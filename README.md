# trading-portal

BalRam's live ETF portal (QQQ, SPY, GLD) — served by GitHub Pages.

Created 2026-09-28 · Last updated 2026-09-29

## Files

- `etf-live.html` — the portal page
- `etf-live.css` — its stylesheet
- `etf-live-bundle.json` — fresh market data, rebaked server-side every 5
  minutes on weekdays 04:00–21:00 ET by `build_live_bundle.py` (in the
  `trading` repo)
- `nyse-holidays.json` — the NYSE full-day closure list the page uses for
  session labels; assembled at deploy time from the cross-thread repo (see
  below), never fetched by visitors from GitHub

The page never fetches market data over the network: fresh data is baked
into the page and the sibling JSON by the bundler. It loads the holiday file
from the same deployed origin before first paint.

## Branches

- `main` — the source of truth: page source, styles, tests, deploy script.
- `gh-pages` — the generated, deployed branch: page source from `main` plus
  the assembled `etf-live-bundle.json` and `nyse-holidays.json`. Regenerated
  on every deploy; never edited by hand.

## Holiday data flow

The page's session labels depend on the NYSE holiday list. The canonical
list is maintained quarterly by the `holiday-list-update` job and mirrored
to `holidays/nyse_holidays.json` in
`technology-consults/cross-thread-task-status-tracker`. Deployments assemble
the portal's `nyse-holidays.json` from that git copy — never from a web
search, and never fetched live by the page from GitHub.

## Deploying

`scripts/deploy_portal.py` builds the deployable and pushes the `gh-pages`
branch. Deploy policy: the portal's own files are hard requirements (any
read/write failure aborts the deploy); the holiday JSON is best-effort —
if it cannot be fetched or fails validation (structure + freshness), the
previously deployed copy is carried forward untouched and the deploy
continues with a warning, so a dead holiday pipeline never blocks shipping
a page fix. `docs/` is excluded from the served branch. `tests/` holds the
portal regression suite, which must pass before any deploy (holiday-data
checks are advisory warnings; only portal-file checks can fail the gate).

Releases are tagged on `main` with semver (e.g. `v1.0.0`) before deploying,
so the tag always identifies the exact deployed source commit. Every deploy
prepares a backout package; the policy is fix-forward, rollback only as a
last resort.
