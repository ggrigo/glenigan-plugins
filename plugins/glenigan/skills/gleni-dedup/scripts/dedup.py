#!/usr/bin/env python3
"""
Glenigan Pipeline Deduplication — Confidence Scoring Engine

Replaces the old three-tier system with a single scoring function that
compounds multiple weak signals into strong evidence.

Usage:
  python3 dedup.py glenigan.db                       # Full scan, auto-merge >= 70
  python3 dedup.py glenigan.db --dry-run              # Report only
  python3 dedup.py glenigan.db --threshold 50         # Lower auto-merge bar
  python3 dedup.py glenigan.db --project 26060066     # Check single project
  python3 dedup.py glenigan.db --json                 # Machine-readable output
"""

import sqlite3
import argparse
import json
import re
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

def ensure_columns(conn):
    """Add dedup columns to projects if missing."""
    cursor = conn.execute("PRAGMA table_info(projects)")
    existing = {row[1] for row in cursor.fetchall()}
    migrations = {
        "merged_into": "ALTER TABLE projects ADD COLUMN merged_into TEXT DEFAULT NULL",
        "merge_reason": "ALTER TABLE projects ADD COLUMN merge_reason TEXT DEFAULT NULL",
        "merge_score": "ALTER TABLE projects ADD COLUMN merge_score INTEGER DEFAULT NULL",
        "merged_at": "ALTER TABLE projects ADD COLUMN merged_at TEXT DEFAULT NULL",
    }
    for col, ddl in migrations.items():
        if col not in existing:
            conn.execute(ddl)
    conn.commit()


# ---------------------------------------------------------------------------
# Tokenization and similarity
# ---------------------------------------------------------------------------

NOISE = {'the', 'and', 'of', 'a', 'an', 'in', 'at', 'to', 'not', 'available', 'for', 'on'}

ABBREVIATIONS = {
    'rd': 'road', 'st': 'street', 'ave': 'avenue', 'dr': 'drive',
    'ln': 'lane', 'ct': 'court', 'pl': 'place', 'sq': 'square',
    'cres': 'crescent', 'cl': 'close', 'gdns': 'gardens', 'pk': 'park',
    'hse': 'house', 'bldg': 'building', 'bldgs': 'buildings',
}

GENERIC_TITLE = {
    'alteration', 'conversion', 'refurbishment', 'new', 'build',
    'extension', 'demolition', 'renovation', 'work', 'erection',
    'construction', 'replacement', 'installation', 'removal', 'repair',
    'improvement', 'change', 'use', 'proposed', 'existing',
}


def deplural(t):
    """Naive depluralization: strip trailing 's' unless double-s."""
    if len(t) > 3 and t.endswith('s') and t[-2] != 's':
        return t[:-1]
    return t


def tokenize(text):
    """Split text into normalized token set."""
    if not text:
        return set()
    tokens = re.split(r'[\s/\(\)\-,\.;:&]+', text.lower())
    result = set()
    for t in tokens:
        t = t.strip()
        if not t or t in NOISE:
            continue
        t = ABBREVIATIONS.get(t, t)
        t = deplural(t)
        result.add(t)
    return result


def token_overlap(a, b):
    """Jaccard similarity between two token sets."""
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def meaningful_shared(a, b):
    """Return shared tokens between a and b that aren't generic title words."""
    ta, tb = tokenize(a), tokenize(b)
    return [t for t in ta & tb if t not in GENERIC_TITLE]


