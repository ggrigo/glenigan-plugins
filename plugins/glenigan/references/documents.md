# Document Intelligence Reference

All document download and analysis logic. Used by /gleni-loop for document steps.

## Safety Rules

- **Never bypass CAPTCHAs or bot detection**
- **Never submit login forms**
- **Respect robots.txt** — if a portal blocks automated access, mark it and move on
- **Rate limit**: wait 3-5 seconds between page loads on the same portal
- **One portal at a time** — don't open multiple portal sessions

## Download Flow

### Step 1: Navigate to Documents Tab

**Browser tool priority:** Use Playwright MCP as primary. Fall back to Chrome MCP if Playwright is unavailable or fails.

**For Idox portals with keyVal (direct access):**

Navigate directly using `playwright_navigate`:
```
URL: {portal_base}/online-applications/applicationDetails.do?activeTab=documents&keyVal={keyval}
```

No search needed. This is the fastest path.

**For Idox portals without keyVal (search required):**

Load the `idox-portal-intelligence` skill for the full extraction sequence:

1. `playwright_navigate` to `{portal_url}/search.do?action=advanced`
2. `playwright_get_visible_html` with `selector: "form"` to detect the field name
3. `playwright_fill` the detected field with the planning ref + `playwright_click` submit
4. `playwright_evaluate` to extract keyval from result links
5. Navigate to the documents tab using the extracted keyval

**Chrome MCP fallback** (if Playwright fails):
1. Use `find()` to locate the search input
2. Use `form_input()` to set the ref — **do NOT use `type()`, it doesn't stick in Idox fields**
3. Use `find()` for the Search button, click it
4. Wait 5s, navigate to Documents tab
5. Read keyVal from the tab URL (Chrome extension blocks it in JS)

**For non-Idox portals:**
- Navigate to portal URL via Playwright
- Search for the planning reference
- Find the documents section
- If structure is unfamiliar, take a screenshot and analyze

### Step 2: List Available Documents

On the documents page, read the document list. Typical Idox layout:

```
| Date | Description | Type | Size |
| 01/02/2025 | Design and Access Statement | Application | 2.4MB |
| 01/02/2025 | Site Location Plan | Application | 500KB |
| 15/03/2025 | Decision Notice | Decision | 150KB |
```

**Document priority is defined in the playbook. Read `config/playbook.md` for context, `config/rules.json` for execution.**

Baresquare works with clients (e.g. CILS) to qualify Glenigan leads. Each client tells us which documents matter for their business. The rules file (`config/rules.json`) contains `document_priorities` with HIGH/MEDIUM/LOW keyword lists.

```python
import json, os

config_path = os.path.join(plugin_dir, 'config', 'rules.json')
with open(config_path) as f:
    client = json.load(f)

high_kw = client['document_priorities']['HIGH']['keywords']
med_kw = client['document_priorities']['MEDIUM']['keywords']
low_kw = client['document_priorities']['LOW']['keywords']
default_unmatched = client['document_priorities'].get('default_unmatched', 'LOW')

def classify_doc(description, filename):
    combined = f"{description} {filename}".lower()
    if any(kw in combined for kw in high_kw):
        return 'HIGH'
    if any(kw in combined for kw in med_kw):
        return 'MEDIUM'
    if any(kw in combined for kw in low_kw):
        return 'LOW'
    # Fallback from rules.json default_unmatched (defaults to LOW if not set)
    return default_unmatched
```

**Default BizDev fallback** (always download regardless of playbook):
1. **Decision Notice** — confirms if project is live or dead
2. **Design and Access Statement** — project scope, end-use, tenant/occupier info
3. **Officer Report / Committee Report** — detailed assessment, decision-maker reasoning

**Always skip:**
- Neighbour notification letters
- Admin correspondence
- Duplicate/superseded versions
- Ownership certificates, fee calculations

### Step 2.5: Catalogue ALL Documents in DB

After classifying every document on the page, **INSERT all of them** into `downloaded_documents` — HIGH, MEDIUM, and LOW. The database is the complete inventory of what exists on the portal. Priority filtering happens at query time, not storage time.

```python
for doc in all_documents:
    priority = classify_doc(doc['description'], doc['filename'])
    c.execute("""
        INSERT OR IGNORE INTO downloaded_documents
        (project_id, document_type, filename, source_url, priority, catalogued_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (project_id, doc['type'], doc['filename'], doc['url'], priority, now))
```

This ensures every document visible on the portal is recorded, regardless of whether it will be downloaded. LOW-priority docs stay in the DB with `file_size = NULL` and `downloaded_at = NULL`, meaning "catalogued but not downloaded."

### Step 3: Download HIGH + MEDIUM Files

**Method waterfall (ranked by reliability):**

Try each method in order. Fall through on failure. Use whichever browser tool (Playwright or Chrome MCP) is available.

