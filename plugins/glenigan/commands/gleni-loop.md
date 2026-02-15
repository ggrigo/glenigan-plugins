# Glenigan v2.6.1

---
description: Process Glenigan projects one-by-one through the enrichment pipeline
allowed-tools: ["Bash", "Read", "Write", "mcp__playwright__playwright_navigate", "mcp__playwright__playwright_fill", "mcp__playwright__playwright_click", "mcp__playwright__playwright_evaluate", "mcp__playwright__playwright_screenshot", "mcp__playwright__playwright_get_visible_html", "mcp__playwright__playwright_get_visible_text", "mcp__playwright__playwright_close", "mcp__playwright__playwright_press_key", "mcp__Claude_in_Chrome__find", "mcp__Claude_in_Chrome__navigate", "mcp__Claude_in_Chrome__form_input", "mcp__Claude_in_Chrome__computer", "mcp__Claude_in_Chrome__read_page", "mcp__Claude_in_Chrome__get_page_text", "mcp__Claude_in_Chrome__tabs_context_mcp", "mcp__Claude_in_Chrome__tabs_create_mcp", "Task"]
argument-hint: "[project_id] [--step classify|portal|research|download|analyze|contacts|score|crm] [--region REGION]"
---

# /gleni-loop

Process Glenigan projects one at a time through the full enrichment pipeline. Each project gets complete attention before moving to the next. Designed to run unattended for hours.

## How It Works

Pick a project. Determine what it needs next. Do that step. Move to the next project. Repeat until done.

```
FOR EACH project in queue:
  1. CLASSIFY     → Is it worth pursuing based on predefined criteria?
     REJECTED? → Skip. Next project.
  2. PORTAL       → Has planning ref? Find Idox keyval.
  3. RESEARCH     → Web search for project intel.
  4. DOWNLOAD     → Get planning docs from portal.
  5. ANALYZE      → Read the docs, extract M&E/lighting signals AND contacts (names, emails, phone numbers).
  6. CONTACTS     → Profile the client first, then the architect, assess consultants.
  7. SCORE        → Calculate priority score.
  8. CRM          → Create deal if qualified. Also write to Google Sheets.
  → Next project.
```

## Usage

- `/gleni-loop` — Process all projects, starting from where we left off
- `/gleni-loop 26065152` — Process just this project through all remaining steps
- `/gleni-loop --step portal` — Run only the portal step for the next project that needs it
- `/gleni-loop --step classify --region LONDON` — Classify the next London project
- `/gleni-loop --step portal --region "WEST MIDLANDS"` — Portal lookup for West Midlands projects

## Startup

### 1. Check Database

```python
import sqlite3, os, json
from datetime import datetime, timedelta

workspace = os.environ.get('WORKSPACE', '.')
db_path = os.path.join(workspace, 'glenigan.db')

if not os.path.exists(db_path):
    print("No database found. Run /gleni-init first, then upload a Glenigan PDF.")
    # stop here
```

### 2. Load Playbook + Rules

Two files, two purposes:

- **`config/playbook.md`** — The client's own words. Human voice, human reasoning. Read this for judgment calls and context. This is the source of truth.
- **`config/rules.json`** — Machine-readable rules compiled from the playbook. Sector tiers, value thresholds, exclusion patterns. Code reads this for execution.

When they disagree, the playbook wins. The JSON is a cache of the playbook's intent.

```python
# Read the compiled rules for code execution
config_path = os.path.join(plugin_dir, 'config', 'rules.json')
with open(config_path) as f:
    client = json.load(f)

# Also read the playbook for judgment context
playbook_path = os.path.join(plugin_dir, 'config', 'playbook.md')
with open(playbook_path) as f:
    playbook = f.read()
```

### 3. Check Browser Availability (only needed if portal/download steps will run)

Before any portal or document work, verify browser tools exist:

```python
# Try playwright_navigate to about:blank
# If tool not found, check Chrome MCP tools
# If neither available, skip portal/download steps and note it
```

### 4. Pick Next Project

If a specific project_id was given, use that. Otherwise, query for the next project that needs work.

The queue is ordered by: highest value first, connected portals first, QUALIFIED before MAYBE.

