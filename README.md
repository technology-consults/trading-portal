# trading-portal

BalRam's live ETF portal (QQQ, SPY, GLD) —
served by GitHub Pages.

## Files
- `etf-live.html` — the portal page
- `etf-live.css` — its stylesheet
- `etf-live-bundle.json` — fresh market data, rebaked server-side every 5 minutes on weekdays by `build_live_bundle.py`

The page never fetches market data over the network: fresh data is baked into the page and the sibling JSON by the bundler.
