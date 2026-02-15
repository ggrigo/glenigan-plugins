# Subagent Prompt Templates

All prompts used by pipeline skills that spawn subagents via the Task tool. Fill in `{placeholders}` with actual project data before passing to a subagent.

## Classification Prompt (5-Criteria)

Used by `classify-opportunities` Method B. One subagent per project. Use `model: "haiku"`.

```
You are evaluating a construction project for {company_name} ({company_description}).

{company_name} specializes in:
{services_list}

## Strong Verticals (Tier 1) - High priority:
{tier1_verticals}

## Good Verticals (Tier 2) - Worth pursuing:
{tier2_verticals}

## Excluded - Do not qualify:
{excluded_verticals}

---

Evaluate this project against 5 criteria:

1. **SCALE FIT**: Is this building-wide or facility-wide?
   - PASS: New builds, major refurbishments, facility upgrades
   - FAIL: Shopfronts, single rooms, small fit-outs, minor works
   - Auto-FAIL patterns: "Relocation of entrance", "Shopfront alterations", "Fascia replacement", "Signage installation", "Single room refurb", "Door replacement"

2. **LIGHTING RELEVANCE**: Would lighting/energy be a meaningful component?
   - PASS: Projects where lighting design/installation is significant
   - FAIL: Pure structural work, landscaping only, no interior/exterior lighting
   - If project value <£250k, require EXPLICIT lighting/energy scope to pass

3. **SECTOR FIT**: Does it match target verticals?
   - PASS: Tier 1 or Tier 2 sectors
   - FAIL: Excluded sectors (street lighting, residential, domestic, housing)
   - FAIL: External sports pitch lighting (golf, tennis, cricket, athletics) unless indoor sports hall or part of larger building

4. **COMMERCIAL VIABILITY**: Is it large enough?
   - PASS: £200k+ value OR 100+ estimated fixtures OR 1000+ sqm
   - MAYBE: £100k-200k value or smaller but promising
   - FAIL: Under £100k, very small scope

5. **TIMING**: Are decisions still open?
   - PASS: Pre-tender, tender, early construction
   - MAYBE: On site but lighting not yet installed
   - FAIL: Completed, maintenance-only
   - WARNING: If starting within 3 months AND no explicit lighting scope, flag as risky

---

## Project Data:
- **Project ID:** {project_id}
- **Description:** {description}
- **Value:** £{value}
- **Town:** {town}
- **Stage:** {stage}
- **Start Date:** {start_date}
- **Sectors:** {sectors}
- **Scheme Description:** {scheme_description}

---

Respond with valid JSON only:
{{
  "status": "QUALIFIED" | "MAYBE" | "REJECTED",
  "scale_fit": true | false,
  "lighting_relevance": true | false,
  "sector_fit": true | false,
  "commercial_viability": true | false,
  "timing_appropriate": true | false,
  "reasoning": "1-2 sentence explanation"
}}
```

### Lightweight Classification Variant

For speed with 15+ projects in parallel:

```
Classify this construction project for {company_name} ({company_description}).

PROJECT: ID {project_id} - {description} - £{value}
TOWN: {town}
STAGE: {stage}
SECTORS: {sectors}
SCHEME: {scheme_description}

{company_name} targets: {services_summary}
Strong verticals: {tier1_list}
Good verticals: {tier2_list}
Excluded: {excluded_list}

RESPOND with exactly:
STATUS: QUALIFIED or MAYBE or REJECTED
REASONING: One sentence
```

---

## Enrichment Prompt

Used by `enrich-project` Pass 3. One subagent per QUALIFIED project. Use `model: "haiku"`.

```
You are enriching a construction project lead for {company_name} ({company_description}).

## Project Data:
- **Project ID:** {project_id}
- **Description:** {description}
- **Value:** £{value}
- **Town:** {town}
- **Planning Reference:** {planning_ref}
- **Planning Authority:** {planning_authority}
- **Scheme Description:** {scheme_description}

## Your Task:

1. **Web Search** - Try these searches in order (stop when you find substantive results):
   - Planning reference: "{planning_ref}" + authority name
   - Project description: "{description}" + "{town}" + planning
   - Company/client: search for the client company + project location
   - News: "{town}" + key terms from scheme description

2. **Write a 400-word summary** covering:
   - What's being built (hospital wing, warehouse, leisure centre, etc.)
   - Scale/size if mentioned (sqm, floors, beds, units)
   - Who's involved beyond the PDF data (contractor, PM, other consultants)
   - Timeline/phasing
   - Any M&E, lighting, sustainability, energy references

3. **Second Pass Classification** - Based on enriched information:
   - CONFIRMED - Initial classification still appropriate
   - UPGRADED - Project is MORE suitable than initially thought
   - DOWNGRADED - Project is LESS suitable

CRITICAL: Never fabricate contact names, emails, phone numbers, or technical specs. If data is not found, say "NOT FOUND".

## Output Format:

### SUMMARY:
[Your 400-word summary]

### SECOND_PASS: [CONFIRMED/UPGRADED/DOWNGRADED]
[One sentence explaining why]

### SOURCES:
[List URLs found]
```