```sql
-- Find the next project that needs ANY enrichment step
SELECT
    p.project_id,
    p.title,
    p.town,
    p.region,
    p.value_numeric,
    p.planning_ref,
    p.planning_authority,
    p.scheme_description,
    p.start_date,
    p.value_basis,
    ec.status AS classification,
    ep.portal_status,
    ep.keyval,
    ew.project_id AS has_web,
    ect.project_id AS has_contacts,
    es.project_id AS has_scoring,
    cd.project_id AS has_deal,
    GROUP_CONCAT(DISTINCT s.sector_name) AS sectors
FROM projects p
LEFT JOIN enrichment_classification ec ON p.project_id = ec.project_id
LEFT JOIN enrichment_portal ep ON p.project_id = ep.project_id
LEFT JOIN enrichment_web ew ON p.project_id = ew.project_id
LEFT JOIN enrichment_contacts ect ON p.project_id = ect.project_id
LEFT JOIN enrichment_scoring es ON p.project_id = es.project_id
LEFT JOIN crm_deals cd ON p.project_id = cd.project_id
LEFT JOIN sectors s ON p.project_id = s.project_id
LEFT JOIN portal_registry pr ON p.planning_authority = pr.authority_name
WHERE p.merged_into IS NULL
  AND (
    ec.project_id IS NULL                           -- needs classification
    OR (ec.status IN ('QUALIFIED','MAYBE') AND (
        ep.project_id IS NULL                       -- needs portal
        OR ew.project_id IS NULL                    -- needs web research
        OR ect.project_id IS NULL                   -- needs contacts
        OR es.project_id IS NULL                    -- needs scoring
        OR cd.project_id IS NULL                    -- needs CRM deal
    ))
  )
GROUP BY p.project_id
ORDER BY
    -- Prioritize: unclassified first, then by value
    CASE WHEN ec.project_id IS NULL THEN 0 ELSE 1 END,
    CASE WHEN ec.status = 'QUALIFIED' THEN 0 WHEN ec.status = 'MAYBE' THEN 1 ELSE 2 END,
    CASE WHEN pr.connectivity = 'connected' THEN 0 WHEN pr.connectivity = 'untested' THEN 1 ELSE 2 END,
    p.value_numeric DESC
LIMIT 1;
```

If `--region` is specified, add `AND p.region = ?` to the WHERE clause.
If `--step` is specified, adjust the WHERE clause to only find projects needing that specific step.

## State Machine: Determine Next Step

For the selected project, determine what it needs:

```python
def next_step(project):
    """Returns the next enrichment step needed for this project."""
    if project['classification'] is None:
        return 'classify'
    if project['classification'] == 'REJECTED':
        return 'done'  # skip to next project
    if project['portal_status'] is None and project['planning_ref']:
        return 'portal'
    if project['has_web'] is None:
        return 'research'
    # Download only if portal is CRAWLABLE
    if project['portal_status'] == 'CRAWLABLE' and project['keyval']:
        has_docs = c.execute(
            "SELECT COUNT(*) FROM downloaded_documents WHERE project_id = ?",
            (project['project_id'],)
        ).fetchone()[0]
        if has_docs == 0:
            return 'download'
        # Check if docs need analysis
        unanalyzed = c.execute(
            "SELECT COUNT(*) FROM downloaded_documents WHERE project_id = ? AND content_summary IS NULL",
            (project['project_id'],)
        ).fetchone()[0]
        if unanalyzed > 0:
            return 'analyze'
    if project['has_contacts'] is None:
        return 'contacts'
    if project['has_scoring'] is None:
        return 'score'
    if project['has_deal'] is None and project['classification'] == 'QUALIFIED':
        return 'crm'
    return 'done'
```

## Step Execution

### CLASSIFY

Read `references/classification.md` for the full decision tree and rules.

For a single project, use Method A (local decision tree) directly:

1. Load playbook (sector mappings, value thresholds, exclusion patterns)
2. Run pre-filters: minor alterations, sports outdoor, timing risk, small project
3. Apply decision tree
4. Calculate confidence score
5. Write one-sentence reasoning

```python
now = datetime.utcnow().isoformat() + 'Z'

# Apply classification logic from references/classification.md
# Result: status (QUALIFIED/MAYBE/REJECTED), vertical, confidence, reasoning

c.execute("""
    INSERT OR REPLACE INTO enrichment_classification
    (project_id, status, vertical, reasoning, confidence, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, ?, 'gleni-loop')
""", (project_id, status, vertical, reasoning, confidence, now))

c.execute("""
    INSERT INTO processing_log (project_id, stage, timestamp, skill, notes)
    VALUES (?, 'classified', ?, 'gleni-loop', ?)
""", (project_id, now, f"{status} ({vertical})"))

conn.commit()
```

