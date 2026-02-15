# Instructions for Claude Code

Please make the following updates to the glenigan-plugins repository:

## 1. Update contacts.md
- File: `plugins/glenigan/references/contacts.md`
- Line: 31
- Change: `"enrichment_research"` → `"enrichment_web"`

## 2. Update plugin README.md  
- File: `plugins/glenigan/README.md`
- Changes:
  - Update header from `v2.0.0` to `v2.6.0`
  - Add a new v2.6.0 changelog entry above the existing v2.0.0 entry

## 3. Commit and Push
After making these changes:
```bash
git add .
git commit -m "Update to v2.6.0: Fix enrichment field name and update version"
git push origin main
```

## Repository Location
The repo is already at: `/Users/ggrigo/glenigan-plugins/`

If not cloned yet, run:
```bash
cd ~
git clone https://github.com/ggrigo/glenigan-plugins.git
cd glenigan-plugins
```

Then follow the instructions above.