| # | Method | Success Rate | When to Use |
|---|--------|-------------|-------------|
| 1 | **Playwright click + download intercept** | ~95% | Default. `playwright_click` on the doc link, Playwright handles ViewDocument redirects and session cookies automatically. |
| 2 | **Playwright evaluate (fetch API)** | ~85% | Fallback when click doesn't trigger download. `playwright_evaluate` running `fetch(url, {credentials:'include'})` in page context to get blob. |
| 3 | **Chrome MCP click** | ~90% | If Playwright unavailable. Click doc link via Chrome MCP `find()` + `left_click`. |
| 4 | **JSZip batch download** | ~80% | Efficient for 5+ docs from same portal. Fetch all as blobs in-page via `playwright_evaluate`, zip them, return base64. |
| 5 | **Direct HTTP (requests)** | ~15% | Last resort. Almost always fails due to Cloudflare/session. Only try for direct PDF URLs (no ViewDocument redirect). |

**ViewDocument redirect pattern:** Most Idox doc links are `ViewDocument.pdf` URLs that 302-redirect to the actual PDF. Browser handles this natively. Direct HTTP usually fails here because it doesn't carry the session.

**Filename sanitization:**
```python
def sanitize_filename(filename, index):
    safe = filename.replace('/', '_').replace('\\', '_')
    if not safe.lower().endswith('.pdf'):
        safe += '.pdf'
    return f"{index+1:02d}_{safe[:100]}"
```

For each HIGH and MEDIUM document (already catalogued in Step 2.5):
1. Try Method 1 (click). If fails, try Method 2 (fetch). If fails, log and skip.
2. Save to: `{workspace}/documents/{project_id}/{sanitized_filename}`
3. **UPDATE** the existing DB record (not INSERT — the row already exists from cataloguing):

```python
c.execute("""
    UPDATE downloaded_documents
    SET downloaded_at = ?, file_size = ?, download_method = ?
    WHERE project_id = ? AND filename = ?
""", (now, size, method_used, project_id, filename))
```

### Step 4: Update Portal Registry

After each portal interaction, update connectivity:

```python
# Success
c.execute("""
    UPDATE portal_registry SET
        connectivity = 'connected',
        last_success = ?,
        success_count = success_count + 1
    WHERE authority_name = ?
""", (now, authority))

# Failure
c.execute("""
    UPDATE portal_registry SET
        last_attempt = ?,
        fail_count = fail_count + 1,
        last_error = ?
    WHERE authority_name = ?
""", (now, error_msg, authority))
```

## Analysis

### What It Extracts

For each downloaded PDF, extract:

| Field | Source Documents | Example |
|-------|-----------------|---------|
| Size (sqft/sqm) | Design & Access Statement, Planning Statement | "4,090 sqm GIA" |
| Development type | Design & Access Statement | "New Build", "Refurbishment", "Mixed" |
| Materials mentions | Any document | solar PV, LED, lighting controls, DALI, BMS |
| Energy targets | Sustainability Statement, D&A | BREEAM Excellent, EPC A, net-zero |
| Key contacts | Cover letters, Agent details | Names not in Glenigan data |
| M&E scope | D&A, MEP reports | "Full mechanical and electrical installation" |
| Lighting specification | Any document | "500 lux minimum", "emergency lighting throughout" |

### Processing Flow

**Step 1: Select Targets**

```python
targets = c.execute("""
    SELECT dd.project_id, dd.filename, dd.document_type, dd.priority,
           p.title, p.value_numeric
    FROM downloaded_documents dd
    JOIN projects p ON dd.project_id = p.project_id
    WHERE dd.content_summary IS NULL
      AND dd.downloaded_at IS NOT NULL
    ORDER BY
        CASE dd.priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
        p.value_numeric DESC
""").fetchall()
```

Note: `downloaded_at IS NOT NULL` ensures we only analyze documents that were actually downloaded (HIGH + MEDIUM), not catalogued-only LOW records.

**Step 2: Read and Analyze Each Document**

Use pdfplumber (install via pip if needed) to extract text:

```python
import pdfplumber

with pdfplumber.open(pdf_path) as pdf:
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
```

For each document, scan for:

**Size indicators:**
```python
import re
size_patterns = [
    r'(\d[\d,]*)\s*(?:sq\s*m|sqm|m²|square\s*metres?)',
    r'(\d[\d,]*)\s*(?:sq\s*ft|sqft|ft²|square\s*feet)',
    r'GIA\s*(?:of\s*)?(\d[\d,]*)',
    r'NIA\s*(?:of\s*)?(\d[\d,]*)',
    r'(\d[\d,]*)\s*(?:GIA|NIA|GEA)',
]
```

