# Glenigan Pipeline Schema Reference v0.3.0

## Three-Tier Architecture

### Core Layer (Immutable)
Data extracted from PDF. Written once, never modified. If a newer PDF contains the same project_id, the project is skipped (not overwritten) unless the user explicitly requests a re-import.

### Enrichment Layer (Progressive)
Each enrichment table is keyed by project_id. All enrichment rows are nullable and independent. Every enrichment carries `enriched_at` (ISO 8601 timestamp) and `enriched_by` (skill name) for audit trail.

### Operational Layer (Workflow)
Processing log, CRM sync state, and team annotations. These track what happened, not what the project is.

---

## Core Tables

### projects
The central table. One row per Glenigan project.

| Column | Type | Required | Source | Notes |
|--------|------|----------|--------|-------|
| project_id | TEXT PK | Yes | Index + Detail | 7-8 digit Glenigan ID |
| source_pdf | TEXT | Yes | Filename | e.g. "Glenigan_Projects_20260212_v2.pdf" |
| imported_at | TEXT | Yes | System | ISO 8601 |
| is_new | INTEGER | Yes | Header | 1=NEW, 0=UPDATED |
| updated_date | TEXT | No | Header | "UPDATED - dd/mm/yyyy" parsed to ISO |
| title | TEXT | Yes | Header | e.g. "Light Industrial/Warehouse" |
| scheme_description | TEXT | No | Detail | Full paragraph |
| additional_text | TEXT | No | Detail | Optional block |
| latest_info_date | TEXT | No | Detail | ISO date |
| latest_info_text | TEXT | No | Detail | Free text, often contains PP- reference |
| address_line | TEXT | No | Header | Street address |
| address_full | TEXT | No | Detail | Full with postcode |
| town | TEXT | No | Index/Header | Town/city name |
| region | TEXT | No | Index | e.g. "WEST MIDLANDS" |
| postcode | TEXT | No | Extracted | Regex from address_full |
| value_text | TEXT | Yes | Detail | Original "£3,900,000" |
| value_numeric | REAL | Yes | Parsed | 3900000.0 |
| funding_type | TEXT | No | Detail | "Private" or "Public" |
| value_basis | TEXT | No | Detail | "Calculated" or "Guideline" |
| start_date | TEXT | No | Detail | ISO date |
| end_date | TEXT | No | Detail | ISO date |
| contract_period | TEXT | No | Detail | "24 Months" |
| dates_basis | TEXT | No | Detail | "Calculated" or "Guideline" |
| project_status | TEXT | No | Detail | "In Progress" etc. |
| planning_stage | TEXT | No | Detail | "Pre-Planning", "Detailed Plans Submitted" |
| contact_stage | TEXT | No | Detail | "Pre-Tender", "Contract Awarded" |
| development_type | TEXT | No | Detail | "Refurbishment", "New Build" |
| floor_area | TEXT | No | Detail | Preserve "Not Available" |
| units | TEXT | No | Detail | Preserve "Not Available" |
| storeys | TEXT | No | Detail | Preserve "Not Available" |
| site_number | TEXT | No | Detail | Preserve "Not Available" |
| planning_authority | TEXT | No | Detail | e.g. "Oxford" |
| planning_ref | TEXT | No | Detail | e.g. "25/00798/SCREEN" from parentheses |
| pp_reference | TEXT | No | Extracted | "PP-14683772" from latest_info_text |

### sectors
One-to-many from projects. Multiple sectors per project.

| Column | Type | Notes |
|--------|------|-------|
| project_id | TEXT FK | References projects |
| sector_name | TEXT | e.g. "Warehousing/Storage" |
| is_primary | INTEGER | 1 if marked "(Primary)" |

### materials
One-to-many from projects. Category: items pairs.

| Column | Type | Notes |
|--------|------|-------|
| project_id | TEXT FK | References projects |
| category | TEXT | e.g. "Doors", "Fittings" |
| items | TEXT | e.g. "Industrial Doors (Unspecified)" |

