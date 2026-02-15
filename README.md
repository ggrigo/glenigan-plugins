# Glenigan Plugins Marketplace

Claude plugin marketplace for Glenigan construction lead qualification tools by Baresquare.

## Available Plugins

### glenigan v2.6.0
Lead qualification pipeline for Glenigan construction data. 

**Features:**
- Import and parse Glenigan PDF exports
- Deduplicate leads based on configurable rules
- Classify leads by project type and relevance
- Extract Idox planning portal key values
- Enrich with web research and contact profiling
- Score and prioritize leads
- CRM integration and export

## Installation

### In Claude Cowork or Claude Code:

```bash
# Add the marketplace
/plugin marketplace add ggrigo/glenigan-plugins

# Install the plugin
/plugin install glenigan@ggrigo-glenigan
```

For private repos, authenticate first:
```bash
gh auth login
```

## Usage

After installation, the following commands are available:

- `/gleni-init` - Initialize database and import PDF data
- `/gleni-loop` - Run the complete pipeline
- `/gleni-pipeline` - Run individual pipeline stages
- `/gleni-crm` - Manage CRM operations

## Requirements

- Glenigan PDF export file
- Playwright MCP server (for portal extraction)
- SQLite database (created automatically)

## Configuration

The plugin includes default configuration for CILS. To customize for your client:

1. Edit `config/playbook.md` with your client's requirements
2. Update `config/rules.json` with your scoring rules

## Support

For issues or questions, contact Baresquare.

## License

Proprietary - Baresquare Ltd.