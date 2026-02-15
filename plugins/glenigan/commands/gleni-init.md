---
description: Initialize Glenigan pipeline database and workspace
allowed-tools: Bash, Write, Read
---

Initialize the Glenigan lead qualification pipeline in the user's workspace folder.

## Storage

The database lives directly in the user's workspace folder: `{workspace}/glenigan.db`. All reads and writes happen at this path. No temp copies, no SQL dumps, no recovery dance.

## Steps

1. Check if `glenigan.db` exists in the workspace. If it does, run `PRAGMA integrity_check`. If healthy, ask user whether to reset or keep existing data.

2. If no DB exists (or user chose reset), create the SQLite database directly at `{workspace}/glenigan.db` using Python `sqlite3`. Run the schema SQL below.

3. If DB already exists and is healthy, check for missing columns/tables and add them using ALTER TABLE and CREATE TABLE IF NOT EXISTS rather than requiring a reset. This supports the "seed latest state" behavior.

4. Confirm to the user: report table count, and note that the database is ready for PDF ingestion.

## SQLite Schema

Run this exact SQL to create the database:

```sql
-- ============================================================
-- Glenigan Pipeline Schema v0.3.0
-- Three-tier: Core (immutable) | Enrichment (progressive) | Operational
-- ============================================================

PRAGMA foreign_keys=ON;

-- ============================================================
-- CORE LAYER: Immutable PDF-extracted data
-- These tables are written once at import and never modified.
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    -- Identity
    project_id          TEXT PRIMARY KEY,           -- Glenigan ID e.g. "26065152"
    source_pdf          TEXT NOT NULL,              -- Origin PDF filename
    imported_at         TEXT NOT NULL,              -- ISO 8601 timestamp
    is_new              INTEGER NOT NULL DEFAULT 0, -- 1 if NEW, 0 if UPDATED
    updated_date        TEXT,                       -- Date from "UPDATED - dd/mm/yyyy"

    -- Description
    title               TEXT NOT NULL,              -- Short title e.g. "Light Industrial/Warehouse"
    scheme_description  TEXT,                       -- Full scheme description paragraph
    additional_text     TEXT,                       -- Optional additional text block
    latest_info_date    TEXT,                       -- Date of latest information
    latest_info_text    TEXT,                       -- Latest information free text

    -- Location
    address_line        TEXT,                       -- Street address e.g. "84 Birmingham Road"
    address_full        TEXT,                       -- Full address with postcode
    town                TEXT,                       -- Town/city
    region              TEXT,                       -- Region e.g. "WEST MIDLANDS", "LONDON"
    postcode            TEXT,                       -- Extracted postcode if available

    -- Financials
    value_text          TEXT NOT NULL,              -- Original string e.g. "£3,900,000"
    value_numeric       REAL NOT NULL,              -- Parsed number for calculations
    funding_type        TEXT,                       -- "Private" or "Public"
    value_basis         TEXT,                       -- "Calculated" or "Guideline"

    -- Dates
    start_date          TEXT,                       -- ISO date
    end_date            TEXT,                       -- ISO date
    contract_period     TEXT,                       -- e.g. "24 Months"
    dates_basis         TEXT,                       -- "Calculated" or "Guideline"

    -- Stages (three separate dimensions)
    project_status      TEXT,                       -- e.g. "In Progress"
    planning_stage      TEXT,                       -- e.g. "Pre-Planning", "Detailed Plans Submitted"
    contact_stage       TEXT,                       -- e.g. "Pre-Tender", "Contract Awarded"

    -- Project summary
    development_type    TEXT,                       -- e.g. "Refurbishment", "New Build"
    floor_area          TEXT,                       -- e.g. "4090" (sqm, as text to preserve "Not Available")
    units               TEXT,                       -- e.g. "1" or "Not Available"
    storeys             TEXT,                       -- e.g. "3" or "Not Available"
    site_number         TEXT,                       -- e.g. "Not Available"

    -- Planning
    planning_authority  TEXT,                       -- e.g. "Dudley", "Oxford"
    planning_ref        TEXT,                       -- Council ref e.g. "25/00798/SCREEN" (may be NULL)
    pp_reference        TEXT                        -- Planning Portal ref e.g. "PP-14683772" (from latest_info_text)
);

CREATE TABLE IF NOT EXISTS sectors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    sector_name         TEXT NOT NULL,              -- e.g. "Warehousing/Storage"
    is_primary          INTEGER NOT NULL DEFAULT 0, -- 1 if "(Primary)"
    UNIQUE(project_id, sector_name)
);

CREATE TABLE IF NOT EXISTS materials (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    category            TEXT NOT NULL,              -- e.g. "Doors", "Fittings", "Walls"
    items               TEXT NOT NULL,              -- e.g. "Industrial Doors (Unspecified)"
    UNIQUE(project_id, category, items)
);

CREATE TABLE IF NOT EXISTS project_roles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    role_type           TEXT NOT NULL,              -- e.g. "Client / Promoter", "Architect / Plans By", "Project Manager"
    company_name        TEXT,                       -- e.g. "Alanto Ltd (TA Ramfoam)"
    company_address     TEXT,
    phone               TEXT,
    email               TEXT,
    website             TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id             INTEGER NOT NULL REFERENCES project_roles(id),
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    name                TEXT NOT NULL,              -- e.g. "Jamie Endres"
    position            TEXT,                       -- e.g. "Director", "Not Available"
    email               TEXT,
    phone               TEXT,
    mobile              TEXT
);

-- ============================================================
-- ENRICHMENT LAYER: Progressive skill enhancements
-- Each row is nullable. Each has source attribution.
-- ============================================================

CREATE TABLE IF NOT EXISTS enrichment_classification (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    status              TEXT NOT NULL,              -- "QUALIFIED", "MAYBE", "REJECTED"
    vertical            TEXT,                       -- "STRONG", "GOOD", "EXCLUDED", "UNKNOWN"
    reasoning           TEXT,                       -- One sentence explanation
    confidence          REAL,                       -- 0.0 to 1.0
    enriched_at         TEXT NOT NULL,              -- ISO 8601
    enriched_by         TEXT NOT NULL DEFAULT 'classify-opportunities'
);

CREATE TABLE IF NOT EXISTS enrichment_portal (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    portal_status       TEXT,                       -- "CRAWLABLE", "ADVANCED_CRAWLING", "UNMAPPABLE", "PORTAL_MAINTENANCE"
    portal_url          TEXT,                       -- Full URL to the portal search page
    portal_type         TEXT,                       -- "idox", "planit", "arcus", "northgate", "unknown"
    verified_ref        TEXT,                       -- Verified planning reference (may differ from core)
    keyval              TEXT,                       -- Idox keyVal for direct document access
    csrf_required       INTEGER DEFAULT 0,          -- 1 if portal needs CSRF token handling
    enriched_at         TEXT NOT NULL,
    enriched_by         TEXT NOT NULL DEFAULT 'enrich-project'
);

CREATE TABLE IF NOT EXISTS enrichment_web (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    summary             TEXT,                       -- Web research summary
    second_pass_status  TEXT,                       -- "CONFIRMED", "UPGRADED", "DOWNGRADED"
    sources             TEXT,                       -- JSON array of source URLs
    enriched_at         TEXT NOT NULL,
    enriched_by         TEXT NOT NULL DEFAULT 'enrich-project'
);

CREATE TABLE IF NOT EXISTS enrichment_contacts (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    architect_quality   TEXT,                       -- "HIGH", "MEDIUM", "LOW"
    linkedin_urls       TEXT,                       -- JSON object of contact name -> LinkedIn URL
    outreach_action     TEXT,                       -- "PHONE", "EMAIL", "LINKEDIN"
    stakeholder_map     TEXT,                       -- JSON: full stakeholder map from Part B discovery
    enriched_at         TEXT NOT NULL,
    enriched_by         TEXT NOT NULL DEFAULT 'enrich-project'
);

CREATE TABLE IF NOT EXISTS enrichment_scoring (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    priority_score      REAL,                       -- 0-200
    rank                INTEGER,                    -- 1 = highest priority
    factor_start_date   REAL,
    factor_vertical     REAL,
    factor_value        REAL,
    factor_second_pass  REAL,
    enriched_at         TEXT NOT NULL,
    enriched_by         TEXT NOT NULL DEFAULT 'prioritize-opportunities'
);

-- ============================================================
-- DOCUMENT ENRICHMENT: Post-extraction document signal data
-- Populated by doc enrichment runs (batch-extract + document analysis)
-- ============================================================

CREATE TABLE IF NOT EXISTS doc_enrichment (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    authority           TEXT NOT NULL,              -- Planning authority name
    planning_ref        TEXT NOT NULL,              -- Council reference
    project_id          TEXT,                       -- FK to projects (NULL if ref didn't match)
    keyval              TEXT,                       -- Idox keyVal extracted
    status              TEXT,                       -- "ok" or error description
    error               TEXT,                       -- Error detail if status != "ok"
    title               TEXT,                       -- Application title from portal
    total_documents     INTEGER DEFAULT 0,          -- Count of indexed documents
    signal_decision     INTEGER DEFAULT 0,          -- 1 if decision notice found
    signal_lighting     INTEGER DEFAULT 0,          -- 1 if lighting docs found
    signal_energy       INTEGER DEFAULT 0,          -- 1 if energy/sustainability docs found
    signal_das          INTEGER DEFAULT 0,          -- 1 if design & access statement found
    signal_officer      INTEGER DEFAULT 0,          -- 1 if officer/committee report found
    high_docs           TEXT                        -- JSON array of high-priority document names
);

-- ============================================================
-- OPERATIONAL LAYER: Workflow state and metadata
-- ============================================================

CREATE TABLE IF NOT EXISTS processing_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    stage               TEXT NOT NULL,              -- "imported", "classified", "enriched", "qualified", "synced"
    timestamp           TEXT NOT NULL,
    skill               TEXT NOT NULL,              -- Which skill performed this
    notes               TEXT                        -- Optional notes
);

CREATE TABLE IF NOT EXISTS downloaded_documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    document_type       TEXT NOT NULL,              -- 'decision_notice', 'design_access', 'officer_report', 'planning_statement', 'other'
    filename            TEXT NOT NULL,              -- Sanitized local filename
    original_name       TEXT,                       -- Original filename from portal
    source_url          TEXT,
    priority            TEXT,                       -- 'HIGH', 'MEDIUM', 'LOW' (from playbook)
    catalogued_at       TEXT NOT NULL,              -- When first seen on portal (Step 2.5)
    downloaded_at       TEXT,                       -- When file was downloaded (NULL = catalogued only)
    download_method     TEXT,                       -- 'click', 'fetch', 'jszip', 'http'
    file_size           INTEGER,                    -- NULL until actually downloaded
    content_summary     TEXT,                       -- AI-generated summary after reading
    UNIQUE(project_id, filename)
);

-- ============================================================
-- CRM LAYER: Built-in pipeline management
-- ============================================================

CREATE TABLE IF NOT EXISTS crm_deals (
    project_id          TEXT PRIMARY KEY REFERENCES projects(project_id),
    stage               TEXT NOT NULL DEFAULT 'new_lead',
                        -- Stages: new_lead -> contacted -> meeting -> proposal -> negotiation -> won / lost / parked
    substage            TEXT,
    temperature         TEXT DEFAULT 'warm',        -- hot / warm / cold
    next_action         TEXT,
    next_action_date    TEXT,
    deal_value          REAL,
    lost_reason         TEXT,
    won_date            TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_activities (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    activity_type       TEXT NOT NULL,              -- 'call', 'email', 'linkedin', 'meeting', 'note', 'site_visit'
    direction           TEXT,                       -- 'outbound', 'inbound'
    contact_name        TEXT,
    contact_role        TEXT,
    channel             TEXT,
    summary             TEXT NOT NULL,
    outcome             TEXT,
    follow_up           TEXT,
    follow_up_date      TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_notes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    note                TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

-- ============================================================
-- PORTAL REGISTRY: Grows over time as portals are confirmed.
-- Seeded from real pipeline runs (Feb 2026).
-- ============================================================

CREATE TABLE IF NOT EXISTS portal_registry (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    authority_name      TEXT NOT NULL UNIQUE,
    portal_url          TEXT,
    portal_type         TEXT,                       -- "idox", "publicaccess", "arcus", "northgate", "unknown"
    search_url_pattern  TEXT,
    csrf_required       INTEGER DEFAULT 0,
    connectivity        TEXT DEFAULT 'untested',    -- "connected", "partial", "failed", "untested"
    last_attempt        TEXT,
    last_success        TEXT,
    success_count       INTEGER DEFAULT 0,
    fail_count          INTEGER DEFAULT 0,
    last_error          TEXT,
    capabilities        TEXT,
    last_confirmed      TEXT,
    notes               TEXT
);

-- Seed from real pipeline runs + Playwright testing (Feb 2026).
-- 35 connected, 11 failed, 14 unverified. Full list in portal-registry.md.

-- CONNECTED: Confirmed working with fetch POST or Playwright form fill
INSERT OR IGNORE INTO portal_registry (authority_name, portal_url, portal_type, csrf_required, connectivity, notes) VALUES
    ('Barnet', 'https://publicaccess.barnet.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox. Keyval confirmed.'),
    ('Bolton', 'https://www.planning.bolton.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Brent', 'https://planning.brent.gov.uk/online-applications', 'idox', 0, 'connected', 'Non-standard keyvals: DCAPR_175962 format (underscores). Use widened regex.'),
    ('Bristol', 'https://pa.bristol.gov.uk/online-applications', 'idox', 1, 'connected', 'CSRF required for HTTP. Cloudflare active. Playwright handles both.'),
    ('Burnley', 'https://publicaccess.burnley.gov.uk/online-applications', 'idox', 0, 'connected', 'Keyval confirmed.'),
    ('Cardiff', 'https://www.cardiffidoxcloud.wales/publicaccess', 'publicaccess', 0, 'connected', 'Welsh authority, .wales domain. PublicAccess variant.'),
    ('Cheltenham', 'https://publicaccess.cheltenham.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Chiltern', 'https://publicaccess.chiltern.gov.uk/online-applications', 'idox', 0, 'connected', 'Keyval confirmed.'),
    ('City of London', 'https://www.planning2.cityoflondon.gov.uk/online-applications', 'idox', 0, 'connected', 'Note planning2 subdomain. Keyval confirmed.'),
    ('Cotswold', 'https://publicaccess.cotswold.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Croydon', 'https://publicaccess3.croydon.gov.uk/online-applications', 'idox', 0, 'connected', 'Note publicaccess3 subdomain.'),
    ('Hart', 'https://publicaccess.hart.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Isle of Wight', 'https://publicaccess.iow.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Lambeth', 'https://planning.lambeth.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Lancaster', 'https://planning.lancaster.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Lichfield', 'https://publicaccess.lichfielddc.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Manchester', 'https://pa.manchester.gov.uk/online-applications', 'idox', 0, 'connected', 'Uses caseReference field, not searchCriteria.'),
    ('Medway', 'https://publicaccess.medway.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Mendip', 'https://publicaccess.mendip.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Newham', 'https://pa.newham.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('North Somerset', 'https://planning.n-somerset.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Oxford', 'https://public.oxford.gov.uk/online-applications', 'idox', 0, 'connected', 'Lazy-loaded doc tables — add 2s wait. Keyval confirmed.'),
    ('Pendle', 'https://publicaccess.pendle.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Plymouth', 'https://planning.plymouth.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Portsmouth', 'https://publicaccess.portsmouth.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Sandwell', 'https://webcaps.sandwell.gov.uk/publicaccess', 'publicaccess', 0, 'connected', 'PublicAccess variant.'),
    ('Sefton', 'https://pa.sefton.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Sevenoaks', 'https://pa.sevenoaks.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Shropshire', 'https://pa.shropshire.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Southampton', 'https://planningpublicaccess.southampton.gov.uk/online-applications', 'idox', 0, 'connected', 'Keyval confirmed.'),
    ('Southwark', 'https://planning.southwark.gov.uk/online-applications', 'idox', 0, 'connected', 'Docs often paginated. Keyval confirmed.'),
    ('Surrey Heath', 'https://publicaccess.surreyheath.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Swindon', 'https://pa.swindon.gov.uk/publicaccess', 'publicaccess', 0, 'connected', 'PublicAccess variant. Uses S/ prefix in refs. Keyval confirmed.'),
    ('Tunbridge Wells', 'https://publicaccess.tunbridgewells.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('West Berkshire', 'https://publicaccess.westberks.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Westminster', 'https://idoxpa.westminster.gov.uk/online-applications', 'idox', 0, 'connected', 'Aggressive rate limiting — use 3-5s delays. Keyval confirmed.'),
    ('Wolverhampton', 'https://planningonline.wolverhampton.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.');

-- CONNECTED (from doc_enrichment JSON, not yet in Playwright-tested list)
INSERT OR IGNORE INTO portal_registry (authority_name, portal_url, portal_type, csrf_required, connectivity, notes) VALUES
    ('Bexley', 'https://pa.bexley.gov.uk/online-applications', 'idox', 0, 'connected', 'From doc enrichment. Needs Playwright verification.'),
    ('Chorley', 'https://planning.chorley.gov.uk/online-applications', 'idox', 0, 'connected', 'From doc enrichment.'),
    ('Enfield', 'https://planningandbuildingcontrol.enfield.gov.uk/online-applications', 'idox', 0, 'connected', 'From doc enrichment.'),
    ('Monmouthshire', 'https://planningonline.monmouthshire.gov.uk/online-applications', 'idox', 0, 'connected', 'Welsh authority. From doc enrichment.'),
    ('Oldham', 'https://planningpa.oldham.gov.uk/online-applications', 'idox', 0, 'connected', 'From doc enrichment.'),
    ('Solihull', 'https://publicaccess.solihull.gov.uk/online-applications', 'idox', 0, 'connected', 'Standard Idox.'),
    ('Swansea', 'https://planning.swansea.gov.uk/online-applications', 'idox', 0, 'connected', 'Welsh authority.'),
    ('Torfaen', 'https://planning.torfaen.gov.uk/online-applications', 'idox', 0, 'connected', 'Welsh authority. From doc enrichment.');

-- FAILED: Known broken (Feb 2026)
INSERT OR IGNORE INTO portal_registry (authority_name, portal_url, portal_type, csrf_required, connectivity, last_error, notes) VALUES
    ('Barking & Dagenham', NULL, 'unknown', 0, 'failed', 'DNS resolution failed for all subdomain variants', 'Portal URL needs discovery.'),
    ('Caerphilly', 'https://publicaccess.caerphilly.gov.uk/PublicAccess', 'publicaccess', 0, 'failed', 'Timeout on navigation', 'Note capital P in PublicAccess.'),
    ('Cornwall', 'https://planning.cornwall.gov.uk/online-applications', 'idox', 0, 'failed', 'Portal offline for maintenance', 'Was working, went down Feb 2026. Retry later.'),
    ('Ealing', 'https://pam.ealing.gov.uk/online-applications', 'unknown', 0, 'failed', 'Non-standard portal, redirect to third-party', 'Returns 404. Needs URL rediscovery.'),
    ('East Staffordshire', NULL, 'unknown', 0, 'failed', 'DNS resolution failed', 'Portal URL needs discovery.'),
    ('Flintshire', NULL, 'unknown', 0, 'failed', 'DNS resolution failed', 'Welsh authority. Portal URL needs discovery.'),
    ('Fylde', 'https://pa.fylde.gov.uk/Search/Advanced/', 'unknown', 0, 'failed', 'Portal returns 404 for standard paths', 'Non-Idox search interface.'),
    ('Halton', NULL, 'unknown', 0, 'failed', 'Portal returns 404 on search pages', 'Portal URL needs discovery.'),
    ('Teignbridge', NULL, 'unknown', 0, 'failed', 'Timeout on navigation', 'Portal URL needs discovery.'),
    ('Winchester', 'https://planningapps.winchester.gov.uk/online-applications', 'idox', 0, 'failed', 'ERR_CERT_AUTHORITY_INVALID', 'Expired SSL cert (Feb 2026). Portal-side issue. Retry later.'),
    ('Wychavon', NULL, 'unknown', 0, 'failed', 'DNS resolution failed', 'Portal URL needs discovery.'),
    ('Wyre', NULL, 'unknown', 0, 'failed', 'Timeout on navigation', 'Portal URL needs discovery.');

-- FAILED (from doc_enrichment errors)
INSERT OR IGNORE INTO portal_registry (authority_name, portal_url, portal_type, csrf_required, connectivity, last_error, notes) VALUES
    ('Exeter', 'https://publicaccess.exeter.gov.uk/online-applications', 'idox', 0, 'failed', 'Portal returned Error page', '3x errors in doc enrichment. Was listed as verified.'),
    ('Horsham', 'https://public-access.horsham.gov.uk/public-access', 'publicaccess', 0, 'failed', 'Portal returned Error page', 'Hyphenated PublicAccess variant.'),
    ('Merthyr Tydfil', NULL, 'unknown', 0, 'failed', 'Portal returned Error page', 'Welsh authority. Portal URL needs discovery.'),
    ('Newport', NULL, 'unknown', 0, 'failed', 'Portal returned Error page', 'Welsh authority. Portal URL needs discovery.');

-- UNTESTED: URL mapped from reference, not yet confirmed by pipeline
INSERT OR IGNORE INTO portal_registry (authority_name, portal_url, portal_type, csrf_required, connectivity, notes) VALUES
    ('Brighton & Hove', 'https://planningapps.brighton-hove.gov.uk/online-applications', 'idox', 0, 'untested', 'Error pages reported Feb 2026. Likely Cloudflare IP block.'),
    ('Camden', 'https://publicaccess.camden.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Canterbury', 'https://publicaccess.canterbury.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Coventry', 'https://planning.coventry.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Darlington', 'https://publicaccess.darlington.gov.uk/online-applications', 'idox', 0, 'untested', 'Likely standard.'),
    ('Derby', 'https://eplanning.derby.gov.uk/online-applications', 'idox', 0, 'untested', 'Non-standard subdomain.'),
    ('Dudley', 'https://publicaccess.dudley.gov.uk/online-applications', 'idox', 0, 'untested', 'Likely standard.'),
    ('Edinburgh', 'https://citydev-portal.edinburgh.gov.uk/online-applications', 'idox', 0, 'untested', 'Non-standard subdomain.'),
    ('Glasgow', 'https://publicaccess.glasgow.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Gloucestershire', 'https://planning.gloucestershire.gov.uk/online-applications', 'idox', 0, 'untested', 'County-level portal.'),
    ('Hackney', 'https://planning.hackney.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Haringey', 'https://publicaccess.haringey.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Islington', 'https://planning.islington.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Kirklees', 'https://publicaccess.kirklees.gov.uk/online-applications', 'idox', 0, 'untested', 'Likely standard.'),
    ('Leeds', 'https://publicaccess.leeds.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Lewisham', 'https://planning.lewisham.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Liverpool', 'https://planning.liverpool.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Newcastle', 'https://publicaccess.newcastle.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Nottingham', 'https://publicaccess.nottinghamcity.gov.uk/online-applications', 'idox', 0, 'untested', 'Note nottinghamcity.'),
    ('Reading', 'https://planning.reading.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Sheffield', 'https://planningapps.sheffield.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Stockport', 'https://planning.stockport.gov.uk/online-applications', 'idox', 0, 'untested', 'Likely standard.'),
    ('Tower Hamlets', 'https://development.towerhamlets.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('Wakefield', 'https://planning.wakefield.gov.uk/online-applications', 'idox', 0, 'untested', 'Likely standard.'),
    ('Wandsworth', 'https://planning.wandsworth.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.'),
    ('York', 'https://planningaccess.york.gov.uk/online-applications', 'idox', 0, 'untested', 'Standard Idox.');

-- ============================================================
-- INDEXES for common queries
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_projects_region ON projects(region);
CREATE INDEX IF NOT EXISTS idx_projects_planning_authority ON projects(planning_authority);
CREATE INDEX IF NOT EXISTS idx_projects_value ON projects(value_numeric);
CREATE INDEX IF NOT EXISTS idx_projects_planning_stage ON projects(planning_stage);
CREATE INDEX IF NOT EXISTS idx_sectors_project ON sectors(project_id);
CREATE INDEX IF NOT EXISTS idx_roles_project ON project_roles(project_id);
CREATE INDEX IF NOT EXISTS idx_contacts_project ON contacts(project_id);
CREATE INDEX IF NOT EXISTS idx_processing_log_project ON processing_log(project_id);
CREATE INDEX IF NOT EXISTS idx_downloaded_docs_project ON downloaded_documents(project_id);
CREATE INDEX IF NOT EXISTS idx_crm_deals_stage ON crm_deals(stage);
CREATE INDEX IF NOT EXISTS idx_crm_deals_next_action ON crm_deals(next_action_date);
CREATE INDEX IF NOT EXISTS idx_crm_activities_project ON crm_activities(project_id);
CREATE INDEX IF NOT EXISTS idx_crm_activities_date ON crm_activities(created_at);
CREATE INDEX IF NOT EXISTS idx_doc_enrichment_project ON doc_enrichment(project_id);
CREATE INDEX IF NOT EXISTS idx_doc_enrichment_authority ON doc_enrichment(authority);
CREATE INDEX IF NOT EXISTS idx_doc_enrichment_signals ON doc_enrichment(signal_lighting, signal_energy);

-- ============================================================
-- VIEWS for common queries
-- ============================================================

CREATE VIEW IF NOT EXISTS v_pipeline_summary AS
SELECT
    p.project_id,
    p.title,
    p.town,
    p.region,
    p.value_numeric,
    p.planning_authority,
    p.planning_ref,
    p.planning_stage,
    p.contact_stage,
    ec.status AS classification,
    ep.portal_status,
    ep.keyval,
    es.priority_score,
    es.rank,
    de.total_documents,
    de.signal_lighting,
    de.signal_energy,
    (SELECT stage FROM processing_log WHERE project_id = p.project_id ORDER BY timestamp DESC LIMIT 1) AS current_stage
FROM projects p
LEFT JOIN enrichment_classification ec ON p.project_id = ec.project_id
LEFT JOIN enrichment_portal ep ON p.project_id = ep.project_id
LEFT JOIN enrichment_scoring es ON p.project_id = es.project_id
LEFT JOIN doc_enrichment de ON p.project_id = de.project_id;

CREATE VIEW IF NOT EXISTS v_qualified_leads AS
SELECT * FROM v_pipeline_summary
WHERE classification = 'QUALIFIED'
ORDER BY rank ASC, value_numeric DESC;

CREATE VIEW IF NOT EXISTS v_enrichment_queue AS
SELECT
    p.project_id,
    p.title,
    p.planning_authority,
    p.planning_ref,
    p.value_numeric,
    p.value_basis,
    p.region,
    pr.connectivity,
    pr.portal_type,
    pr.success_count,
    pr.portal_url,
    ep.portal_status AS already_enriched,
    CASE
        WHEN pr.connectivity = 'connected' THEN 1
        WHEN pr.connectivity = 'partial'   THEN 2
        WHEN pr.connectivity = 'untested'  THEN 3
        WHEN pr.connectivity = 'failed'    THEN 4
        ELSE 5
    END AS priority_tier
FROM projects p
LEFT JOIN portal_registry pr ON p.planning_authority = pr.authority_name
LEFT JOIN enrichment_portal ep ON p.project_id = ep.project_id
WHERE ep.project_id IS NULL
ORDER BY priority_tier ASC, p.value_numeric DESC;

-- CILS-specific: projects with lighting or energy document signals
CREATE VIEW IF NOT EXISTS v_cils_signals AS
SELECT
    p.project_id,
    p.title,
    p.town,
    p.value_numeric,
    p.planning_authority,
    de.signal_lighting,
    de.signal_energy,
    de.total_documents,
    de.high_docs,
    ec.status AS classification
FROM projects p
JOIN doc_enrichment de ON p.project_id = de.project_id
LEFT JOIN enrichment_classification ec ON p.project_id = ec.project_id
WHERE de.signal_lighting = 1 OR de.signal_energy = 1
ORDER BY p.value_numeric DESC;

CREATE VIEW IF NOT EXISTS v_crm_pipeline AS
SELECT
    d.project_id,
    p.title,
    p.town,
    p.region,
    p.value_numeric AS project_value,
    d.deal_value,
    d.stage,
    d.temperature,
    d.next_action,
    d.next_action_date,
    d.updated_at,
    ec.status AS classification,
    ec.vertical,
    (SELECT COUNT(*) FROM crm_activities a WHERE a.project_id = d.project_id) AS activity_count,
    (SELECT summary FROM crm_activities a WHERE a.project_id = d.project_id ORDER BY created_at DESC LIMIT 1) AS last_activity
FROM crm_deals d
JOIN projects p ON d.project_id = p.project_id
LEFT JOIN enrichment_classification ec ON d.project_id = ec.project_id
ORDER BY
    CASE d.temperature
        WHEN 'hot' THEN 1
        WHEN 'warm' THEN 2
        WHEN 'cold' THEN 3
    END,
    d.next_action_date ASC;

CREATE VIEW IF NOT EXISTS v_crm_overdue AS
SELECT * FROM v_crm_pipeline
WHERE next_action_date IS NOT NULL
  AND next_action_date < date('now')
  AND stage NOT IN ('won', 'lost', 'parked');

CREATE VIEW IF NOT EXISTS v_crm_today AS
SELECT * FROM v_crm_pipeline
WHERE next_action_date = date('now')
  AND stage NOT IN ('won', 'lost', 'parked');
```

## Post-Creation

After creating the database, report:
- Number of tables created (18)
- Number of seeded portal registry entries (by connectivity tier)
- Full path to the database file
- Remind the user they can now use the `ingest-pdf` skill by uploading a Glenigan PDF