Report: `"Project {id}: {title} (£{value}) → {status} ({reasoning})"`

If REJECTED, move to next project immediately.

### PORTAL

Read `references/portals.md` for the full extraction logic.

**Decision tree:**

```
Has planning_ref?
  NO → Mark UNMAPPABLE. Move to RESEARCH step.
  YES →
    Authority in portal_registry?
      YES, connected → Use stored portal_url. Extract keyval.
      YES, failed → Check last_error. If PORTAL_MAINTENANCE and last_attempt > 7 days, retry. Otherwise skip.
      YES, untested → Attempt discovery.
      NO → Attempt discovery.
```

**Discovery** (if needed):
1. Check `references/portals.md` → Portal Registry section for known URLs
2. If not listed, try URL pattern cascade from Portal URL Verifier section
3. If still not found, Google: `"{planning_authority}" council planning applications`

**Extraction** (for Idox portals):
1. Navigate to `{portal_url}/search.do?action=advanced`
2. Detect field pattern (run universal detection script from references/portals.md)
3. Generate ref variants using `generateRefVariants()` from references/portals.md
4. Try original ref first, then variants
5. Extract keyval from results
6. Construct direct access URLs

**Write results:**

```python
if keyval:
    portal_status = 'CRAWLABLE'
elif portal_errored:
    portal_status = 'PORTAL_MAINTENANCE'
else:
    portal_status = 'UNMAPPABLE'

c.execute("""
    INSERT OR REPLACE INTO enrichment_portal
    (project_id, portal_status, portal_url, portal_type, keyval,
     verified_ref, csrf_required, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'gleni-loop')
""", (project_id, portal_status, portal_url, portal_type, keyval,
      planning_ref, csrf_required, now))

# Update portal_registry
c.execute("""
    INSERT INTO portal_registry (authority_name, portal_url, portal_type, connectivity, last_attempt, last_success, success_count)
    VALUES (?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(authority_name) DO UPDATE SET
        portal_url = COALESCE(excluded.portal_url, portal_registry.portal_url),
        connectivity = CASE WHEN ? IS NOT NULL THEN 'connected' ELSE portal_registry.connectivity END,
        last_attempt = excluded.last_attempt,
        last_success = CASE WHEN ? IS NOT NULL THEN excluded.last_success ELSE portal_registry.last_success END,
        success_count = CASE WHEN ? IS NOT NULL THEN portal_registry.success_count + 1 ELSE portal_registry.success_count END
""", (authority, portal_url, portal_type, now, now, keyval, keyval, keyval))

conn.commit()
```

Report: `"Project {id}: Portal {authority} → {status} (keyval: {keyval or 'none'})"`

**Rate limiting:** Wait 2s between searches. Westminster/London boroughs: 3-5s. After error: 5-10s.

### RESEARCH

Web research using search tools. No browser needed.

1. Search for: `"{planning_ref}" {town}` or `"{title}" {town} planning`
2. Read top results
3. Write a 400-word summary covering: what's being built, scale, who's involved, timeline, M&E/lighting/sustainability mentions
4. Assess second_pass_status: CONFIRMED / UPGRADED / DOWNGRADED

For deeper analysis, spawn a haiku subagent using the Enrichment Prompt from `references/prompts.md`.

```python
c.execute("""
    INSERT OR REPLACE INTO enrichment_web
    (project_id, summary, second_pass_status, sources, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, 'gleni-loop')
""", (project_id, summary, second_pass_status, json.dumps(sources), now))
conn.commit()
```

Report: `"Project {id}: Web research → {second_pass_status}. {one_line_summary}"`

### DOWNLOAD

Read `references/documents.md` for the full download logic.

**Requires:** CRAWLABLE portal status + keyval.

1. Navigate directly: `{portal_url}/applicationDetails.do?keyVal={keyval}&activeTab=documents`
2. List available documents
3. Classify each by priority using playbook (`config/rules.json` → `document_priorities`)
4. Download HIGH priority first, then MEDIUM. Skip LOW.
5. Save to `{workspace}/documents/{project_id}/`
6. Record in `downloaded_documents` table

**Method waterfall:** Playwright click (95%) → Playwright fetch (85%) → Chrome MCP click (90%) → JSZip batch (80%) → Direct HTTP (15%)

**Always download regardless of playbook:** Decision Notice, Design & Access Statement, Officer Report.

Report: `"Project {id}: Downloaded {n} documents from {authority} portal"`

### ANALYZE

