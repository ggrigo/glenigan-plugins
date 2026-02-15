# Portal Intelligence Reference

All portal lookup and keyval extraction logic. Used by /gleni-loop for Pass 2.

## Why Playwright MCP

Benchmark results from live testing (February 2026):

| Method | Tool Calls | Success Rate | Notes |
|--------|-----------|-------------|-------|
| JS fetch() in browser | 1 | ~25% | Cloudflare blocks search POST endpoints |
| Playwright MCP | 4 | 90%+ | navigate → fill → click → evaluate |
| Chrome MCP step-by-step | 8 | 90%+ | Double the calls, screenshot/a11y overhead |
| Chrome MCP hybrid | 4 | 90%+ | Needs explicit waits, output blocking issues |

**Use Playwright MCP as the primary extraction method.** Fall back to Chrome MCP only for portals requiring visual interaction (CAPTCHAs).

## Extraction Sequence

### 1. Navigate to Advanced Search

```
{portal_url}/search.do?action=advanced
```

Use `playwright_navigate`. If the page shows a Cloudflare challenge, wait 5 seconds and retry. The Playwright browser handles JS challenges automatically.

### 2. Detect Search Field Pattern

Idox portals use different field names. Detect the pattern from the form HTML using `playwright_get_visible_html` with `selector: "form"`, `cleanHtml: true`.

Check for these field names in priority order:
1. `searchCriteria.reference` (25% of portals: Brighton, Bristol, Southwark, Westminster)
2. `caseReference` (35% of portals: Oxford, Southampton, Leeds, Manchester)
3. `searchCriteria.simpleSearchString` (fallback)
4. `applicationReference` (rare)

### 3. Fill and Submit

Use `playwright_fill` with the detected selector:
```
selector: input[name="searchCriteria.reference"]
value: {planning_ref}
```

Submit with `playwright_click`:
```
selector: input[type="submit"][value*="Search"]
```

Playwright automatically waits for navigation after click.

### 4. Extract Keyval

Use `playwright_evaluate` to extract the keyval from result links:

```javascript
const el = document.querySelector('a[href*="activeTab=summary"]');
el ? el.getAttribute('href').match(/Val=([A-Z0-9]+)/)[1] : null;
```

Alternative extraction points if primary fails:
- URL bar (single-result auto-redirect): `window.location.href.match(/keyVal=([A-Z0-9]+)/)`
- Any link containing `applicationDetails`: `document.querySelector('a[href*="applicationDetails"]')`
- Onclick handlers: `document.querySelector('a[onclick*="keyVal"]')`

### 5. Construct Direct Access URL

Once keyval is obtained, construct direct URLs:
```
Documents: {portal_url}/applicationDetails.do?keyVal={keyval}&activeTab=documents
Summary:   {portal_url}/applicationDetails.do?keyVal={keyval}&activeTab=summary
Contacts:  {portal_url}/applicationDetails.do?keyVal={keyval}&activeTab=contacts
```

## Keyval Properties

- **Format**: 10-14 alphanumeric characters, uppercase
- **Permanent**: Never changes once assigned
- **Cache forever**: Safe to cache with no expiry
- **Case sensitive**: Preserve exact case

## Rate Limiting

- Wait 2 seconds between searches on the same portal
- Batch by authority (one browser session per authority)
- Westminster and some London boroughs need 3-5 second delays
- If rate limited (429 or timeout), back off exponentially: 2s, 5s, 10s

## Error Recovery

If extraction fails (no keyval obtained):
1. Screenshot the page to diagnose (Cloudflare? Login wall? Error page?)
2. Try navigating to simple search instead: `search.do?action=simple`
3. Try alternative field patterns
4. If portal errored → mark as PORTAL_MAINTENANCE (retry later)
5. If search returned nothing → mark as UNMAPPABLE and move to next ref

## Search Field Detection Patterns

### Pattern 1: searchCriteria.reference (25% of portals)

**Detection**: Check for `input[name="searchCriteria.reference"]`

```javascript
// Playwright evaluate
document.querySelector('input[name="searchCriteria.reference"]') !== null
```

**Fill selector**: `input[name="searchCriteria.reference"]`

**Found in**: Brighton, Bristol, Southwark, Westminster, Tower Hamlets, Cornwall, Gloucestershire, Medway

