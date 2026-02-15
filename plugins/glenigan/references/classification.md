# Classification Reference

All classification logic for Pass 1. Used by /gleni-loop when classifying a project.

## Playbook

**All sector mappings, value thresholds, and exclusion patterns are defined in the playbook. Read `config/rules.json` (the playbook) first.**

Baresquare qualifies Glenigan leads on behalf of clients. The current client's playbook lives in `config/rules.json`. Switch clients by replacing that file.

```python
import json, os

config_path = os.path.join(plugin_dir, 'config', 'rules.json')
with open(config_path) as f:
    client = json.load(f)

STRONG_SECTORS = set(client['sector_relevance']['STRONG'])
GOOD_SECTORS = set(client['sector_relevance']['GOOD'])
EXCLUDED_SECTORS = set(client['sector_relevance']['EXCLUDED'])

QUALIFIED_MIN = client['value_thresholds']['qualified_min']     # e.g. 500000
MAYBE_MIN = client['value_thresholds']['maybe_min']             # e.g. 200000
BIG_UNKNOWN_MIN = client['value_thresholds']['big_unknown_min'] # e.g. 2000000
SMALL_PROJECT_CUTOFF = client['value_thresholds'].get('small_project_cutoff', 250000)

EXCLUSION_PATTERNS = client.get('exclusion_patterns', {})
EXISTING_CLIENTS = set(client.get('existing_clients', []))
SCORING = client.get('scoring', {})
```

Current client: **{client_name}** — {client_description}

## Pre-Classification Filters

Apply these BEFORE the decision tree. They catch common false positives:

### 1. Minor Alterations Filter

Auto-REJECT regardless of value or sector if title or scheme_description matches:

```python
minor_patterns = EXCLUSION_PATTERNS.get('minor_alterations', [
    "relocation of entrance", "shopfront alterations", "fascia replacement",
    "signage installation", "single room refurb", "door replacement"
])

def is_minor_alteration(title, description):
    combined = f"{title} {description}".lower()
    return any(p.lower() in combined for p in minor_patterns)
```

**Exception:** If the alteration is part of a larger refurbishment with explicit lighting/energy scope, don't reject.

### 2. Floodlighting Exclusion

Auto-REJECT any project where the work is purely floodlighting or external lighting. Floodlighting is a different technology and market — very specific type of light, not CILS's scope.

```python
floodlight_patterns = EXCLUSION_PATTERNS.get('floodlighting', [
    "floodlight", "floodlighting", "flood light", "flood lighting",
    "external lighting conversion", "LED floodlight conversion"
])

def is_floodlight_only(title, description):
    combined = f"{title} {description}".lower()
    has_floodlight = any(p.lower() in combined for p in floodlight_patterns)
    if not has_floodlight:
        return False
    # Check if there's also indoor scope — mixed projects stay alive
    indoor_signals = ['gym', 'wellness', 'hotel', 'office', 'retail', 'restaurant',
                      'reception', 'fit-out', 'fitout', 'refurbishment', 'conversion to']
    has_indoor = any(s in combined for s in indoor_signals)
    return has_floodlight and not has_indoor  # REJECT only if pure floodlight
```

**Key rule:** If a project mixes indoor construction with outdoor floodlighting, the indoor element keeps it alive. Pure floodlight = REJECTED.

### 3. Mobile Units / Caravans Exclusion

Auto-REJECT anything involving caravans, mobile homes, or mobile units. These are not construction projects.

```python
mobile_patterns = EXCLUSION_PATTERNS.get('mobile_units', [
    "caravan", "static caravan", "mobile home", "mobile unit",
    "portable cabin", "modular unit"
])

def is_mobile_unit(title, description):
    combined = f"{title} {description}".lower()
    return any(p.lower() in combined for p in mobile_patterns)
```

### 4. Change of Use Filter

Change of use is NOT an automatic rejection. Apply judgment:

- **REJECT** if: no building work described, facade-only changes, caravans/mobile units
- **KEEP** if: real interior fit-out, hotel/gym/leisure conversion with construction, industrial-to-leisure conversion