def normalize_postcode(pc):
    """Strip spaces and uppercase for comparison."""
    if not pc or pc == 'Not Available':
        return None
    return re.sub(r'\s+', '', pc.upper())


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def score_pair(a, b):
    """
    Score the likelihood that two project dicts represent the same physical project.
    Returns (score, signals_list).
    """
    score = 0
    signals = []

    # Signal 1: Same planning_ref + planning_authority (+40)
    ref_a = (a.get('planning_ref') or '').strip()
    ref_b = (b.get('planning_ref') or '').strip()
    auth_a = (a.get('planning_authority') or '').strip().lower()
    auth_b = (b.get('planning_authority') or '').strip().lower()
    if ref_a and ref_b and ref_a != 'N/A' and ref_b != 'N/A':
        if ref_a == ref_b and auth_a == auth_b:
            score += 40
            signals.append(f"ref:{ref_a}@{auth_a} +40")

    # Signal 2: Same pp_reference (+35)
    pp_a = (a.get('pp_reference') or '').strip()
    pp_b = (b.get('pp_reference') or '').strip()
    if pp_a and pp_b and pp_a == pp_b:
        score += 35
        signals.append(f"pp:{pp_a} +35")

    # Signal 3: Same postcode (+30)
    pc_a = normalize_postcode(a.get('postcode'))
    pc_b = normalize_postcode(b.get('postcode'))
    strong_location = False
    if pc_a and pc_b and pc_a == pc_b:
        score += 30
        signals.append(f"postcode:{pc_a} +30")
        strong_location = True

    # Signal 4: Address token overlap >= 60% (+25) or >= 40% (+15)
    addr_overlap = token_overlap(a.get('address_full', ''), b.get('address_full', ''))
    if addr_overlap >= 0.6:
        score += 25
        signals.append(f"address:{addr_overlap:.0%} +25")
        strong_location = True
    elif addr_overlap >= 0.4:
        score += 15
        signals.append(f"address:{addr_overlap:.0%} +15")

    # Signal 5: Title token overlap >= 50% (+20) or >= 30% (+10)
    title_overlap = token_overlap(a.get('title', ''), b.get('title', ''))
    if title_overlap >= 0.5:
        score += 20
        signals.append(f"title:{title_overlap:.0%} +20")
    elif title_overlap >= 0.3:
        score += 10
        signals.append(f"title:{title_overlap:.0%} +10")

    # Signal 5b: Combo bonus — strong location + 2+ meaningful shared title tokens (+10)
    if strong_location:
        shared = meaningful_shared(a.get('title', ''), b.get('title', ''))
        if len(shared) >= 2:
            score += 10
            signals.append(f"combo:{'+'.join(shared)} +10")

    # Signal 6: Value within 20% (+10)
    val_a = a.get('value_numeric') or 0
    val_b = b.get('value_numeric') or 0
    if val_a > 0 and val_b > 0:
        diff = abs(val_a - val_b)
        threshold = 0.2 * max(val_a, val_b)
        if diff <= threshold:
            score += 10
            signals.append(f"value:~{diff/max(val_a,val_b):.0%}diff +10")
    elif val_a == 0 and val_b == 0:
        # Both zero-value: mild supporting signal
        score += 5
        signals.append("value:both_zero +5")

    # Signal 7: Same town (+5)
    town_a = (a.get('town') or '').strip().lower()
    town_b = (b.get('town') or '').strip().lower()
    if town_a and town_b and town_a == town_b:
        score += 5
        signals.append(f"town:{town_a} +5")

    return min(score, 100), signals


# ---------------------------------------------------------------------------
# Classification rank (for keeper selection)
# ---------------------------------------------------------------------------

CLASS_RANK = {"QUALIFIED": 3, "MAYBE": 2, "REJECTED": 1}


def get_classification(conn, project_id):
    row = conn.execute(
        "SELECT status FROM enrichment_classification WHERE project_id = ?",
        (project_id,)
    ).fetchone()
    return row[0] if row else None


def pick_keeper(conn, id_a, id_b, imp_a, imp_b):
    """Pick keeper: highest classification, then newest import."""
    cls_a = CLASS_RANK.get(get_classification(conn, id_a), 0)
    cls_b = CLASS_RANK.get(get_classification(conn, id_b), 0)
    if cls_a > cls_b:
        return id_a
    if cls_b > cls_a:
        return id_b
    # Same rank: newest wins
    return id_a if (imp_a or '') >= (imp_b or '') else id_b


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