**Submit button**: `input[type="submit"][value="Search"]` or `input[type="submit"][value*="Search"]`

### Pattern 2: caseReference (35% of portals)

**Detection**: Check for `input[name="caseReference"]`

```javascript
document.querySelector('input[name="caseReference"]') !== null
```

**Fill selector**: `input[name="caseReference"]`

**Found in**: Oxford, Southampton, Leeds, Manchester

**Submit button**: Same as Pattern 1

### Pattern 3: simpleSearchString (15% of portals)

**Detection**: Check for `input[name="searchCriteria.simpleSearchString"]`

```javascript
document.querySelector('input[name="searchCriteria.simpleSearchString"]') !== null
```

**Fill selector**: `input[name="searchCriteria.simpleSearchString"]`

**Notes**: Used on simple search pages. Navigate to `search.do?action=simple` instead of advanced.

### Pattern 4: applicationReference (5% of portals)

**Detection**: Check for `input[name="applicationReference"]`

**Fill selector**: `input[name="applicationReference"]`

**Notes**: Rare, found in some newer Idox installations.

### Universal Detection Script

Run this via `playwright_evaluate` to detect the pattern automatically:

```javascript
const patterns = [
  { name: 'searchCriteria.reference', selector: 'input[name="searchCriteria.reference"]' },
  { name: 'searchCriteria.simpleSearchString', selector: 'input[name="searchCriteria.simpleSearchString"]' },
  { name: 'caseReference', selector: 'input[name="caseReference"]' },
  { name: 'applicationReference', selector: 'input[name="applicationReference"]' }
];

const detected = patterns.find(p => document.querySelector(p.selector));
detected ? JSON.stringify(detected) : 'NO_PATTERN_FOUND';
```

### Form Submission Patterns

#### Standard Submit Button
```
selector: input[type="submit"][value*="Search"]
```

#### Alternative Submit
Some portals use a button element instead:
```
selector: button[type="submit"]
```

#### CSRF Tokens
Most Idox forms include a hidden `_csrf` field. Playwright handles this automatically since it uses the real browser session. No need to extract or pass the token manually.

### Post-Search Behaviour

#### Single Result
Some portals auto-redirect to the application detail page when only one result is found. In this case, the keyval is in the URL:
```javascript
window.location.href.match(/keyVal=([A-Z0-9]+)/)
```

#### Multiple Results
Results are shown in a table. Extract the keyval from the first result link:
```javascript
document.querySelector('a[href*="activeTab=summary"]').getAttribute('href').match(/Val=([A-Z0-9]+)/)[1]
```

#### No Results
The page shows "No results found" or similar. Check:
```javascript
document.body.textContent.includes('No results found') ||
document.body.textContent.includes('0 results')
```

## Extraction Strategies

### Strategy 1: Playwright Advanced Search (Primary)

1. Navigate to `{portal_url}/search.do?action=advanced`
2. Detect field pattern
3. Fill reference and submit
4. Extract keyval from result links

**Expected**: 4 Playwright tool calls. ~5 seconds per keyval.

### Strategy 2: Playwright Simple Search (Fallback)

If advanced search fails (form not found, different layout):

1. Navigate to `{portal_url}/search.do?action=simple`
2. Look for `searchCriteria.simpleSearchString`
3. Fill and submit
4. Extract keyval

**When to use**: When advanced search page returns an error or has no reference field.

### Strategy 3: Direct URL Probe

Some portals accept planning refs directly in the URL:

```
{portal_url}/simpleSearchResults.do?action=firstPage&searchType=Application&searchCriteria.reference={ref}
```

Use `playwright_navigate` directly. If the page loads with results, extract the keyval.

**When to use**: When form-based approaches fail repeatedly.

### Strategy 4: Chrome MCP (Last Resort)

Use Chrome MCP browser tools when Playwright fails:
- Portals requiring CAPTCHA solving (user interaction needed)
- Portals with JavaScript-heavy dynamic forms
- Sessions that require cookie acceptance dialogs

## Error Diagnosis

### Cloudflare Challenge
**Symptom**: Page shows "Checking your browser" or "Just a moment"
**Solution**: Wait 5-10 seconds. Playwright handles JS challenges. If persistent, the portal may be blocking automated browsers entirely.

