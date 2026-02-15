# Contact Profiling Reference

All contact profiling and competitive analysis logic. Used by /gleni-loop for contact steps.

## Prerequisites

- `glenigan.db` must exist with imported projects
- Projects should have `enrichment_classification` rows (Pass 1 complete)
- Best run after Pass 4 (contact assessment) but works independently

## Part A: Known Role Profiling

For each qualified project, profile ALL known roles from the Glenigan data — not just Architects. Every role is a potential outreach path.

### Target Selection

```python
targets = c.execute("""
    SELECT p.project_id, p.title, p.value_numeric, p.town, p.planning_ref,
           p.planning_authority,
           pr.role_type, pr.company_name, pr.company_address,
           pr.phone, pr.email, pr.website,
           c.name as contact_name, c.position, c.email as contact_email,
           c.phone as contact_phone, c.mobile,
           ep.verified_ref, er.summary as research_summary
    FROM projects p
    JOIN enrichment_classification ec ON p.project_id = ec.project_id
    LEFT JOIN project_roles pr ON p.project_id = pr.project_id
    LEFT JOIN contacts c ON pr.id = c.role_id
    LEFT JOIN enrichment_portal ep ON p.project_id = ep.project_id
    LEFT JOIN enrichment_web er ON p.project_id = er.project_id
    WHERE ec.status IN ('QUALIFIED', 'MAYBE')
      AND p.project_id NOT IN (SELECT project_id FROM enrichment_contacts)
    ORDER BY p.value_numeric DESC
    LIMIT 10
""").fetchall()
```

### Role Priority

Profile every role, but prioritize outreach differently:

| Priority | Role Types | Why |
|----------|-----------|-----|
| 1 | Client, Promoter, Developer | Holds budget, makes decisions |
| 2 | Architect | Influences specification, writes lighting/energy into design |
| 3 | M&E Consultant, Energy Consultant | Potential PARTNER — joint proposal opportunity |
| 4 | Contractor, Main Contractor | May sub-contract lighting packages |
| 5 | QS, Structural, Other | Lower value but still catalogue for completeness |

### Subagent Approach

Spawn one subagent per project using the Task tool. Use `model: "haiku"` for speed. Send in parallel batches of 5-10.

Read `references/prompts.md` for the full "Contact Profile Prompt" template.

Each subagent receives ALL roles for that project. For EACH company in the roles list, the subagent MUST complete these four mandatory lookups (do not skip any):

**Mandatory Step 1 — WebSearch:**
Search "[company name] contact phone email" and "[company name] directors". WebSearch returns rich snippets with phone numbers, emails, website URLs, LinkedIn profiles directly in results. Extract everything visible. This single step often provides 80% of what's needed.

**Mandatory Step 2 — Companies House:**
Search "[company name] Companies House" or navigate to find-and-update.company-information.service.gov.uk. Extract: company number, registered office, directors (names + appointment dates), SIC codes, active/dissolved status.

**Mandatory Step 3 — Company Website:**
Visit the website found in step 1. Look for: contact page (phone, email), team/about page (named individuals with titles), office addresses. Extract any direct emails (firstname.lastname@) and direct phone numbers.

**Mandatory Step 4 — LinkedIn:**
Search "[company name] LinkedIn" or "[director name] LinkedIn". Find key individuals: MD/CEO, directors, project managers. Extract profile URLs. Do NOT fabricate profiles.

After completing the three mandatory lookups per company, the subagent:
1. Assesses email quality: HIGH (personal) / MEDIUM (generic info@) / LOW (none)
2. Assesses phone quality: HIGH (mobile/direct 07xxx) / MEDIUM (switchboard) / LOW (none)
3. Recommends best outreach path per role: PHONE → EMAIL → LINKEDIN → RESEARCH_NEEDED

### Email Quality Patterns

| Quality | Patterns |
|---------|----------|
| HIGH | firstname.lastname@, firstname_lastname@, firstname@ (2+ chars) |
| MEDIUM | info@, enquiries@, contact@, hello@, studio@, office@, admin@, reception@, general@ |
| LOW | No email found |

### Phone Quality Patterns

| Quality | Patterns |
|---------|----------|
| HIGH | UK mobile (07xxx, +447), labeled "direct line" or "mobile" |
| MEDIUM | Landline, labeled "switchboard", "main", "reception" |
| LOW | No phone found |

## Part B: Wider Stakeholder Discovery

Part A only profiles what's already in the Glenigan database. For many projects, the PDF lists just Client + Architect — missing the full picture of who controls the project.

Part B fills the gap using web research. It runs for EVERY qualified project, even those with good DB roles.

### When to Run Part B

ALWAYS. Even if Part A found contacts, Part B often uncovers:
- Property owner / landlord (the actual budget holder)
- Development manager (coordinates consultants)
- Named individuals within known companies
- Contractor (if not in Glenigan data)
- Project manager
- Facilities manager (for refurbishments)

### Research Strategy

Spawn one subagent per project using the Task tool. Use `model: "sonnet"` (needs reasoning for complex web research).

Read `references/prompts.md` for the full "Stakeholder Discovery Prompt" template.

The subagent uses THREE research layers. All are mandatory.

#### Layer 1: Per-Company Lookups (MANDATORY — do this for EVERY known company)

For each company in the project's roles, the subagent MUST do:

