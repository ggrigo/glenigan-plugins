---
name: gleni-ingest
description: >
  This skill should be used when the user uploads a Glenigan PDF export,
  asks to "import Glenigan projects", "ingest PDF", "load projects",
  "process Glenigan export", or drops a multi-project Glenigan PDF.
  Extracts all projects with strict accuracy validation and writes to SQLite.
  Triggered by /gleni-ingest command.
---

# Ingest Glenigan PDF

Extract projects from a Glenigan multi-project PDF export into the SQLite database. Accuracy is paramount: fail the entire batch if extraction quality drops below 95%.

## Prerequisites — Auto-Init Guard

Before doing anything else, check if `glenigan.db` exists in the workspace folder:

```python
import os
db_path = os.path.join(workspace_folder, 'glenigan.db')
if not os.path.exists(db_path):
    # Database doesn't exist — run /gleni-init automatically
    pass  # Trigger the gleni-init command
```

If the database is missing, **do not ask the user** — run `/gleni-init` automatically, then proceed with ingestion. The user should never need to think about init vs ingest as separate steps.

## Extraction Strategy

Use `pdfplumber` (install via pip if needed) to extract text from every page. The PDF has a predictable structure:

1. **Page 1**: Cover page. Skip. Extract `source_pdf` name and delivery date.
2. **Pages 2-N**: Index table. Parse for project_id, region, town, title, stage, value, new/updated flag.
3. **Remaining pages**: Detail pages, one per project. Parse each for full project data.

### Step 1: Parse the Index

The index is grouped by REGION headers (all caps, e.g. "WEST MIDLANDS", "LONDON"). Under each region, rows follow the pattern:

```
ID 26065152 U Dudley Light Industrial/Warehouse Pre-Tender £3,900,000
```

Extract:
- `project_id`: The 8-digit number after "ID"
- `is_new`: "N" = 1, "U" = 0 (the letter after the ID)
- `town`: First word(s) after the flag
- `title`: Description text (everything between town and stage)
- `contact_stage`: "Pre-Tender" or "Contract Awarded"
- `value_text`: The £-prefixed amount
- `region`: The current region header

Build a dictionary keyed by project_id with these index fields.

### Step 2: Parse Detail Pages

Each detail page starts with "Back to Index" and contains structured sections. Parse each page to extract:

**Header block:**
- Title + NEW/UPDATED flag + date
- Address line (first line under title)
- Full address with postcode
- Value + funding type + value basis

**Dates block:**
- Start Date, End Date, Contract Period
- Whether dates are "Calculated" or "Guideline"

**Stages block (two PDF layouts exist — handle both):**
- Layout A (53%): `S In Progress P Pre-Planning C Pre-Tender` — S/P/C markers inline with values. Split on the single-letter markers.
- Layout B (47%): `S P C` on one line, then `In Progress Detailed Plans Submitted Pre-Tender` on the next. Match against known stage values working backwards (contact stage from end, then planning stage, then project status).
- Extract: Project Status, Planning Stage, Contact Stage as separate clean values.

**Project Summary block:**
- Development Type, Floor Area, Planning Authority (with planning ref in parentheses), Units, Site Number, Storeys

**Sectors block:**
- List of sector names, identify which has "(Primary)"

**Latest Information block:**
- Date in parentheses + free text
- Extract PP-reference if present (regex: `PP-\d{7,8}`)

**Scheme Description block:**
- Everything between "Scheme Description" header and next section

**Additional Text block (optional):**
- If present, capture

**Materials block:**
- Category: items pairs, one per line

**Project Roles block:**
- Parse role blocks. Each starts with a role label like "Client / Promoter" or "Architect / Plans By"
- Extract: company name, address, phone (TEL:), email (EMAIL:), website (WEB:)
- Under each role/company, parse contact rows: Name, Position, Email, Tel, Mobile

### Step 3: Merge Index + Detail