### 403 Forbidden
**Symptom**: HTTP 403 response
**Solution**: This is expected for direct HTTP. Playwright bypasses this via real browser context. If Playwright also gets 403, the portal is blocking aggressively.

### Session Expired / 500 Error
**Symptom**: Server error after form submission
**Solution**: Close browser, open fresh session. Navigate to homepage first, then to search.

### No Results Found
**Symptom**: Valid planning ref returns zero results
**Possible causes**:
- Wrong authority (ref belongs to different council)
- Ref format mismatch (some portals need slashes, some don't)
- Application not yet on portal (recent submissions)

### Rate Limited
**Symptom**: 429 status or connections timing out
**Solution**: Exponential backoff. 2s → 5s → 10s → 30s. Switch to different authority if processing a batch.

### Keyval Validation

After extraction, validate the keyval:
- Must be 10-14 uppercase alphanumeric characters
- Must match pattern: `/^[A-Z0-9]{10,14}$/`
- Test by constructing a direct URL and checking it returns 200

```javascript
// Quick validation via Playwright
const testUrl = `${portalUrl}/applicationDetails.do?keyVal=${keyval}&activeTab=summary`;
// Navigate and check title contains the planning ref
```

### Batch Optimization

#### Group by Authority
Process all refs for one authority before switching. This:
- Maintains browser session and cookies
- Avoids re-navigating to search page from scratch
- Reduces Cloudflare challenges (session is established)

#### Navigate Back After Each Search
After extracting a keyval, navigate back to the search page:
```
playwright_navigate: {portal_url}/search.do?action=advanced
```

This is faster than re-establishing the session.

#### Delay Between Searches
- Standard portals: 2 seconds
- Westminster / rate-limited portals: 3-5 seconds
- After an error: 5-10 seconds

#### Browser Session Management
- Keep one Playwright browser open for the entire batch
- Close and reopen only if errors accumulate (3+ consecutive failures)
- Use `playwright_close` at the end of the batch

## Reference Format Normalizer

Planning references vary across authorities. Some portals reject refs with slashes, others require them. Some expect zero-padded numbers, others don't. This normalizer generates variant formats to maximize search success.

### generateRefVariants()

```javascript
function generateRefVariants(ref) {
  const variants = [ref];

  // 1. Missing slash: "250176" → "25/0176"
  if (/^\d{6,}$/.test(ref)) {
    variants.push(ref.slice(0, 2) + '/' + ref.slice(2));
    // Also try with 4-digit year prefix
    if (ref.length >= 8) variants.push(ref.slice(0, 4) + '/' + ref.slice(4));
  }

  // 2. Authority prefix strip: "25/AP/0176" → "AP/0176"
  if (/^\d{2}\/[A-Z]+\//.test(ref)) {
    variants.push(ref.replace(/^\d{2}\//, ''));
  }

  // 3. Zero-padding: "25/176" → "25/0176"
  const parts = ref.split('/');
  if (parts.length >= 2) {
    const last = parts[parts.length - 1];
    if (/^\d+$/.test(last) && last.length < 4) {
      const padded = [...parts];
      padded[padded.length - 1] = last.padStart(4, '0');
      variants.push(padded.join('/'));
    }
    // Also try 5-digit padding (some authorities)
    if (/^\d+$/.test(last) && last.length < 5) {
      const padded5 = [...parts];
      padded5[padded5.length - 1] = last.padStart(5, '0');
      variants.push(padded5.join('/'));
    }
  }

  // 4. Slash variants: "25/AP/0176" → "25-AP-0176"
  if (ref.includes('/')) {
    variants.push(ref.replace(/\//g, '-'));
    variants.push(ref.replace(/\//g, '')); // no separator
  }

  // 5. Hyphen to slash: "BH2026-00020" → "BH2026/00020"
  if (ref.includes('-') && !ref.includes('/')) {
    variants.push(ref.replace(/-/g, '/'));
  }

  // 6. Year prefix normalization: "2025/0176" → "25/0176"
  if (/^20\d{2}\//.test(ref)) {
    variants.push(ref.replace(/^20(\d{2})/, '$1'));
  }
  // Reverse: "25/0176" → "2025/0176"
  if (/^\d{2}\//.test(ref) && !ref.startsWith('20')) {
    variants.push('20' + ref);
  }

  return [...new Set(variants)];
}
```

### Known Format Patterns by Authority

| Authority | Typical Format | Example | Notes |
|-----------|---------------|---------|-------|
| Southwark | `YY/AP/NNNN` | `26/AP/0176` | Year + area prefix + 4-digit |
| Brighton & Hove | `BHYYYY/NNNNN` | `BH2026/00020` | BH prefix + full year |
| Bristol | `YY/NNNNN/X` | `26/00123/F` | Year + 5-digit + suffix letter |
| Oxford | `YY/NNNNN/FUL` | `25/02345/FUL` | Year + 5-digit + app type |
| Westminster | `YY/NNNNN` | `26/01234` | Year + 5-digit |
| Brent | `YY/NNNN` | `25/3508` | Year + 4-digit, no padding |
| Barnet | `YY/NNNN/FUL` | `25/1234/FUL` | Year + 4-digit + suffix |

### Usage in Extraction

Before submitting a search:

1. Call `generateRefVariants(ref)` to get all plausible formats
2. Try the original ref first
3. If no results, try variants in order
4. Stop at first successful match
5. Log which variant worked — this helps future extractions at the same authority

### Common Failure Modes

- **Silent miss**: Portal accepts the search but returns 0 results because the format didn't match. The page looks normal, just empty.
- **Brent DCAPR keyvals**: Discovered in v0.2.0 — Brent uses `DCAPR_175962` format keyvals with underscores. The old regex `/[A-Z0-9]{10,14}/` missed these entirely. Now using `/[A-Za-z0-9_]{6,20}/`.

## Portal URL Verifier

When a mapped portal URL fails (404, timeout, redirect to non-portal page), try common alternative URL patterns before marking the portal as dead.

### URL Pattern Cascade

For a given authority slug (e.g., `ealing`), try these patterns in order:

```
1. https://planning.{slug}.gov.uk/online-applications
2. https://publicaccess.{slug}.gov.uk/online-applications
3. https://pa.{slug}.gov.uk/online-applications
4. https://pam.{slug}.gov.uk/online-applications
5. https://{slug}.planning-register.co.uk/online-applications
6. https://planning.{slug}.gov.uk/publicaccess
7. https://publicaccess.{slug}.gov.uk/publicaccess
8. https://pa.{slug}.gov.uk/publicaccess
```

### Verification Steps

For each candidate URL:

1. **Navigate** using `playwright_navigate` with a 10-second timeout
2. **Check for redirect** — if the final URL differs from the navigated URL, follow it. Some councils redirect `planning.council.gov.uk` to `publicaccess.council.gov.uk` or a completely different domain.
3. **Health check** — run the pre-flight health check from SKILL.md
4. **Look for Idox markers** — search page HTML for:
   - `idox` or `Idox` in page source
   - `search.do?action=` in any link
   - `publicaccess` or `online-applications` in the URL path
   - Footer text containing "Idox" or "IDOX Software"
5. **If valid**: Update `portal_registry` with new URL, mark connectivity = 'connected'
6. **If all patterns fail**: Mark as `PORTAL_DEAD`

### Dead vs Temporary Classification

- **PORTAL_DEAD (permanent)**: All URL patterns exhausted, no Idox markers found. Likely migrated to non-Idox system (Arcus, NEC, custom).
- **PORTAL_MAINTENANCE (temporary)**: Portal responded but showed maintenance page. Will likely come back. Retry next session.
- **CLOUDFLARE_BLOCKED (temporary)**: Portal exists but Cloudflare is blocking automated access. May work later or from different IP.
- **PORTAL_MOVED (fixable)**: Redirect detected to a new URL. Update registry and retry.

### Implementation via playwright_evaluate

```javascript
async function verifyPortalUrl(slug) {
  const patterns = [
    `https://planning.${slug}.gov.uk/online-applications`,
    `https://publicaccess.${slug}.gov.uk/online-applications`,
    `https://pa.${slug}.gov.uk/online-applications`,
    `https://pam.${slug}.gov.uk/online-applications`,
    `https://${slug}.planning-register.co.uk/online-applications`,
    `https://planning.${slug}.gov.uk/publicaccess`,
    `https://publicaccess.${slug}.gov.uk/publicaccess`,
    `https://pa.${slug}.gov.uk/publicaccess`
  ];

  for (const url of patterns) {
    try {
      const resp = await fetch(url, { method: 'HEAD', redirect: 'follow' });
      if (resp.ok) {
        return { url: resp.url, status: 'FOUND', originalPattern: url };
      }
    } catch (e) {
      continue;
    }
  }
  return { url: null, status: 'PORTAL_DEAD' };
}
```

Note: This fetch-based approach runs from the Playwright page context so it benefits from any established Cloudflare clearance. For authorities not following standard patterns (e.g., Cardiff uses `.wales` domain, Bath uses `app.bathnes.gov.uk`), manual discovery via Google search is still needed.

### Known Non-Standard URLs

| Authority | Actual URL | Why Pattern Fails |
|-----------|-----------|-------------------|
| Cardiff | `https://www.cardiffidoxcloud.wales/publicaccess` | `.wales` TLD, `idoxcloud` subdomain |
| Bath & NE Somerset | `https://app.bathnes.gov.uk/webforms/planning/` | Completely custom path |
| Caerphilly | `https://publicaccess.caerphilly.gov.uk/PublicAccess` | Capital P in path |
| Horsham | `https://public-access.horsham.gov.uk/public-access` | Hyphenated subdomain and path |

