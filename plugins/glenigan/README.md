# Glenigan v2.6.0

Lead qualification pipeline for Glenigan construction project data. Built by Baresquare.

## What It Does

Import Glenigan PDF exports, then process projects one at a time: classify for client fit, extract Idox keyvals from UK council portals via Playwright, enrich with web research and document analysis, profile architect contacts, map consultant competitors, score and rank leads, and manage deals in a built-in CRM.

## Architecture

One loop. One project at a time. All the way through. Then next.

```
Upload PDF → /gleni-loop
  FOR EACH project:
    Classify → Portal → Research → Download → Analyze → Contacts → Score → CRM
    → Next project
```

Three-tier SQLite schema: Core (immutable PDF data) | Enrichment (progressive) | Operational (CRM, processing log).

## Commands

| Command | Description |
|---------|-------------|
| `/gleni-init` | Create database, seed portal registry, migrate schema |
| `/gleni-loop` | The workhorse. Process projects one-by-one through all passes. |
| `/gleni-pipeline` | Query and view the project pipeline |
| `/gleni-crm` | Manage CRM deals, activities, follow-ups |

### /gleni-loop usage

```
/gleni-loop                              # Process all, start where we left off
/gleni-loop 26065152                     # Just this project, all steps
/gleni-loop --step portal                # Portal lookup for next project that needs it
/gleni-loop --step classify --region LONDON  # Classify next London project
```

## Skills

| Skill | Description |
|-------|-------------|
| `gleni-ingest` | Parse Glenigan multi-project PDFs into SQLite |
| `gleni-dedup` | Detect and merge duplicate projects (confidence scoring) |

## Reference Docs

All domain knowledge lives in `references/`. The loop command reads them as needed.

| File | Contents |
|------|----------|
| `references/classification.md` | Decision tree, pre-filters, scoring rules |
| `references/portals.md` | Portal registry (96+ UK authorities), search patterns, extraction strategies, ref normalizer |
| `references/documents.md` | Download methods, analysis patterns, document priority |
| `references/contacts.md` | Architect profiling, consultant competitive analysis |
| `references/prompts.md` | Subagent prompt templates |
| `references/nudge.md` | Next-best-action logic |
| `references/schema.md` | Full database schema reference |

## Playbook + Rules

Two config files, two purposes:

- **`config/playbook.md`** — The client's own words. Human voice, human reasoning. The agent reads this for judgment calls and context. Source of truth. When playbook and rules disagree, the playbook wins.
- **`config/rules.json`** — Machine-readable rules compiled from the playbook. Sector tiers, value thresholds, exclusion patterns. Code reads this for execution.

Currently configured for **CILS** (Commercial & Industrial Lighting Solutions). Switch clients by replacing both files.

## Quick Start

1. Install plugin
2. `/gleni-init`
3. Upload a Glenigan PDF
4. `/gleni-loop`
5. Come back in a few hours

## Version History

**v2.6.0** (February 2026) — Production Release
- Fixed enrichment_web table reference in contacts profiling
- Stabilized pipeline for production use
- Enhanced error handling and retry logic
- Improved portal extraction reliability

**v2.0.0** (February 2026) — Consolidation
- 9 skills + 5 commands → 2 skills + 4 commands + 7 reference docs
- New `/gleni-loop` command: state machine per project, runs unattended
- Removed enrich-project orchestrator (loop replaces it)
- Merged download-documents + analyze-documents into references/documents.md
- Merged extract-keyval + batch-extract into references/portals.md
- Demoted pipeline-nudge to references/nudge.md
- Renamed all skills/commands to gleni- prefix

**v1.1.0** (February 2026) — Previous release
- 8 skills, 5 commands, complete enrichment pipeline

## Author

Baresquare