ENRICHMENT_TABLES = [
    "enrichment_classification", "enrichment_portal", "enrichment_web",
    "enrichment_contacts", "enrichment_scoring",
]


def migrate_enrichment(conn, keeper_id, archive_id):
    migrated = []
    for table in ENRICHMENT_TABLES:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        if not exists:
            continue
        archived_has = conn.execute(
            f"SELECT 1 FROM {table} WHERE project_id = ?", (archive_id,)
        ).fetchone()
        keeper_has = conn.execute(
            f"SELECT 1 FROM {table} WHERE project_id = ?", (keeper_id,)
        ).fetchone()
        if archived_has and not keeper_has:
            conn.execute(
                f"UPDATE {table} SET project_id = ? WHERE project_id = ?",
                (keeper_id, archive_id)
            )
            migrated.append(table)
    return migrated


def do_merge(conn, keeper_id, archive_id, score, signals, dry_run=False):
    now = datetime.now(timezone.utc).isoformat()
    reason = " | ".join(signals)
    record = {
        "keeper": keeper_id,
        "archived": archive_id,
        "score": score,
        "signals": signals,
        "reason": reason,
        "timestamp": now,
        "enrichment_migrated": [],
    }
    if dry_run:
        return record

    record["enrichment_migrated"] = migrate_enrichment(conn, keeper_id, archive_id)

    conn.execute("""
        UPDATE projects SET merged_into=?, merge_reason=?, merge_score=?, merged_at=?
        WHERE project_id=?
    """, (keeper_id, reason, score, now, archive_id))

    conn.execute("""
        INSERT INTO crm_notes (project_id, note, created_at) VALUES (?, ?, ?)
    """, (keeper_id, f"DEDUP: Merged {archive_id} (score:{score}). {reason}", now))

    return record


# ---------------------------------------------------------------------------
# Full scan: score all pairs within same postcode or same town
# ---------------------------------------------------------------------------