## Portal Registry

Portal URL mappings for Idox-based UK planning authorities. Verified February 2026.

### High-Success Portals (90%+ extraction rate)

| Authority | Portal URL | Pattern | Notes |
|-----------|-----------|---------|-------|
| Brighton & Hove | `https://planningapps.brighton-hove.gov.uk/online-applications` | searchCriteria | Works with HTTP + headers too |
| Bristol | `https://planningonline.bristol.gov.uk/online-applications` | searchCriteria | Cloudflare active, needs Playwright |
| Southwark | `https://planning.southwark.gov.uk/online-applications` | searchCriteria | Stable, documents often paginated |
| Cornwall | `https://planning.cornwall.gov.uk/online-applications` | searchCriteria | Standard Idox |
| Gloucestershire | `https://planning.gloucestershire.gov.uk/online-applications` | searchCriteria | Standard Idox |
| Medway | `https://publicaccess.medway.gov.uk/online-applications` | searchCriteria | Standard Idox |
| Tower Hamlets | `https://development.towerhamlets.gov.uk/online-applications` | searchCriteria | Standard Idox |
| Westminster | `https://idoxpa.westminster.gov.uk/online-applications` | searchCriteria | Aggressive rate limiting, use 3-5s delays |

### Medium-Success Portals (50-90%)

