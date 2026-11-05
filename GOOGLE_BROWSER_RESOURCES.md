# Google website resources and browser diagnostics

Implementation checkpoint: 2026-11-04. No Google Cloud API activation, billing
change, sign-in, deployment, profile replacement or shared Codex configuration
change was performed.

Follow-up 2026-11-05: companion 0.1.2 remembers workspace/session UI preferences,
detects the active room only when the user explicitly selects a tab, and returns
fixed diagnostic messages for stale rooms, unavailable scopes and competing
connections. An idle profile cannot displace the selected connection. Latest
checks: 39 focused Python tests, 19 isolated browser checks with zero axe
violations, and a previous 550-test full suite with zero failures/errors/skips.
The backend corrections are deployed. Live local-page read and user-approved
fill subsequently completed, independently confirmed in Chrome and recorded as
one execution claim and one completion. No room ID needs manual entry.

## Local resources

Downloads are in the operator-selected Documents/FullCircle/resources/google
directory. `resource-manifest.json` records nonzero sizes, original source URLs,
versions and SHA-256 hashes. These are local integrity hashes, not claims of
publisher-signature validation. Scripts preserve existing unverified files.

- WebP 1.6.0 Windows x64 utilities, extracted for local photo optimization.
  [Google download page](https://developers.google.com/speed/webp/download).
- Chrome for Testing 157.0.8103.38 Windows x64, pinned to the Stable metadata
  returned during download. Use its separate test profile, not account browsing.
  [Google explanation](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing).
- DevTools troubleshooting skill, troubleshooting reference and Apache license
  from revision `af2834411a564d366f9cab63efb046d9084f4dba`. These are reference
  files, not automatically installed instructions or permission to weaken policy.
  [Upstream source](https://github.com/ChromeDevTools/chrome-devtools-mcp).

Reuse the installed Playwright, axe, Lighthouse, Prettier and SVGO packages. The
installed DevTools MCP 1.12.0 completed a real stdio initialization, listed 32
tools and successfully called `list_pages` against isolated Chrome for Testing.
Usage statistics, CrUX integration and update checks were disabled for that
test. This does not configure or repair the current client's browser host.

## What the Chrome evidence establishes

- The issue log records extension/profile and origin-authorization failures on
  November 2, then verified dedicated-browser startup/CDP connectivity on
  November 3. The original origin denial's cause was not established.
- During this task, the client reported its browser host unavailable. Native
  URL inspection eventually worked; input geometry and screenshot capture failed.
- The existing repository CDP bridge subsequently returned `connected: true`.
  These are distinct transports. A working bridge does not prove that the
  client's browser host is healthy.
- Isolated Chrome for Testing and the installed DevTools MCP both worked in
  bounded checks. This narrows diagnosis but does not establish an external
  host regression's cause or exact onset.

`scripts/browser_diagnostics.py` collects bounded status and relevant Git history
without reading profiles, cookies, transcripts or account content. Its JSON
report remains local in the resource folder. Dates/commits are correlation, not
proof of causation. Historical revision tests must use isolated checkouts rather
than alter an active checkout or another agent's work.

The companion prototype and installation boundary are documented in
[chrome_extension/README.md](chrome_extension/README.md). After explicit user approval,
the per-user native host was registered and Veridex restarted. Live health and
all six browser tools were verified; unauthenticated relay requests return 401.
On November 5 the operator reported it loaded, and the production native
connection returned `connected`. Follow-up native-host process ancestry showed
that installation was in the other Chrome profile; the dedicated browser had no
companion target. Correct-profile loading is required before acceptance.
Explicit tab selection, local-page read and one approved fill on
`/browser_companion_check.html` are now verified. The fixture submitted nothing.
Other live navigation/click and real-account operations remain separate acceptance
work; they are not inferred from this local check.

## Later shortlist

| Resource | Useful for | Current decision |
| --- | --- | --- |
| Google Fonts / Material Symbols | Website typography and a small consistent icon set | Select during branding; retain each downloaded license and self-host selected assets. [Fonts](https://fonts.google.com/), [Symbols](https://developers.google.com/fonts/docs/material_symbols) |
| Antigravity | Optional code/diff review and a second diagnostic perspective | Free individual tier has usage limits; account access and terms remain unverified. No installation, source upload or provider change. [Plans](https://www.antigravity.google/pricing) |
| DevTools AI assistance | Explain inspected styling, requests, sources and performance | Review data-sharing and eligibility before enabling; it is not historical Git analysis. [Documentation](https://developer.chrome.com/docs/devtools/ai-assistance/get-started) |
| Cloud SDK | Manage an actual Google Cloud deployment | Defer while the website uses existing IONOS hosting. [SDK](https://cloud.google.com/sdk) |
| Cloud Logging / Error Reporting | Group timestamped errors from instrumented services | Defer until telemetry, privacy and costs are designed. It cannot retrospectively inspect uncaptured local Chrome failures. [Error Reporting](https://docs.cloud.google.com/error-reporting/docs/grouping-errors) |

Cloud Free Tier requires a billing account and has usage limits. A $0 dashboard
estimate is not proof that future usage will remain free. No Cloud services were
enabled for this work. [Free-program conditions](https://docs.cloud.google.com/free/docs/free-cloud-features)

## Repeatable checks

Use the active Sol/high route for diagnosis. Existing bounded checks:

```powershell
.\.venv\Scripts\python.exe -m unittest test_browser_extension test_veridex_mcp -v
.\.venv\Scripts\python.exe -m unittest discover -v
```

The standalone `scripts/test_browser_extension.mjs` takes explicit `--chrome`,
`--toolkit` and `--output` paths; use a new ignored `output/playwright/...`
directory for every run. `scripts/check_devtools_transport.py` takes the same
Chrome and toolkit paths and performs no global MCP configuration changes.