1. **WebSearch first** — Search "[company name] contact phone email" and "[company name] directors". WebSearch returns rich snippets with phone numbers, emails, website URLs, and LinkedIn profiles directly in results — often faster than visiting sites. Extract everything visible in search results.
2. **Companies House** — Search "[company name] Companies House" or navigate to find-and-update.company-information.service.gov.uk. Extract: company number, directors (names + appointment dates), registered office, SIC codes, status.
3. **Company Website** — Visit the website found in step 1. Extract: contact page (phone, email), team/about page (named people), addresses. Look for direct emails (firstname.lastname@).
4. **LinkedIn** — Search "[company name] LinkedIn" or "[director name] LinkedIn". Extract profile URLs for MD/CEO, directors, project managers. Never fabricate.

This is the foundation. It reliably finds contacts even for small/obscure companies. WebSearch in step 1 often returns phone, email, and LinkedIn in a single query — do NOT skip it.

#### Layer 2: Google AI Mode (wider discovery — goes beyond known roles)

AI mode synthesized queries to discover stakeholders NOT in the Glenigan data:
1. "Who owns [address]?" — property owner, landlord, REIT
2. "Who is developing [address] [town]?" — developer, promoter
3. "[project title] [town] architect contractor" — project team
4. "[applicant company] development projects" — company profile, key people
5. "[address] planning application [ref]" — parties, decision, context

Any NEW companies discovered → run Layer 1 lookups on them too.

#### Layer 3: Planning Portal (if ref/keyval available)

Hit the council planning portal directly via browser automation:
- Application form shows applicant name + agent
- Officer/committee report names parties consulted
- Decision notice names the applicant

#### Supplementary Sources (fill remaining gaps)

**Property press:** Estates Gazette, CoStar, Property Week, React News
**Trade press:** Construction Enquirer, Building, PBC Today, local news

**Contractor / Tender Intelligence:**
- Contract award notices (OJEU/Find a Tender for public sector)
- Contractor appointment announcements

### Output Requirements

The subagent must return a structured stakeholder map:

```
STAKEHOLDER MAP for [project_id]:

OWNER/LANDLORD:
- Company: [name]
- Named contacts: [name, role — with source URL]
- Type: [REIT / developer / local authority / private]

DEVELOPER/PROMOTER:
- Company: [name]
- Named contacts: [name, role — with source URL]
- LinkedIn: [URL if found]

ARCHITECT:
- Company: [name]
- Named contacts: [name, role — with source URL]
- Website: [URL]
- LinkedIn: [URL if found]

CONTRACTOR:
- Company: [name]
- Named contacts: [name, role — with source URL]
- Contract value: [if known]

OTHER STAKEHOLDERS:
- [role]: [company] — [named contacts]

OUTREACH STRATEGY:
- Tier 1 (decision-maker): [who and how to reach]
- Tier 2 (specifier): [who and how to reach]
- Tier 3 (partner opportunity): [who and how to reach]

SOURCES:
[list all URLs consulted]
```

### Merge with Part A

After Part B returns:
1. Merge new contacts with Part A findings
2. Part B discoveries that match Part A companies → enrich the existing record
3. Part B discoveries of NEW stakeholders → add as new contact records
4. Resolve conflicts: Part B (from official sources) overrides Part A (from Glenigan PDF) for names/roles

### Write to DB

Store the full stakeholder map. The enrichment_contacts table holds the structured assessment, crm_notes holds the detailed narrative.

```python
now = datetime.utcnow().isoformat() + 'Z'

# Structured assessment
c.execute("""
    INSERT OR REPLACE INTO enrichment_contacts
    (project_id, architect_quality, linkedin_urls, outreach_action,
     stakeholder_map, enriched_at, enriched_by)
    VALUES (?, ?, ?, ?, ?, ?, 'profile-contacts')
""", (project_id, quality_json, linkedin_json, recommended_action,
      stakeholder_map_json, now))

# Detailed narrative for CRM
c.execute("""
    INSERT INTO crm_notes (project_id, note, created_at)
    VALUES (?, ?, ?)
""", (project_id, f"STAKEHOLDER MAP: {stakeholder_narrative}", now))
```

## Part C: Consultant Competitive Analysis

Many Glenigan exports list only Client and Architect — no M&E or specialist consultants. This is normal. In a typical 15-project batch, expect 0-3 projects with relevant consultant data. If none found, skip entirely.

### Pass 1 — Type Classification

For each consultant role on qualified projects, classify relevance:

| Type | Relevant? |
|------|-----------|
| Lighting consultant | YES |
| Energy consultant | YES |
| Sustainability consultant | YES |
| M&E consultant | YES |
| Structural engineer | NO |
| QS / Cost consultant | NO |
| Other | NO |

Spawn haiku subagents in parallel. Read `references/prompts.md` → "Consultant Type Prompt".

### Pass 2 — Competitive Assessment (relevant consultants only)

For consultants classified as relevant, assess competitive position:

| Classification | Meaning | Action |
|---------------|---------|--------|
| COMPETITOR | Does design + installation (competes directly) | Track, don't contact |
| PARTNER | Design-only or energy audits (can deliver their recommendations) | Potential joint proposal |
| IRRELEVANT | No meaningful overlap | Ignore |

Spawn haiku subagents. Read `references/prompts.md` → "Consultant Competitive Prompt".

### Store Results

Store consultant profiles in `crm_notes` linked to the project:

```python
c.execute("""
    INSERT INTO crm_notes (project_id, note, created_at)
    VALUES (?, ?, ?)
""", (project_id, f"CONSULTANT PROFILE: {company} — {type} — {classification}. {reasoning}", now))
```

## Batch Behavior

User can say:
- "profile contacts for project 26065152" — single project
- "profile all contacts" — all qualified projects without enrichment_contacts
- "check consultants" — consultant competitive analysis only
