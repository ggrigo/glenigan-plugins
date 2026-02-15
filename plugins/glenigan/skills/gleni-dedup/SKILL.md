# Glenigan v2.6.1

---
name: gleni-dedup
description: >
  Detect and resolve duplicate projects in the Glenigan pipeline database.
  Use this skill whenever the user says "deduplicate", "find duplicates",
  "merge duplicates", "clean duplicates", "remove dupes", "check for duplicates",
  "duplicate check", or "dedup". Also trigger when the user imports a second
  Glenigan PDF and you suspect overlapping projects. This skill both DETECTS
  existing duplicates (post-hoc cleanup) and PREVENTS new ones at ingestion time
  via a single confidence-scoring function embedded in gleni-ingest.
---

# Deduplicate Glenigan Projects

Duplicates enter the pipeline from overlapping Glenigan PDF exports. The same physical project can appear with a different Glenigan ID, reshuffled address text, different title wording, and even different planning refs across two exports. The old three-tier system (exact ref, address, fuzzy) missed real duplicates because it treated each signal independently. This skill uses a single confidence-scoring function that compounds multiple weak signals into strong evidence.

## How It Works: Confidence Scoring

Every candidate pair gets a **match score** (0-100) built from independent signals. Multiple partial matches accumulate, so a pair that matches on postcode + partial title + partial address scores higher than any single signal alone.

### Signals

| Signal | Points | Why it works |
|--------|--------|-------------|
| Same `planning_ref` + `planning_authority` | +40 | Same application, strongest identifier |
| Same `pp_reference` | +35 | Same Planning Portal entry |
| Same postcode | +30 | 96% coverage in DB; narrows to same street |
| Address token overlap >= 60% | +25 | Catches reshuffled/reformatted addresses |
| Address token overlap >= 40% | +15 | Partial address overlap (same street, different unit) |
| Title token overlap >= 50% | +20 | "Pavilion (Alterations)" vs "Pavilion Building (Refurbishment)" |
| Title token overlap >= 30% | +10 | Partial title overlap |
| Combo: strong location + 2 meaningful title tokens | +10 | Rewards pairs with both location AND substance match |
| Value within 20% (both > 0) | +10 | Supporting evidence, not standalone |
| Both values zero | +5 | Mild supporting signal |
| Same town | +5 | Weak but useful tiebreaker |

Signals are additive. The **combo bonus** fires only when a pair has strong location evidence (postcode match or address >= 60%) AND shares at least 2 meaningful title tokens (excluding generic building words like "alteration", "conversion", "refurbishment", etc). This prevents false positives from pairs that share only a generic word like "offices".

### Thresholds

| Score | Action |
|-------|--------|
| >= 70 | **Auto-merge.** High confidence. Log to `crm_notes`. |
| 40-69 | **Flag for review.** Present side-by-side, user decides. |
| < 40 | **Separate projects.** No action. |

### Token Overlap

Tokenization splits on spaces, slashes, parentheses, and hyphens. Common noise words are stripped: "the", "and", "of", "a". Comparison uses Jaccard similarity (intersection / union of token sets).

```python
NOISE = {'the', 'and', 'of', 'a', 'an', 'in', 'at', 'to', 'not', 'available', 'for', 'on'}
ABBREVIATIONS = {'rd': 'road', 'st': 'street', 'ave': 'avenue', 'dr': 'drive',
                 'ln': 'lane', 'ct': 'court', 'pl': 'place', 'sq': 'square',
                 'cres': 'crescent', 'cl': 'close', 'gdns': 'gardens', 'pk': 'park',
                 'hse': 'house', 'bldg': 'building', 'bldgs': 'buildings'}
GENERIC_TITLE = {'alteration', 'conversion', 'refurbishment', 'new', 'build',
                 'extension', 'demolition', 'renovation', 'work', 'erection',
                 'construction', 'replacement', 'installation', 'removal', 'repair',
                 'improvement', 'change', 'use', 'proposed', 'existing'}

def deplural(t):
    if len(t) > 3 and t.endswith('s') and t[-2] != 's':
        return t[:-1]
    return t

def tokenize(text):
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
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
```

