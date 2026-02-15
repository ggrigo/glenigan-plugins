---
description: Manage the built-in CRM pipeline for Glenigan leads
allowed-tools: Bash, Read, Write
argument-hint: "<action: pipeline | today | overdue | log | move | deal>"
---

Built-in CRM for Glenigan leads. No Monday.com needed. All data lives in `glenigan.db`.

## Usage Patterns

- `/glenigan-crm` or `/glenigan-crm pipeline` → Show active deals by temperature
- `/glenigan-crm today` → Today's follow-ups
- `/glenigan-crm overdue` → Overdue actions
- `/glenigan-crm deal {project_id}` → Full deal view (project + enrichments + activities + notes)
- `/glenigan-crm log {project_id} {type}` → Log an activity (call, email, linkedin, meeting, note)
- `/glenigan-crm move {project_id} {stage}` → Move deal to new stage
- `/glenigan-crm add {project_id}` → Create deal from qualified project
- `/glenigan-crm stats` → CRM stats (deals by stage, temperature, activity volume)

## Queries

Use Python with `sqlite3`. Use the views `v_crm_pipeline`, `v_crm_overdue`, `v_crm_today`.

### Pipeline View

```sql
SELECT * FROM v_crm_pipeline WHERE stage NOT IN ('won', 'lost', 'parked');
```

### Today's Actions

```sql
SELECT * FROM v_crm_today;
```

### Overdue

```sql
SELECT * FROM v_crm_overdue;
```

### Log an Activity

```python
from datetime import datetime
now = datetime.utcnow().isoformat() + 'Z'

c.execute("""
    INSERT INTO crm_activities
    (project_id, activity_type, direction, contact_name, contact_role,
     channel, summary, outcome, follow_up, follow_up_date, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (project_id, activity_type, direction, contact_name, contact_role,
      channel, summary, outcome, follow_up, follow_up_date, now))

# Update deal's next_action if follow_up provided
if follow_up:
    c.execute("""
        UPDATE crm_deals SET
            next_action = ?,
            next_action_date = ?,
            updated_at = ?
        WHERE project_id = ?
    """, (follow_up, follow_up_date, now, project_id))
```

### Move Deal Stage

```python
# Valid transitions:
# new_lead → contacted → meeting → proposal → negotiation → won
#                                                            → lost
#         → parked (from any stage)

c.execute("""
    UPDATE crm_deals SET
        stage = ?,
        updated_at = ?,
        won_date = CASE WHEN ? = 'won' THEN ? ELSE won_date END,
        lost_reason = CASE WHEN ? = 'lost' THEN ? ELSE lost_reason END
    WHERE project_id = ?
""", (new_stage, now,
      new_stage, now,
      new_stage, lost_reason,
      project_id))
```

### Create Deal from Qualified Project

```python
c.execute("""
    INSERT OR IGNORE INTO crm_deals
    (project_id, stage, temperature, deal_value, created_at, updated_at)
    VALUES (?, 'new_lead', 'warm', ?, ?, ?)
""", (project_id, project_value, now, now))
```

### Bulk Create Deals

For all qualified projects not yet in CRM:

```python
c.execute("""
    INSERT OR IGNORE INTO crm_deals (project_id, stage, temperature, deal_value, created_at, updated_at)
    SELECT
        ec.project_id, 'new_lead', 'warm', p.value_numeric, ?, ?
    FROM enrichment_classification ec
    JOIN projects p ON ec.project_id = p.project_id
    WHERE ec.status = 'QUALIFIED'
      AND ec.project_id NOT IN (SELECT project_id FROM crm_deals)
""", (now, now))
```

## Output Format

### Pipeline View

```
# CRM Pipeline — {date}
{total_active} active deals | {hot} hot | {warm} warm | {cold} cold

## Hot Deals
| Project | Title | Town | Value | Stage | Next Action | Due |
...

## Warm Deals
...

## Overdue ({count})
| Project | Title | Next Action | Due | Days Overdue |
...
```

### Deal Detail

```
# Deal: {title} ({project_id})
Stage: {stage} | Temp: {temperature} | Value: £{value}
Next: {next_action} — {next_action_date}

## Project Info
Town: {town} | Region: {region} | Planning: {planning_stage}
Authority: {planning_authority} | Ref: {planning_ref}

## Enrichment
Classification: {status} ({vertical}) | Portal: {portal_status}

## Activities ({count})
{date} | {type} | {summary} | Outcome: {outcome}
...

## Notes
{date} | {note}
...
```

## Nudge Integration

After every CRM interaction, append the pipeline nudge from `references/nudge.md`. If all enrichment is done, the nudge shifts to CRM actions:

> "3 overdue follow-ups. Next: Call Jamie Endres at Alanto Ltd for project 26065152 (£3.9M). Say 'log call for 26065152' after."