**Energy/sustainability keywords:**
```python
energy_keywords = {
    'solar_pv': ['solar pv', 'photovoltaic', 'solar panel', 'solar array'],
    'led': ['led lighting', 'led luminaire', 'led fixture', 'led retrofit'],
    'lighting_controls': ['dali', 'lighting control', 'daylight sensor', 'occupancy sensor', 'pir sensor', 'bms integration'],
    'breeam': ['breeam', 'breeam excellent', 'breeam very good', 'breeam outstanding'],
    'net_zero': ['net zero', 'net-zero', 'zero carbon', 'carbon neutral'],
    'heat_pump': ['heat pump', 'ashp', 'gshp', 'air source'],
    'epc': ['epc rating', 'epc a', 'epc b', 'energy performance'],
}
```

**Lighting scope indicators:**
```python
lighting_keywords = [
    'lux', 'luminaire', 'lighting design', 'lighting scheme',
    'emergency lighting', 'external lighting', 'floodlight',
    'lighting installation', 'lighting specification',
]
```

**Step 3: Generate Summary**

For each document, write a concise summary (max 200 words) of relevant findings. Store in `downloaded_documents.content_summary`.

```python
c.execute("""
    UPDATE downloaded_documents
    SET content_summary = ?
    WHERE id = ?
""", (summary, doc_id))
```

**Step 4: Update Enrichment**

If analysis reveals significant new intelligence (explicit lighting scope, energy targets, larger size than Glenigan indicated), update `enrichment_web` or add a `crm_note`:

```python
# If lighting/energy scope found, note it
if found_lighting or found_energy:
    c.execute("""
        INSERT INTO crm_notes (project_id, note, created_at)
        VALUES (?, ?, ?)
    """, (project_id, f"DOCUMENT ANALYSIS: {key_findings}", now))
```

## Batch Behavior

User can say:
- "download documents for project 26065152" — single project
- "download documents for Oxford projects" — all CRAWLABLE Oxford projects
- "download documents" — next 5 highest-value CRAWLABLE projects

Always show the user what you plan to download before starting:

```
Found 3 CRAWLABLE projects for Oxford:
1. 26065152 — Light Industrial/Warehouse (£3.9M) — 8 documents available
2. 26070881 — Office Refurbishment (£1.2M) — 5 documents available
3. 26072345 — Retail Unit (£800K) — 3 documents available

Download priority documents from all 3? (y/n)
```

## Error Handling

| Error | Action |
|-------|--------|
| 403 Forbidden | Mark portal as 'failed', log error, skip |
| CAPTCHA detected | Mark as 'partial', note CAPTCHA, skip |
| No documents tab | Screenshot page, try alternate URL patterns |
| Document link 404 | Log, continue to next document |
| Timeout | Retry once after 10s, then skip |
| Portal redesigned | Screenshot, mark 'failed' with note |

## Document Retrieval Prerequisites

- `glenigan.db` must exist with projects that have `enrichment_portal` rows (Pass 2 complete)
- Projects need either a `keyVal` (Idox direct access) or `verified_ref` + `portal_url`
- Portal must have `connectivity` = 'connected' or 'partial' in portal_registry

### Select Target

```python
# Find projects with portal data and no catalogued documents yet
targets = c.execute("""
    SELECT p.project_id, p.title, p.planning_authority, p.planning_ref,
           ep.portal_url, ep.portal_type, ep.keyval, ep.portal_status,
           pr.csrf_required
    FROM projects p
    JOIN enrichment_portal ep ON p.project_id = ep.project_id
    JOIN portal_registry pr ON p.planning_authority = pr.authority_name
    WHERE ep.portal_status = 'CRAWLABLE'
      AND p.project_id NOT IN (
          SELECT DISTINCT project_id FROM downloaded_documents
      )
    ORDER BY p.value_numeric DESC
    LIMIT 5
""").fetchall()
```

Note: This checks projects with zero rows in `downloaded_documents`. Once Step 2.5 catalogues all documents for a project, that project won't appear here again — even if some documents haven't been downloaded yet.

## Schema

The `downloaded_documents` table is defined in `/glenigan-init`. Key columns:

| Column | Set at | Meaning |
|--------|--------|---------|
| `priority` | Catalogue (Step 2.5) | HIGH/MEDIUM/LOW from playbook |
| `catalogued_at` | Catalogue (Step 2.5) | When the document was first seen on the portal |
| `downloaded_at` | Download (Step 3) | When the file was actually downloaded. NULL = catalogued only |
| `file_size` | Download (Step 3) | Size of downloaded file. NULL = not downloaded |
| `download_method` | Download (Step 3) | Which waterfall method succeeded |
| `content_summary` | Analysis | Extracted intelligence from the document |
| `original_name` | Download (Step 3) | Filename before sanitization |

A row with `downloaded_at IS NULL` means the document exists on the portal and has been classified, but was not downloaded (typically LOW priority). This is normal and expected.