### Address & Title Normalization

Before comparing, tokens are: lowercased, abbreviation-expanded (Rd→Road, St→Street, etc), depluralized ("offices"→"office", "buildings"→"building"), and stripped of noise words. Comparison uses Jaccard similarity (intersection / union) because Glenigan reshuffles address components between exports.

## Where It Runs

**Primary: Inside `gleni-ingest` at INSERT time.** Before inserting each project, score it against all active rows. If score >= 70, UPDATE the existing record with newer data. If 40-69, flag for review after ingestion completes. If < 40, INSERT as new.

**Secondary: Standalone audit.** User says "deduplicate" or "find duplicates". Scores every active pair and reports matches. This catches duplicates that slipped through (e.g. from before the scoring was added) or when the user wants to review borderline cases.

Run the script:
```bash
python3 scripts/dedup.py glenigan.db                    # Full scan, auto-merge >= 70
python3 scripts/dedup.py glenigan.db --dry-run           # Report only
python3 scripts/dedup.py glenigan.db --threshold 50      # Lower auto-merge bar
python3 scripts/dedup.py glenigan.db --project 26060066  # Check single project
```

## Merge Process

When merging (score >= threshold):

1. **Pick keeper:** Highest classification status (QUALIFIED > MAYBE > REJECTED > none). If tied, newest `imported_at`.
2. **Migrate enrichment:** For each enrichment table, if archived has data the keeper lacks, transfer it.
3. **Soft-delete:** Set `merged_into`, `merge_reason`, `merge_score`, `merged_at` on the archived row. Never hard-delete.
4. **Log:** Insert into `crm_notes` with score and contributing signals.

All pipeline queries filter `WHERE merged_into IS NULL`.

## Schema Additions

On first run, adds columns to `projects` if missing:

| Column | Type | Purpose |
|--------|------|---------|
| `merged_into` | TEXT | project_id this was merged into (NULL = active) |
| `merge_reason` | TEXT | Signal breakdown that triggered merge |
| `merge_score` | INTEGER | Confidence score (0-100) |
| `merged_at` | TEXT | ISO 8601 timestamp |

## What This Catches That Three Tiers Missed

**Vet Practice, CH5 1UA:** Postcode match (30) + address overlap (25) + title overlap "veterinary practice" (20) + combo bonus "veterinary+practice" (10) + value match (10) = **90 → auto-merge**. The old system missed this because the address was reshuffled between exports.

**Pavilion, E10 6RJ:** Postcode match (30) + address overlap (25) + value:both_zero (5) = **60 → flagged for review**. Title overlap is below threshold because "Pavilion (Alterations)" vs "Pavilion Building (Refurbishment)" share only one meaningful token after filtering generic words. The system correctly flags rather than auto-merges, letting the user confirm.

**Offices, BA1 6RS:** Postcode match (30) + address overlap partial (15) + title overlap (10) + town match (5) + value:both_zero (5) = **65 → flagged for review**. Correctly flagged because these are different units (Flat 1 vs 2 Lambridge Buildings) with different application types (FUL vs LBA).

## User Interaction

```
=== DEDUPLICATION REPORT ===

Auto-merged (score >= 70):
  26061201 → 26056756  score:90  Vet Practice, CH5 1UA [postcode+address+title+combo+value]

Flagged for review (score 40-69):
  1. "Pavilion (Alterations)" vs "Pavilion Building (Refurbishment)" at E10 6RJ  score:60
     A: 26060066 (Wardens Residence, Crawley Rd)
     B: 26057931 (Wardens Residence, Crawley Rd)
  2. "Offices" vs "Office Building (Alterations)" at BA1 6RS  score:65
     A: 26061179 (Flat 1, Lambridge Buildings) — ref: 26/00305/FUL
     B: 26061083 (2 Lambridge Buildings) — ref: 26/00292/LBA

Separate projects: 477 active
```

## Post-Dedup Nudge

Read references/nudge.md for the priority waterfall. After deduplication completes, nudge the user: "Deduplicated: {n} auto-merged, {k} flagged for review. Run 'classify projects' to continue."
