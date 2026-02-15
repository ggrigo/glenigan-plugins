# Glenigan v2.6.1

---
description: View and query the Glenigan project pipeline
allowed-tools: Bash, Read
argument-hint: "<filter: all | qualified | region | stats>"
---

Query the Glenigan SQLite database and present pipeline status. The database is `glenigan.db` in the user's workspace folder.

## Usage Patterns

Respond to these kinds of requests:

- `/glenigan-pipeline` or `/glenigan-pipeline all` → Show summary stats + top projects
- `/glenigan-pipeline stats` → Database statistics and enrichment coverage
- `/glenigan-pipeline qualified` → Show only QUALIFIED projects, ranked by priority
- `/glenigan-pipeline region London` → Filter by region
- `/glenigan-pipeline search {term}` → Search projects by title, town, or description
- `/glenigan-pipeline project {id}` → Full detail view of a single project with all enrichments

## Queries

Use Python with `sqlite3` to query the database. Use the views `v_pipeline_summary` and `v_qualified_leads` when appropriate.

### Stats Query

```sql
-- Total projects
SELECT COUNT(*) FROM projects;

-- By region
SELECT region, COUNT(*), SUM(value_numeric) FROM projects GROUP BY region ORDER BY COUNT(*) DESC;

-- By planning stage
SELECT planning_stage, COUNT(*) FROM projects GROUP BY planning_stage;

-- By contact stage
SELECT contact_stage, COUNT(*) FROM projects GROUP BY contact_stage;

-- Enrichment coverage
SELECT
    (SELECT COUNT(*) FROM enrichment_classification) AS classified,
    (SELECT COUNT(*) FROM enrichment_portal) AS portal_checked,
    (SELECT COUNT(*) FROM enrichment_web) AS web_enriched,
    (SELECT COUNT(*) FROM enrichment_contacts) AS contacts_assessed,
    (SELECT COUNT(*) FROM enrichment_scoring) AS scored;

-- Portal registry
SELECT COUNT(*) FROM portal_registry;
```

### Pipeline View

```sql
SELECT * FROM v_pipeline_summary ORDER BY value_numeric DESC LIMIT 20;
```

### Qualified Leads

```sql
SELECT * FROM v_qualified_leads;
```

## Output Format

Present results as clean tables. For the summary view:

```
# Glenigan Pipeline: {date}
{total} projects | £{total_value} total value

## Enrichment Coverage
Classified: {n}/{total} | Portal: {n}/{total} | Web: {n}/{total} | Scored: {n}/{total}

## Top Projects by Value
| ID | Title | Town | Value | Stage | Classification |
...

## By Region
| Region | Count | Total Value |
...
```

For single project detail, show all core fields, all enrichments (if any), all contacts, all sectors, processing log, and any team annotations.

## Enrichment Nudge (ALWAYS append)

After every `/glenigan-pipeline` response, **always** append a nudge line using the nudge reference logic (see `references/nudge.md`). This is the async heartbeat — every interaction is a chance to push the pipeline forward.

Read `references/nudge.md` for the full priority waterfall and query logic. The nudge is a single blockquote line at the end:

```
> ⚡ 296 projects unclassified. Next: Classify 45 WEST MIDLANDS projects (£12.3M). Say "classify West Midlands projects" to start.
```

Never skip the nudge. It costs < 50ms and keeps momentum.