| Authority | Portal URL | Pattern | Notes |
|-----------|-----------|---------|-------|
| Oxford | `https://public.oxford.gov.uk/online-applications` | caseReference | Encoded keyvals, wait for lazy-loaded tables |
| Southampton | `https://planningpublicaccess.southampton.gov.uk/online-applications` | caseReference | Standard |
| Leeds | `https://publicaccess.leeds.gov.uk/online-applications` | caseReference | Standard |
| Swindon | `https://pa.swindon.gov.uk/publicaccess` | searchCriteria | Verified working Feb 2026 |

### Challenging Portals (<50%)

| Authority | Portal URL | System | Notes |
|-----------|-----------|--------|-------|
| Birmingham | `https://eplanning.birmingham.gov.uk/Northgate/PlanningExplorer` | Northgate | Not Idox, needs custom handler |
| Manchester | Various | Custom | Behind authentication wall |
| Ealing | `https://www.ealing.gov.uk/info/201155/planning_and_building_control` | Custom | Non-standard, redirect to third-party |

### URL Construction Patterns

#### Standard Idox

Most portals follow this pattern:
```
Base:     {portal_url}
Search:   {portal_url}/search.do?action=advanced
Results:  {portal_url}/advancedSearchResults.do?action=firstPage
Details:  {portal_url}/applicationDetails.do?keyVal={keyval}&activeTab={tab}
```

#### Common Tab Names
- `summary` — Application summary
- `details` — Further information
- `contacts` — Agent, architect, applicant
- `documents` — All planning documents
- `dates` — Important dates
- `map` — Location map
- `makeComment` — Public comments
- `relatedCases` — Linked applications

#### Non-Standard Variants

Brighton uses `searchCriteria.do` in some cases:
```
{portal_url}/searchCriteria.do?action=advanced&searchType=Application
```

Some portals use `simpleSearchResults.do` instead of `advancedSearchResults.do`.