Match detail pages to index entries by project_id. The index provides region (which detail pages don't have). The detail page provides everything else.

### Step 4: Validate

For each project, validate:
- `project_id` matches pattern `^\d{7,8}$`
- `value_text` is parseable as currency
- `title` is at least 10 characters
- `value_numeric` > 0

Count valid vs total. If valid/total < 0.95, **abort the entire import** and report which projects failed validation and why.

### Step 5: Write to SQLite (with Dedup Prevention)

For each valid project, check for duplicates BEFORE inserting. The dedup check catches cases where the same physical project appears with a different Glenigan ID across two PDF exports (different region, different date).

Run three lookups in order (stop at first match):

1. **Exact ref:** Same `planning_ref` + `planning_authority` (with `merged_into IS NULL`)
2. **Same address:** Normalized `address_full` matches an existing row
3. **Fuzzy match:** Same `title` + `town` + `value_numeric` within 20%

```python
def check_duplicate(cursor, project):
    """Returns (is_dupe, existing_id, reason) tuple."""

    # Check 1: Exact planning ref
    ref = project.get('planning_ref', '')
    if ref and ref != 'N/A' and ref.strip():
        existing = cursor.execute("""
            SELECT project_id FROM projects
            WHERE planning_ref = ? AND planning_authority = ?
              AND merged_into IS NULL
        """, (ref, project.get('planning_authority', ''))).fetchone()
        if existing:
            return (True, existing[0], 'exact_ref')

    # Check 2: Same address (normalized)
    addr = project.get('address_full', '')
    if addr and addr.strip():
        import re
        norm = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', addr.lower())).strip()
        candidates = cursor.execute("""
            SELECT project_id, address_full FROM projects
            WHERE address_full IS NOT NULL AND address_full != ''
              AND merged_into IS NULL
        """).fetchall()
        for cand_id, cand_addr in candidates:
            cand_norm = re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', cand_addr.lower())).strip()
            if cand_norm == norm:
                return (True, cand_id, 'same_address')

    # Check 3: Same title + town + similar value
    title = project.get('title', '')
    town = project.get('town', '')
    if title and town:
        candidates = cursor.execute("""
            SELECT project_id, value_numeric FROM projects
            WHERE title = ? AND town = ? AND merged_into IS NULL
        """, (title, town)).fetchall()
        new_val = project.get('value_numeric', 0) or 0
        for cand_id, cand_val in candidates:
            cand_val = cand_val or 0
            if cand_val == 0 and new_val == 0:
                return (True, cand_id, 'fuzzy_title_town')
            if cand_val > 0 and new_val > 0:
                if abs(cand_val - new_val) < 0.2 * max(cand_val, new_val):
                    return (True, cand_id, 'fuzzy_title_town_value')

    return (False, None, None)
```

For each project:

1. Check if `project_id` already exists → skip (log "duplicate skipped")
2. Run `check_duplicate()` against the extracted fields
3. **If duplicate found:** UPDATE the existing record with newer data (dates, status, latest_info, latest_info_date, contact_stage, planning_stage, project_status). Don't INSERT. Log in `crm_notes`: "Updated from re-import: {source_pdf}".
4. **If no duplicate:** INSERT into `projects`, `sectors`, `materials`, `project_roles`, `contacts`. INSERT into `processing_log` with stage="imported".

### Step 6: Report

After import, report:
- Total projects found in PDF
- Successfully imported (new) count
- Updated (duplicate matched and refreshed) count
- Skipped (exact project_id match) count
- Failed validation count (with details)
- Breakdown by region
- Breakdown by contact_stage

## Accuracy Notes

Common extraction pitfalls to handle:
- Multi-line descriptions in the index (title wraps to next line with indentation)
- "Not Available" should be stored as-is, not as NULL (except for truly missing fields)
- Phone numbers may appear as "Removed to comply with Data Protection"
- Some projects span two PDF pages (long scheme descriptions or many roles)
- Planning ref format varies: "25/00798/SCREEN", "2025/06261/PA", "254840FUL", empty "()"
- The PP-reference in latest_info_text is a different identifier from the council planning_ref
- Value parsing: strip £ and commas, parse as float
- Date parsing: Glenigan uses "dd/mm/yyyy" format, convert to ISO "yyyy-mm-dd"

## Post-Ingestion Nudge

After reporting ingestion results, **always** append the enrichment nudge. Read references/nudge.md for the priority waterfall. The nudge will automatically suggest deduplication if this import overlaps with existing data (Priority 0.5), or classification if the data is clean (Priority 1). The user just imported data — momentum is high — follow the nudge.

## Schema Reference

Read `references/schema.md` for the complete table definitions and field descriptions before implementing extraction.