def load_active_projects(conn):
    cols = [d[1] for d in conn.execute("PRAGMA table_info(projects)").fetchall()]
    rows = conn.execute(
        "SELECT * FROM projects WHERE merged_into IS NULL"
    ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def find_candidate_pairs(projects):
    """
    Generate candidate pairs efficiently using blocking on postcode and town.
    Only pairs that share a postcode or town are scored (avoids N^2).
    """
    from collections import defaultdict

    pc_blocks = defaultdict(list)
    town_blocks = defaultdict(list)

    for p in projects:
        pc = normalize_postcode(p.get('postcode'))
        if pc:
            pc_blocks[pc].append(p)
        town = (p.get('town') or '').strip().lower()
        if town:
            town_blocks[town].append(p)

    seen = set()
    pairs = []

    for block in list(pc_blocks.values()) + list(town_blocks.values()):
        for i in range(len(block)):
            for j in range(i + 1, len(block)):
                a, b = block[i], block[j]
                key = tuple(sorted([a['project_id'], b['project_id']]))
                if key not in seen:
                    seen.add(key)
                    pairs.append((a, b))
    return pairs


def full_scan(conn, threshold=70, dry_run=False):
    projects = load_active_projects(conn)
    pairs = find_candidate_pairs(projects)

    auto_merges = []
    flagged = []

    # Score all pairs
    scored = []
    for a, b in pairs:
        score, signals = score_pair(a, b)
        if score >= 40:
            scored.append((score, signals, a, b))

    # Sort by score descending so we merge the strongest matches first
    scored.sort(key=lambda x: -x[0])

    # Track which projects have been archived (to avoid double-merging)
    archived = set()

    for score, signals, a, b in scored:
        if a['project_id'] in archived or b['project_id'] in archived:
            continue

        if score >= threshold:
            keeper_id = pick_keeper(
                conn, a['project_id'], b['project_id'],
                a.get('imported_at', ''), b.get('imported_at', '')
            )
            archive_id = b['project_id'] if keeper_id == a['project_id'] else a['project_id']
            record = do_merge(conn, keeper_id, archive_id, score, signals, dry_run)
            auto_merges.append(record)
            archived.add(archive_id)
        else:
            flagged.append({
                "id_a": a['project_id'],
                "id_b": b['project_id'],
                "score": score,
                "signals": signals,
                "title_a": a.get('title', ''),
                "title_b": b.get('title', ''),
                "address_a": a.get('address_full', ''),
                "address_b": b.get('address_full', ''),
                "postcode": a.get('postcode', ''),
            })

    if not dry_run:
        conn.commit()

    return auto_merges, flagged


# ---------------------------------------------------------------------------
# Single project check (for ingestion-time use)
# ---------------------------------------------------------------------------

def check_project(conn, project_dict, threshold=70):
    """
    Score a new project against all active rows.
    Returns list of (existing_id, score, signals) sorted by score desc.
    """
    actives = load_active_projects(conn)
    matches = []
    for existing in actives:
        if existing['project_id'] == project_dict.get('project_id'):
            continue
        score, signals = score_pair(project_dict, existing)
        if score >= 40:
            matches.append((existing['project_id'], score, signals))
    matches.sort(key=lambda x: -x[1])
    return matches


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def build_report(auto_merges, flagged, total_before, total_after, dry_run):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if dry_run else "executed",
        "summary": {
            "projects_before": total_before,
            "projects_after": total_after,
            "auto_merged": len(auto_merges),
            "flagged_for_review": len(flagged),
        },
        "auto_merges": auto_merges,
        "flagged": flagged,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Glenigan dedup (confidence scoring)")
    parser.add_argument("db", help="Path to glenigan.db")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no merges")
    parser.add_argument("--threshold", type=int, default=70, help="Auto-merge threshold (default: 70)")
    parser.add_argument("--project", help="Check single project_id")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_columns(conn)

    # Single project mode
    if args.project:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(projects)").fetchall()]
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (args.project,)
        ).fetchone()
        if not row:
            print(f"Project {args.project} not found.")
            sys.exit(1)
        project = dict(zip(cols, row))
        matches = check_project(conn, project, args.threshold)
        if args.json:
            print(json.dumps(matches, indent=2))
        elif matches:
            print(f"Matches for {args.project}:")
            for eid, score, signals in matches:
                action = "AUTO-MERGE" if score >= args.threshold else "REVIEW"
                print(f"  {eid}  score:{score}  [{action}]  {' | '.join(signals)}")
        else:
            print(f"No duplicates found for {args.project}")
        conn.close()
        return

    # Full scan
    total_before = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE merged_into IS NULL"
    ).fetchone()[0]

    auto_merges, flagged = full_scan(conn, args.threshold, args.dry_run)

    total_after = conn.execute(
        "SELECT COUNT(*) FROM projects WHERE merged_into IS NULL"
    ).fetchone()[0]

    report = build_report(auto_merges, flagged, total_before, total_after, args.dry_run)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        mode = "DRY RUN" if args.dry_run else "EXECUTED"
        s = report["summary"]
        print(f"=== DEDUPLICATION REPORT ({mode}) ===\n")

        if auto_merges:
            label = "Would auto-merge" if args.dry_run else "Auto-merged"
            print(f"{label} (score >= {args.threshold}):")
            for m in auto_merges:
                print(f"  {m['archived']} -> {m['keeper']}  score:{m['score']}  [{' | '.join(m['signals'])}]")
            print()

        if flagged:
            print(f"Flagged for review (score 40-{args.threshold - 1}):")
            for i, f in enumerate(flagged, 1):
                print(f"  {i}. \"{f['title_a']}\" vs \"{f['title_b']}\"  score:{f['score']}  {f['postcode']}")
                print(f"     A: {f['id_a']} ({f['address_a'][:50]})")
                print(f"     B: {f['id_b']} ({f['address_b'][:50]})")
            print()

        if not auto_merges and not flagged:
            print("No duplicates found.\n")

        print(f"Active projects: {s['projects_before']} -> {s['projects_after']}")

    conn.close()


if __name__ == "__main__":
    main()