### project_roles
One-to-many from projects. Each role block in the PDF.

| Column | Type | Notes |
|--------|------|-------|
| project_id | TEXT FK | References projects |
| role_type | TEXT | e.g. "Client / Promoter", "Architect / Plans By" |
| company_name | TEXT | e.g. "Alanto Ltd (TA Ramfoam)" |
| company_address | TEXT | Full address |
| phone | TEXT | May be "Not Available" |
| email | TEXT | May be "Removed to comply with Data Protection" |
| website | TEXT | URL if present |

### contacts
One-to-many from project_roles. Individual people.

| Column | Type | Notes |
|--------|------|-------|
| role_id | INTEGER FK | References project_roles |
| project_id | TEXT FK | References projects |
| name | TEXT | e.g. "Jamie Endres" |
| position | TEXT | e.g. "Director", "Not Available" |
| email | TEXT | Individual email |
| phone | TEXT | Direct phone |
| mobile | TEXT | Mobile number |

---

## Enrichment Tables

All enrichment tables follow the same pattern: project_id as PK + FK, data columns, enriched_at, enriched_by.

### enrichment_classification
Baresquare vertical fit assessment.

| Value | Meaning |
|-------|---------|
| QUALIFIED | Strong fit for Baresquare services |
| MAYBE | Possible fit, needs investigation |
| REJECTED | Not suitable |
| STRONG vertical | Healthcare, Industrial, Leisure, Public Sector |
| GOOD vertical | Commercial, Education, Retail |
| EXCLUDED vertical | Street lighting, Domestic/Housing, Historic |

### enrichment_portal
Planning portal intelligence.

| Value | Meaning |
|-------|---------|
| CRAWLABLE | Has keyval — portal access confirmed |
| PORTAL_MAINTENANCE | Portal errored/blocked, retry later |
| UNMAPPABLE | No keyval obtainable — no ref, non-Idox, or search returned nothing |

The keyval determines status: has keyval = CRAWLABLE, no keyval = not crawlable.

### enrichment_web
Web research results.

### enrichment_contacts
Contact quality assessment and LinkedIn discovery.

### enrichment_scoring
Priority scoring with factor breakdown.

### doc_enrichment
Post-extraction document signal data. Populated by batch-extract + document analysis runs.

| Column | Type | Notes |
|--------|------|-------|
| authority | TEXT | Planning authority name |
| planning_ref | TEXT | Council reference |
| project_id | TEXT FK | References projects (NULL if ref didn't match) |
| keyval | TEXT | Idox keyVal extracted |
| status | TEXT | "ok" or error description |
| error | TEXT | Error detail if status != "ok" |
| title | TEXT | Application title from portal |
| total_documents | INTEGER | Count of indexed documents |
| signal_decision | INTEGER | 1 if decision notice found |
| signal_lighting | INTEGER | 1 if lighting docs found |
| signal_energy | INTEGER | 1 if energy/sustainability docs found |
| signal_das | INTEGER | 1 if design & access statement found |
| signal_officer | INTEGER | 1 if officer/committee report found |
| high_docs | TEXT | JSON array of high-priority document names |

---

## PDF Structure Reference

A typical Glenigan multi-project PDF has:
- **Page 1**: Cover page with delivery date, requestor
- **Pages 2-3**: Index table grouped by REGION with columns: ID, Town, Description, Stage, Value
- **Pages 4+**: One detail page per project

The index provides: project_id, region, town, title, contact_stage, value_text.
The detail page provides: everything else.

Index entries have a flag character after the ID: "N" = NEW, "U" = UPDATED.

Planning references appear in two places:
1. In the Planning Authority field as parenthetical: `Oxford (25/00798/SCREEN)`
2. In the Latest Information text as: `reference PP-14683772`

Both should be extracted. They are different references (council vs national portal).