Read `references/documents.md` → Analysis section.

**Requires:** Downloaded documents with no `content_summary`.

1. Read each PDF with pdfplumber
2. Scan for: size indicators, energy/sustainability keywords, lighting scope, M&E mentions
3. Extract any contacts found in documents: names (first + surname), email addresses, phone numbers. Strongly prioritise phone numbers.
4. Write max 200-word summary per document
5. If significant findings (explicit lighting/energy scope), add `crm_note`
6. If contacts found, store them alongside the document summary for the CONTACTS step

```python
c.execute("""
    UPDATE downloaded_documents SET content_summary = ? WHERE id = ?
""", (summary, doc_id))

# If significant
if found_lighting or found_energy:
    c.execute("""
        INSERT INTO crm_notes (project_id, note, created_at)
        VALUES (?, ?, ?)
    """, (project_id, f"DOCUMENT ANALYSIS: {key_findings}", now))
conn.commit()
```

Report: `"Project {id}: Analyzed {n} documents. {key_findings_summary}"`

### CONTACTS

Read `references/contacts.md` for the full profiling logic.

**Part A: Client Profiling** (NEW — profile client FIRST)

1. Find client/promoter role for this project
2. Research the client company: what they do, size, decision-makers
3. Assess contact quality (email, phone)
4. Note any existing relationship (check `existing_clients` in config)

**Part B: Architect Profiling**

1. Find architect role for this project
2. Spawn a haiku subagent using the Architect Profile Prompt from `references/prompts.md`
3. Assess email quality (HIGH/MEDIUM/LOW), phone quality (HIGH/MEDIUM/LOW)
4. Recommend outreach action: PHONE → EMAIL → LINKEDIN → RESEARCH_NEEDED
5. If direct outreach is recommended, draft the outreach messaging using `outreach_context` from config

```python
c.execute("""
    INSERT OR REPLACE INTO enrichment_contacts
    (project_id, architect_quality, linkedin_urls, outreach_action, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, 'gleni-loop')
""", (project_id, quality_json, linkedin_json, recommended_action, now))
conn.commit()
```

**Part C: Consultant Competitive Analysis** (if relevant consultants exist)

Most projects only have Client + Architect. If M&E, lighting, energy, or sustainability consultants are listed:
1. Classify type (relevant or not) using Consultant Type Prompt from `references/prompts.md`
2. If relevant, assess competitive position using Consultant Competitive Prompt
3. Store in `crm_notes`

Report: `"Project {id}: Architect {company} — {quality} quality, recommend {action}"`

### SCORE

Calculate priority score using the scoring logic from `references/classification.md`.

```python
# Factor: Start Date (0-30 points)
if not start_date:
    factor_start = 15  # unknown
else:
    months = (datetime.strptime(start_date, '%Y-%m-%d') - datetime.utcnow()).days / 30
    if months <= 1: factor_start = 30
    elif months <= 3: factor_start = 27
    elif months <= 6: factor_start = 21
    elif months <= 12: factor_start = 15
    elif months <= 18: factor_start = 12
    else: factor_start = 9

# Factor: Vertical (0-25 points)
scoring = client.get('scoring', {})
if vertical == 'STRONG':
    factor_vertical = scoring.get('vertical_strong', 25)
elif vertical == 'GOOD':
    factor_vertical = scoring.get('vertical_good', 10)
else:
    factor_vertical = 0

# Factor: Value (0-50 points, 5 per £100k, capped)
factor_value = min(int(value_numeric / 100000) * scoring.get('value_per_100k', 5),
                   scoring.get('value_cap', 50))

# Factor: Second Pass adjustment
factor_second = 0
if second_pass_status == 'UPGRADED':
    factor_second = scoring.get('second_pass_upgraded', 15)
elif second_pass_status == 'CONFIRMED':
    factor_second = scoring.get('second_pass_confirmed', 5)
elif second_pass_status == 'DOWNGRADED':
    factor_second = scoring.get('second_pass_downgraded', -10)

# Factor: Existing client (+20)
factor_client = 0
roles = c.execute("SELECT company_name FROM project_roles WHERE project_id = ?", (project_id,)).fetchall()
existing = set(client.get('existing_clients', []))
if any(r[0] in existing for r in roles):
    factor_client = scoring.get('existing_client', 20)

priority_score = factor_start + factor_vertical + factor_value + factor_second + factor_client

c.execute("""
    INSERT OR REPLACE INTO enrichment_scoring
    (project_id, priority_score, factor_start_date, factor_vertical, factor_value,
     factor_second_pass, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'gleni-loop')
""", (project_id, priority_score, factor_start, factor_vertical, factor_value,
      factor_second, now))

# Update rank across all scored projects
c.execute("""
    UPDATE enrichment_scoring SET rank = (
        SELECT COUNT(*) + 1 FROM enrichment_scoring es2
        WHERE es2.priority_score > enrichment_scoring.priority_score
    )
""")
conn.commit()
```