```python
def assess_change_of_use(title, description):
    combined = f"{title} {description}".lower()
    if 'change of use' not in combined:
        return None  # not a change-of-use project, skip this filter

    # Auto-reject signals
    reject_signals = ['caravan', 'mobile home', 'mobile unit', 'facade only',
                      'no building work', 'designation change']
    if any(s in combined for s in reject_signals):
        return 'REJECTED'

    # Keep signals — real construction
    keep_signals = ['fit-out', 'fitout', 'conversion', 'refurbishment', 'gym',
                    'hotel', 'wellness', 'leisure', 'restaurant', 'office',
                    'window replacement', 'structural', 'industrial']
    if any(s in combined for s in keep_signals):
        return 'KEEP'

    # Ambiguous — investigate further
    return 'MAYBE'
```

**Industrial-to-leisure conversions are explicitly IN.** Converting a disused factory to a gym requires full fit-out including lighting. The "change of use" label does not disqualify these.

### 5. Sports Outdoor Exclusion

Auto-REJECT outdoor sports projects where the work is purely external:

```python
sports_patterns = EXCLUSION_PATTERNS.get('sports_outdoor', [
    "golf course external works", "cricket pitch",
    "athletics track", "single sports pitch"
])
```

**Exception:** Golf driving ranges are in scope. Mixed projects (indoor + outdoor) stay alive — the indoor element keeps them in.

### 6. Timing Filter

If start date is <3 months away AND no explicit lighting/energy scope mentioned → REJECT or deduct 20 points. Rationale: contractor already selected, too late to influence specification.

```python
from datetime import datetime, timedelta

def check_timing_risk(start_date_str, description):
    if not start_date_str:
        return False  # unknown = no penalty
    start = datetime.strptime(start_date_str, '%Y-%m-%d')
    months_away = (start - datetime.utcnow()).days / 30
    if months_away < 3:
        # Check for explicit scope
        scope_keywords = ['lighting', 'led', 'luminaire', 'solar', 'energy', 'bms']
        has_scope = any(kw in (description or '').lower() for kw in scope_keywords)
        return not has_scope  # True = timing risk
    return False
```

### 7. Small Project Filter

Projects below `small_project_cutoff` (default £250k) require EXPLICIT lighting/energy scope in the title or scheme_description to qualify. Without it → REJECT.

## Decision Tree

After pre-filters pass:

```
IF any sector matches EXCLUDED list → REJECTED
ELIF value_basis = 'Guideline' AND value_numeric < MAYBE_MIN → REJECTED (placeholder value)
ELIF is_minor_alteration(title, description) → REJECTED
ELIF is_sports_outdoor(title, description) → REJECTED
ELIF any sector matches STRONG list AND value_numeric >= QUALIFIED_MIN → QUALIFIED
ELIF any sector matches GOOD list AND value_numeric >= QUALIFIED_MIN → QUALIFIED
ELIF any sector matches STRONG list AND value_numeric < QUALIFIED_MIN → MAYBE (good fit, small)
ELIF value_numeric >= BIG_UNKNOWN_MIN AND sector is UNKNOWN → MAYBE (big enough to investigate)
ELIF existing_client_match(roles) → MAYBE (existing relationship, always worth a look)
ELSE → REJECTED
```

### Existing Client Boost

If any company in `project_roles` matches the `existing_clients` list, boost:
- Add +20 to priority score
- If would otherwise be REJECTED on value alone, upgrade to MAYBE

```python
def check_existing_client(project_id):
    roles = c.execute("SELECT company_name FROM project_roles WHERE project_id = ?", (project_id,)).fetchall()
    return any(r['company_name'] in EXISTING_CLIENTS for r in roles)
```

## Classification Methods

### Method A: Local Decision Tree (default, fast)

Apply the decision tree above directly in Python. Best for large batches (20+).

### Method B: Subagent Classification (thorough, slower)

For ambiguous projects or when the user wants deeper analysis, spawn haiku subagents via the Task tool. Best for batches of 10-15.

Read `references/prompts.md` → "Classification Prompt" for the full 5-criteria template. Each subagent evaluates: scale fit, lighting relevance, sector fit, commercial viability, timing.

```
Task tool call:
  subagent_type: "general-purpose"
  model: "haiku"
  description: "Classify project {project_id}"
  prompt: [filled template from prompts.md]
```

Spawn independent subagents in parallel within a single message for speed.

**When to use Method B:** When there are fewer than 15 projects, or the user asks for "thorough classification" or "deep classify".

## Sector-to-Tier Mapping

Glenigan sector names don't always match config tier names directly:

| Glenigan Sector | Maps To | Tier |
|----------------|---------|------|
| Warehousing/Storage, Light Industrial, Distribution | Industrial | STRONG |
| Indoor Play Areas, Leisure, Sports Halls | Leisure/Sports | STRONG |
| Hospitals, Medical Centres, Healthcare | Healthcare | STRONG |
| Council, Government, Public Buildings | Public Sector | STRONG |
| Colleges, Schools, Universities | Education | GOOD |
| Office Buildings, Commercial | Commercial | GOOD |
| Shops, Retail | Retail | GOOD |
| Community Centres | Community | GOOD |
| Pubs/Wine Bars, Cafes, Restaurants | Hospitality | EXCLUDED |
| Hotels | Hospitality | STRONG |
| Kindergartens/Nurseries | Education | GOOD |

When the sector name is ambiguous, classify based on scheme_description.

## Confidence Score

The classification confidence (0.0-1.0):
- 0.9+ → sector exactly matches, value is high, description confirms
- 0.7-0.9 → sector matches but value is borderline, or description is ambiguous
- 0.5-0.7 → inferred from description keywords, no clear sector match
- < 0.5 → guesswork based on title alone

## Reasoning

One sentence explaining the classification. Examples:
- "Retail warehouse development with Guideline £13K value — excluded on value."
- "£3.9M industrial/warehouse in West Midlands — strong logistics vertical."
- "Minor shopfront alteration — rejected as minor works."
- "£500K office refurb starting in 2 months with no lighting scope — timing risk, rejected."

## Scoring (for prioritization)

After classification, calculate a preliminary priority score for QUALIFIED and MAYBE projects:

| Factor | Logic | Points |
|--------|-------|--------|
| Start Date | 0-1mo: 30, 1-3mo: 27, 3-6mo: 21, 6-12mo: 15, 12-18mo: 12, 18+mo: 9, unknown: 15 | 0-30 |
| Vertical | STRONG: +25, GOOD: +10, EXCLUDED: n/a | 0-25 |
| Value | 5 points per £100k (capped at 50) | 0-50 |
| Existing Client | Match in client list: +20 | 0-20 |

Store in `enrichment_scoring` after all passes complete. The score gets updated as enrichment progresses (second_pass_status adds/subtracts points).

## Batch Processing

```python
import sqlite3, json
from datetime import datetime

db_path = os.path.join(workspace_folder, 'glenigan.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Find unclassified projects
unclassified = c.execute("""
    SELECT p.project_id, p.title, p.scheme_description, p.value_numeric,
           p.value_basis, p.development_type, p.region, p.start_date,
           GROUP_CONCAT(s.sector_name, '|') as sectors
    FROM projects p
    LEFT JOIN sectors s ON p.project_id = s.project_id
    WHERE p.project_id NOT IN (SELECT project_id FROM enrichment_classification)
    GROUP BY p.project_id
    ORDER BY p.value_numeric DESC
""").fetchall()

BATCH_SIZE = 20
batch = unclassified[:BATCH_SIZE]
```

Present to user as a table:

```
| # | ID | Title | Value | Sectors | Status | Vertical | Confidence | Reasoning |
```

**Ask user to confirm before writing.** Then INSERT:

```python
now = datetime.utcnow().isoformat() + 'Z'
for result in confirmed_results:
    c.execute("""
        INSERT INTO enrichment_classification
        (project_id, status, vertical, reasoning, confidence, enriched_at, enriched_by)
        VALUES (?, ?, ?, ?, ?, ?, 'classify-opportunities')
    """, (result['project_id'], result['status'], result['vertical'],
          result['reasoning'], result['confidence'], now))

    c.execute("""
        INSERT INTO processing_log (project_id, stage, timestamp, skill, notes)
        VALUES (?, 'classified', ?, 'classify-opportunities', ?)
    """, (result['project_id'], now, f"{result['status']} ({result['vertical']})"))

conn.commit()
```

## User Interaction Flow

1. Report: "{n} unclassified projects found. Processing batch of {batch_size}..."
2. Show classification table for the batch
3. Ask: "Approve these {batch_size} classifications? (y/n/edit)"
4. If approved, write to DB
5. Report: "{n} classified. {remaining} remaining."

## Region-Filtered Classification

User can say "classify London projects" or "classify West Midlands":

```python
unclassified = c.execute("""
    SELECT ... FROM projects p
    WHERE p.region = ? AND p.project_id NOT IN (SELECT project_id FROM enrichment_classification)
    ...
""", (region.upper(),)).fetchall()
```