---

## Contact Profile Prompt

Used by `profile-contacts` Part A. One subagent per PROJECT (not per contact). Use `model: "haiku"`.

```
You are profiling contacts for {company_name} sales outreach on a construction project.

## Project:
- **Title:** {project_title}
- **Value:** £{value}
- **Town:** {town}

## Known Roles from Database:
{roles_block}

(Each role lists: role_type, company_name, contact_name, position, email, phone, website)

## Your Task:

For EACH company in the roles list, complete these FOUR mandatory lookups. Do NOT skip any.

### Mandatory Step 1 — WebSearch
Search "[company name] contact phone email" and "[company name] directors". WebSearch returns rich snippets with phone numbers, emails, website URLs, LinkedIn profiles directly in results. Extract everything visible in search results. This single step often provides 80% of what's needed.

### Mandatory Step 2 — Companies House
Search "[company name] Companies House" or go to find-and-update.company-information.service.gov.uk. Extract:
- Company number
- Registered office address
- Directors (full names + appointment dates)
- SIC codes
- Active/dissolved status

### Mandatory Step 3 — Company Website
Visit the website found in Step 1. Look for:
- Contact page: phone numbers, email addresses
- Team/About page: named individuals with titles
- Office addresses
Extract any direct emails (firstname.lastname@) and direct phone numbers.

### Mandatory Step 4 — LinkedIn
Search "[company name] LinkedIn" or "[director name] LinkedIn". Find key individuals:
- MD/CEO, directors, project managers
- Extract profile URLs for named individuals
Do NOT fabricate profiles — only report what you actually find.

### After completing all three lookups per company:

1. **Assess Contact Quality:**
   - Email: HIGH (personal firstname.lastname@) / MEDIUM (generic info@) / LOW (none)
   - Phone: HIGH (mobile/direct 07xxx) / MEDIUM (switchboard) / LOW (none)

2. **Recommend Action per role:**
   - PHONE: If high-quality phone available
   - EMAIL: If personal email available
   - LINKEDIN: If no direct contact but LinkedIn found
   - RESEARCH_NEEDED: If insufficient contact info

CRITICAL: Never fabricate contact details. Only report what you actually find. Mark anything not found as "NOT FOUND".

## Output Format (repeat for EACH role):

### ROLE: [role_type] — [company_name]
- Contact: [name, position]
- Email: [email] (HIGH/MEDIUM/LOW)
- Phone: [phone] (HIGH/MEDIUM/LOW)
- LinkedIn: [URL or "NOT FOUND"]
- Website: [URL]
- Recommended Action: [PHONE/EMAIL/LINKEDIN/RESEARCH_NEEDED]
- Notes: [recent projects, decision-making role, any other findings]

### BEST_OUTREACH_PATH:
[Which role/contact to approach first and why, based on priority hierarchy:
1. Client/Promoter (budget holder), 2. Architect (specifier), 3. M&E/Energy (partner), 4. Contractor]
```

---

## Stakeholder Discovery Prompt

Used by `profile-contacts` Part B. One subagent per project. Use `model: "sonnet"`.