Report: `"Project {id}: Score {priority_score} (start:{factor_start} vertical:{factor_vertical} value:{factor_value} 2nd:{factor_second})"`

### CRM

Create a deal for QUALIFIED projects. Write to both the internal DB and a Google Sheet.

```python
c.execute("""
    INSERT OR IGNORE INTO crm_deals
    (project_id, stage, temperature, deal_value, created_at, updated_at)
    VALUES (?, 'new_lead', 'warm', ?, ?, ?)
""", (project_id, value_numeric, now, now))
conn.commit()
```

**Google Sheets mirror** (required — client needs direct access):

The Google Sheet must contain these columns:
1. **Project Name** — title from Glenigan
2. **Priority Score** — the qualification/priority number from scoring
3. **Glenigan Reference** — the project_id
4. **Status** — QUALIFIED, MAYBE, or REJECTED

Update the sheet after every CRM write. The client uses this to monitor the pipeline without needing access to the database.

Report: `"Project {id}: Deal created — £{value}, new_lead, warm. Sheet updated."`

## Loop Behavior

After completing all steps for one project, immediately pick the next project from the queue and repeat. Continue until:

- No more projects need work (queue is empty)
- A step fails in an unrecoverable way (report the error and move to next project)

**Never stop on a single failure.** Log the error, mark the relevant enrichment as failed/maintenance, and continue to the next project.

**Progress reporting:** After every project, print a one-line status:

```
[3/47] 26065152 — Light Industrial/Warehouse (£3.9M) — QUALIFIED, CRAWLABLE, scored 85 ✓
[4/47] 26070881 — Office Refurbishment (£1.2M) — MAYBE, UNMAPPABLE, scored 42 ✓
[5/47] 26061179 — Retail Unit (£150K) — REJECTED (minor works) ✗
```

## Single-Step Mode

When `--step` is specified, only run that one step:

- `--step classify` → Find next unclassified project, classify it, stop
- `--step portal` → Find next project without portal data, run portal lookup, stop
- `--step research` → Find next project without web research, research it, stop
- `--step download` → Find next CRAWLABLE project without documents, download, stop
- `--step analyze` → Find next project with unanalyzed documents, analyze, stop
- `--step contacts` → Find next project without contact profiling, profile, stop
- `--step score` → Find next unscored project, score it, stop
- `--step crm` → Find next qualified project without a deal, create deal, stop

After the single step, print the result and append the nudge from `references/nudge.md`.

## Error Handling

| Error | Action |
|-------|--------|
| Portal timeout | Mark PORTAL_MAINTENANCE, skip to RESEARCH |
| Cloudflare block | Wait 10s, retry once. If still blocked, mark PORTAL_MAINTENANCE |
| CAPTCHA | Mark PORTAL_MAINTENANCE (needs Chrome MCP with user interaction) |
| No planning ref | Mark UNMAPPABLE, skip to RESEARCH |
| Non-Idox portal | Mark portal_type, skip to RESEARCH |
| PDF read failure | Log error, skip ANALYZE for that document |
| Web search no results | Write "No web data found" as summary, mark CONFIRMED |
| DB write failure | Log error, stop loop, report |

## Nudge

After the loop completes (or after single-step mode), always generate a nudge using `references/nudge.md`. This tells the user what's left to do.

## Reference Files

This command reads these reference docs as needed during execution:

| Step | Reference |
|------|-----------|
| Always | `config/playbook.md` (source of truth — the client's own words) |
| CLASSIFY | `references/classification.md`, `config/rules.json` |
| PORTAL | `references/portals.md` |
| RESEARCH | `references/prompts.md` (Enrichment Prompt) |
| DOWNLOAD | `references/documents.md`, `config/rules.json` |
| ANALYZE | `references/documents.md` |
| CONTACTS | `references/contacts.md`, `references/prompts.md`, `config/rules.json` |
| SCORE | `references/classification.md` (scoring section), `config/rules.json` |
| Always | `references/nudge.md` |
