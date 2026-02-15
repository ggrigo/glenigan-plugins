# Nudge Reference

Used by all commands and skills to generate next-best-action suggestions.

Generate a short, specific, actionable enrichment suggestion based on current DB state. This is the async heartbeat of the pipeline — since Cowork can't run cron jobs, every interaction is an opportunity to push the pipeline forward.

## Design Principle

Every nudge must be:
1. **Specific** — not "enrich some projects" but "Classify 15 West Midlands industrial projects worth £23M"
2. **Actionable** — the user can say "yes, do it" and Cowork knows exactly what to run
3. **Value-anchored** — always show the £ value at stake to create urgency
4. **One thing** — never suggest two actions. Pick the single highest-impact next step.

## How to Generate the Nudge

Run this Python against `glenigan.db` in the workspace folder:

```python
import sqlite3, json, os

db_path = os.path.join(workspace_folder, 'glenigan.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Counts for each enrichment pass
total = c.execute("SELECT COUNT(*) FROM projects WHERE merged_into IS NULL").fetchone()[0]
classified = c.execute("""
    SELECT COUNT(*) FROM enrichment_classification ec
    JOIN projects p ON ec.project_id = p.project_id
    WHERE p.merged_into IS NULL
""").fetchone()[0]
qualified = c.execute("""
    SELECT COUNT(*) FROM enrichment_classification ec
    JOIN projects p ON ec.project_id = p.project_id
    WHERE ec.status='QUALIFIED' AND p.merged_into IS NULL
""").fetchone()[0]
maybe = c.execute("""
    SELECT COUNT(*) FROM enrichment_classification ec
    JOIN projects p ON ec.project_id = p.project_id
    WHERE ec.status='MAYBE' AND p.merged_into IS NULL
""").fetchone()[0]
portal_done = c.execute("""
    SELECT COUNT(*) FROM enrichment_portal ep
    JOIN projects p ON ep.project_id = p.project_id
    WHERE p.merged_into IS NULL
""").fetchone()[0]
web_done = c.execute("""
    SELECT COUNT(*) FROM enrichment_web ew
    JOIN projects p ON ew.project_id = p.project_id
    WHERE p.merged_into IS NULL
""").fetchone()[0]
contacts_done = c.execute("""
    SELECT COUNT(*) FROM enrichment_contacts ec2
    JOIN projects p ON ec2.project_id = p.project_id
    WHERE p.merged_into IS NULL
""").fetchone()[0]
scored = c.execute("""
    SELECT COUNT(*) FROM enrichment_scoring es
    JOIN projects p ON es.project_id = p.project_id
    WHERE p.merged_into IS NULL
""").fetchone()[0]

# Dedup state: check for potential duplicates needing cleanup
needs_dedup = c.execute("""
    SELECT COUNT(*) FROM (
        SELECT planning_ref, planning_authority, COUNT(*) as cnt
        FROM projects
        WHERE planning_ref IS NOT NULL AND planning_ref != '' AND planning_ref != 'N/A'
          AND merged_into IS NULL
        GROUP BY planning_ref, planning_authority
        HAVING cnt > 1
    )
""").fetchone()[0]

# Also check for recently imported projects that haven't been deduped
# (imported in last session but no dedup log entry after their import)
recent_imports = c.execute("""
    SELECT COUNT(*) FROM projects p
    WHERE p.merged_into IS NULL
      AND p.imported_at > (
          SELECT COALESCE(MAX(created_at), '1970-01-01')
          FROM crm_notes WHERE note LIKE 'DEDUP:%'
      )
""").fetchone()[0]

# What needs doing?
unclassified = total - classified
needs_portal = qualified + maybe - portal_done
needs_web = qualified - web_done
needs_contacts = qualified - contacts_done
needs_scoring = qualified - scored
```

## Nudge Priority Waterfall

Work through this in order. The first match wins:

### Priority 0: No database
If `glenigan.db` doesn't exist → nudge is: "Upload a Glenigan PDF export to get started."

### Priority 0.5: Dedup needed after ingestion
If `needs_dedup > 0` OR (recent imports were loaded from a new PDF source and total PDFs > 1):

This catches the critical moment right after a second (or third, fourth...) PDF import. Overlapping exports are the primary source of duplicates, and classifying or enriching duplicate rows wastes time and muddies scoring.

```python
if needs_dedup > 0:
    nudge = f"🔄 {needs_dedup} potential duplicate ref matches found. Say 'deduplicate' to clean up before classifying."
elif recent_imports > 0:
    pdf_count = c.execute("SELECT COUNT(DISTINCT source_pdf) FROM projects").fetchone()[0]
    if pdf_count > 1:
        nudge = f"🔄 {recent_imports} projects imported from a new PDF. Say 'deduplicate' to check for overlaps with existing data."
```

The reason this sits above classification: enriching or classifying a duplicate row means double the portal lookups, double the web research, and conflicting CRM deals for the same site. Catching duplicates early saves real time downstream.

### Priority 1: Unclassified projects (Pass 1)
If unclassified > 0:

```python
# Find the richest unclassified batch
batch = c.execute("""
    SELECT region, COUNT(*) as cnt, CAST(SUM(value_numeric) AS INTEGER) as total_value
    FROM projects
    WHERE project_id NOT IN (SELECT project_id FROM enrichment_classification)
      AND merged_into IS NULL
    GROUP BY region
    ORDER BY total_value DESC
    LIMIT 1
""").fetchone()
```

Nudge: `"⚡ {unclassified} projects unclassified. Next: Classify {batch.cnt} {batch.region} projects (£{format_value(batch.total_value)}). Say 'classify {batch.region} projects' to start."`

### Priority 2: Portal discovery (Pass 2)
If needs_portal > 0:

```python
# Find the best portal target: connected authority with most unprocessed projects
best_portal = c.execute("""
    SELECT planning_authority, connectivity, COUNT(*) as cnt,
           CAST(SUM(value_numeric) AS INTEGER) as total_value
    FROM v_enrichment_queue
    WHERE planning_ref IS NOT NULL
    GROUP BY planning_authority
    ORDER BY
        CASE WHEN connectivity='connected' THEN 1
             WHEN connectivity='untested' THEN 2
             ELSE 3 END,
        total_value DESC
    LIMIT 1
""").fetchone()
```

Nudge: `"🔍 {needs_portal} projects need portal discovery. Next: Check {best_portal.planning_authority} portal — {best_portal.cnt} projects worth £{format_value(best_portal.total_value)}. Say 'enrich portals for {best_portal.planning_authority}' to start."`

### Priority 3: Web research (Pass 3)
If needs_web > 0:

```python
best_web = c.execute("""
    SELECT p.region, COUNT(*) as cnt, CAST(SUM(p.value_numeric) AS INTEGER) as total_value
    FROM projects p
    JOIN enrichment_classification ec ON p.project_id = ec.project_id
    WHERE ec.status = 'QUALIFIED'
      AND p.project_id NOT IN (SELECT project_id FROM enrichment_web)
      AND p.merged_into IS NULL
    GROUP BY p.region
    ORDER BY total_value DESC
    LIMIT 1
""").fetchone()
```

Nudge: `"🌐 {needs_web} qualified projects need web research. Next: Research {best_web.cnt} {best_web.region} projects (£{format_value(best_web.total_value)}). Say 'research {best_web.region} projects' to start."`

### Priority 4: Contact assessment (Pass 4)
If needs_contacts > 0:

Nudge: `"👤 {needs_contacts} qualified projects need contact assessment. Say 'assess contacts' to start."`

### Priority 5: Scoring
If needs_scoring > 0:

Nudge: `"📊 {needs_scoring} projects ready for priority scoring. Say 'score projects' to finalize the pipeline."`

### Priority 6: CRM actions
All enrichment passes done. Check CRM state:

```python
deals_total = c.execute("SELECT COUNT(*) FROM crm_deals WHERE stage NOT IN ('won','lost','parked')").fetchone()[0]
undealed = c.execute("""
    SELECT COUNT(*) FROM enrichment_classification ec
    WHERE ec.status = 'QUALIFIED'
      AND ec.project_id NOT IN (SELECT project_id FROM crm_deals)
      AND ec.project_id IN (SELECT project_id FROM projects WHERE merged_into IS NULL)
""").fetchone()[0]
overdue = c.execute("SELECT COUNT(*) FROM v_crm_overdue").fetchone()[0]
today_actions = c.execute("SELECT COUNT(*) FROM v_crm_today").fetchone()[0]
```

**6a. Qualified projects not in CRM:**
If undealed > 0:
Nudge: `"📋 {undealed} qualified projects not yet in CRM. Say 'add qualified to CRM' to create deals."`

**6b. Overdue follow-ups:**
If overdue > 0:
Nudge: `"⏰ {overdue} overdue follow-ups. Say '/glenigan-crm overdue' to see them."`

**6c. Today's actions:**
If today_actions > 0:
Nudge: `"📞 {today_actions} actions due today. Say '/glenigan-crm today' to see them."`

**6d. Pipeline healthy:**
Nudge: `"✅ {deals_total} active deals in pipeline. Say '/glenigan-crm' for full view."`

## Value Formatting

```python
def format_value(v):
    if v >= 1_000_000:
        return f"£{v/1_000_000:.1f}M"
    elif v >= 1_000:
        return f"£{v/1_000:.0f}K"
    else:
        return f"£{v:.0f}"
```

## Output Format

The nudge is always a single line, rendered as a blockquote at the very end of the response:

```
> ⚡ 296 projects unclassified. Next: Classify 45 WEST MIDLANDS projects (£12.3M). Say "classify West Midlands projects" to start.
```

## Integration Points

This nudge MUST appear at the end of:
1. Every `/glenigan-pipeline` response
2. Every `ingest-pdf` completion message
3. Every `deduplicate` completion message
4. Every `enrich-project` pass completion
5. Every `/glenigan-crm` response
6. Direct calls: "what should I do next", "nudge", "next action", "pipeline status"

The nudge query is lightweight (< 50ms) and should never be skipped.