```
You are building a stakeholder map for a UK construction project. {company_name} ({company_description}) wants to identify everyone involved in this project to find the best outreach path for their LED lighting and solar PV solutions.

## Project Data:
- **Project ID:** {project_id}
- **Title:** {project_title}
- **Value:** £{value}
- **Town:** {town}
- **Address:** {address}
- **Planning Ref:** {planning_ref}
- **Planning Authority:** {planning_authority}
- **Known roles from database:** {known_roles_summary}
- **Research summary (if available):** {research_summary}

## Your Task:

Use THREE research layers. Complete ALL of them — do NOT stop early.

### Layer 1: Mandatory Per-Company Lookups (ALWAYS DO THIS)

For EVERY company mentioned in the known roles, run these four lookups:

**1a. WebSearch** — Search "[company name] contact phone email" and "[company name] directors". WebSearch returns rich snippets with phone numbers, emails, website URLs, LinkedIn profiles directly. Extract everything visible. This often provides 80% of what's needed in one query.

**1b. Companies House** — Search "[company name] Companies House" or go to find-and-update.company-information.service.gov.uk. Extract: company number, registered office, directors (names + appointment dates), SIC codes, active/dissolved status.

**1c. Company Website** — Visit the website found in 1a. Extract: contact page (phone, email), team/about page (named individuals with titles), office addresses. Look for direct emails (firstname.lastname@) and direct phone numbers.

**1d. LinkedIn** — Search "[company name] LinkedIn" or "[director name] LinkedIn". Find key individuals (MD/CEO, directors, project managers). Extract profile URLs. Do NOT fabricate.

### Layer 2: Google AI Mode (wider discovery)

Navigate to google.com and use AI mode for synthesized queries that go BEYOND the known roles:

1. "Who owns {address}?" — surfaces property owner, landlord, REIT
2. "Who is developing {address} {town}?" — surfaces developer, promoter
3. "{project_title} {town} architect contractor" — surfaces project team
4. "[applicant company] development projects" — surfaces company profile, key people
5. "{address} planning application {planning_ref}" — surfaces parties, decision, context

If AI mode is unavailable or results are thin, fall back to standard Google keyword searches.

Any NEW companies discovered via AI mode → run Layer 1 lookups on them too.

### Layer 3: Planning Portal Intelligence

If a planning ref is available, navigate to the council portal via browser and extract:
- Applicant name (from application form)
- Agent name (from application form)
- Parties consulted (from officer report)
- Decision details

### Supplementary Sources (fill remaining gaps)

**Property press:** Estates Gazette, CoStar, Property Week, React News
**Trade press:** Construction Enquirer, Building, PBC Today, local news

**LinkedIn:**
- Search for key companies found + relevant job titles (development director, project manager, head of estates)
- Report ONLY profiles you actually find. Never fabricate.

**Contractor & Tender Intelligence:**
- Contract award notices, sub-contractor opportunities.

## Output Format:

STAKEHOLDER MAP:

OWNER/LANDLORD:
- Company: [name]
- Named contacts: [name, title — SOURCE: url]
- Type: REIT / developer / local authority / private / NOT FOUND

DEVELOPER/PROMOTER:
- Company: [name]
- Named contacts: [name, title — SOURCE: url]
- LinkedIn: [url or NOT FOUND]

ARCHITECT:
- Company: [name]
- Named contacts: [name, title — SOURCE: url]
- Website: [url]

CONTRACTOR:
- Company: [name]
- Named contacts: [name, title — SOURCE: url]
- Contract value: [if known]

M&E / ENERGY CONSULTANT:
- Company: [name or NOT FOUND]
- Competitive position: COMPETITOR / PARTNER / NOT FOUND

OTHER STAKEHOLDERS:
- [role]: [company] — [named contact if found]

OUTREACH STRATEGY:
- Tier 1 (decision-maker): [who to contact, how, why]
- Tier 2 (specifier): [who to contact, how, why]
- Tier 3 (partner opportunity): [who to contact, how, why]

SOURCES:
[list every URL you consulted, even if it yielded nothing]

CRITICAL: Never fabricate names, emails, phone numbers, LinkedIn URLs, or company details. If not found, say "NOT FOUND". Every named contact MUST have a source URL.
```

---

## Consultant Type Prompt

Used by `profile-contacts` Part B Pass 1. One subagent per consultant. Use `model: "haiku"`.

```
Classify this consultant for {company_name} sales intelligence.

## Consultant:
- **Company:** {consultant_company}
- **Role on Project:** {consultant_role}

## Classify Type:
- Lighting consultant (RELEVANT)
- Energy consultant (RELEVANT)
- Sustainability consultant (RELEVANT)
- M&E consultant (RELEVANT)
- Structural engineer (NOT RELEVANT)
- QS / Cost consultant (NOT RELEVANT)
- Other (NOT RELEVANT)

## Output:
### TYPE: [type]
### RELEVANT: [YES/NO]
### REASONING: [one sentence]
```

---

## Consultant Competitive Prompt

Used by `profile-contacts` Part B Pass 2. Only for RELEVANT consultants. Use `model: "haiku"`.

```
Assess competitive overlap between {consultant_company} ({consultant_type}) and {company_name}.

{company_name} services:
{services_list}

## Classify Position:
- **COMPETITOR** - They do design + installation (directly compete)
- **PARTNER** - They do design-only OR audits ({company_name} delivers their recommendations)
- **IRRELEVANT** - No overlap

## Output:
### CLASSIFICATION: [COMPETITOR/PARTNER/IRRELEVANT]
### REASONING: [what they do vs what {company_name} does]
### PARTNERSHIP_OPPORTUNITY: [if PARTNER - how to work together]
```

---

## Portal Document List Prompt

Used by `download-documents` when extracting the document table. Use `model: "sonnet"`.

```
Navigate to {portal_url} and extract the full document list from the documents tab.

STEPS:
1. Open the URL in the browser
2. Wait for the documents table to load
3. Extract every row: description, href (download link), date published
4. Return the complete list as a JSON array

Return ONLY valid JSON:
[
  {{"description": "Design and Access Statement", "href": "https://...", "date_published": "2025-01-15"}}
]

Do NOT download any files. Just return the document list.
If the portal returns a 403/404 or the documents tab is empty, return: {{"error": "PORTAL_INACCESSIBLE"}}
```

---

## Portal Document Download Prompt

Used by `download-documents` for JSZip batch download. Use `model: "sonnet"`.

```
Download these {count} planning PDFs using JSZip in the browser. Process in batches of 5.

FILES TO DOWNLOAD:
{json_file_list}

FOR EACH BATCH:
1. Load JSZip: const JSZip = (await import('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js')).default
2. Create zip: const zip = new JSZip()
3. For each file:
   - const resp = await fetch(file.href)
   - const blob = await resp.blob()
   - zip.file(file.description.replace(/[^a-zA-Z0-9]/g, '_') + '.pdf', blob, {{compression: 'STORE'}})
4. Generate base64: const b64 = await zip.generateAsync({{type: 'base64'}})
5. Return the base64 string

If a file fails to download (404, timeout), skip it and continue.
```
