#!/usr/bin/env python3
"""Pre-deploy regression suite for trading-portal holiday handling.

Gate: scripts/deploy_portal.py runs this and aborts the deploy on any
failure. Covers:
  1. the canonical workspace JSON passes the SAME validation rules the
     deploy gate applies to the remote copy (structure + rolling-window
     freshness), cites the official NYSE publication, and does not contain
     the old wrong date 2027-04-02 (the 2026-09-29 page bug)
  2. etf-live.html has no hardcoded holiday dates and reads nyse-holidays.json
     same-origin at runtime — never from GitHub
  3. the page's real marketSession() logic returns the right session for a
     real holiday from the current list, a non-holiday weekday, and a weekend
     (node functional test with stubbed DOM/fetch/clock)

The holiday list is a rolling next-four-months file refreshed quarterly, so
no test may hardcode far-future dates — section 3 builds its scenarios from
the real JSON under test.

Exit 0 = all pass. Any FAIL line = do not deploy.
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(REPO, "etf-live.html")
WORKSPACE_JSON = os.path.expanduser("~/workspace/shared/holidays/nyse_holidays.json")
NYSE_URL = ("https://ir.theice.com/press/news-details/2025/"
            "NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar/"
            "default.aspx")

sys.path.insert(0, os.path.join(REPO, "scripts"))
from deploy_portal import validate_holidays  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + ": " + name
          + ("" if cond or not detail else " — " + detail))
    if not cond:
        failures.append(name)


# ---- 1. canonical workspace JSON (same rules as the deploy gate) ----
hs = None
try:
    ws_text = open(WORKSPACE_JSON).read()
except OSError as e:
    check("workspace JSON readable", False, str(e))
else:
    try:
        doc = validate_holidays(ws_text)
    except (AssertionError, ValueError) as e:
        check("workspace JSON passes canonical validation (deploy-gate rules)",
              False, str(e)[:200])
    else:
        check("workspace JSON passes canonical validation (deploy-gate rules)",
              True)
        hs = doc["holidays"]

if hs is not None:
    check("old wrong date 2027-04-02 absent", "2027-04-02" not in hs)
    check("sources cite the official NYSE publication",
          NYSE_URL in doc.get("sources", []),
          "sources=" + str(doc.get("sources")))

# ---- 2. page static checks ----
page = open(PAGE).read()
check("page has no hardcoded NYSE_HOLIDAYS set",
      "const NYSE_HOLIDAYS = new Set([" not in page)
check("page does not contain the old wrong date 2027-04-02",
      "2027-04-02" not in page)
check("page fetches nyse-holidays.json same-origin",
      'fetch("nyse-holidays.json"' in page)
check("page never fetches holiday data from GitHub at runtime",
      "api.github.com" not in page and "raw.githubusercontent.com" not in page)
check("page loads holidays before first paint",
      re.search(r"async function tick\(\)\{\s*\n\s*await loadHolidays\(\);", page)
      is not None)
check("marketSession consults the dynamic holiday set",
      "NYSE_HOLIDAYS.has(ds)" in page)

# ---- 3. node: syntax + functional test of the real page code ----
m = re.search(r'<script>\n"use strict";(.*?)\n</script>\s*$', page, re.S)
check("main script block extractable", m is not None)
if m and hs is not None:
    closed_day = hs[0]  # first real holiday in the current list
    open_day = "2026-09-29"  # a Tuesday
    if open_day in hs:
        open_day = "2026-10-06"  # fallback Tuesday
    sat_day = "2026-10-03"  # a Saturday

    def utc_args(ymd):
        y, mo, d = (int(x) for x in ymd.split("-"))
        hh = 15 if mo in (11, 12, 1, 2, 3) else 14  # 10:00 ET in EST vs EDT
        return f"Date.UTC({y}, {mo - 1}, {d}, {hh})"

    script = '"use strict";' + m.group(1)
    with open("/tmp/portal_main_script.js", "w") as f:
        f.write(script)
    r = subprocess.run(["node", "--check", "/tmp/portal_main_script.js"],
                       capture_output=True, text=True)
    check("page JS syntax valid", r.returncode == 0, r.stderr.strip()[:200])

    driver = r"""
// ---- test prelude: stub browser APIs, then run the real page script ----
let FIXED = 0; // ms epoch; driver sets per scenario
const RealDate = Date;
class StubDate extends RealDate {
  constructor(...a){ super(...(a.length ? a : [FIXED])); }
  static now(){ return FIXED; }
}
global.Date = StubDate;
const __fs = require("fs");
global.fetch = async (url) => {
  if (url === "nyse-holidays.json")
    return { ok: true, text: async () => __fs.readFileSync(process.env.WSJSON, "utf8") };
  return { ok: false };
};
global.AbortController = class { constructor(){} abort(){} get signal(){ return undefined; } };
const __el = () => ({ innerHTML:"", textContent:"", value:"30", style:{},
                      addEventListener(){}, });
global.document = { getElementById: __el };
global.localStorage = { getItem: () => null, setItem(){} };

// ---- the real page script is inlined here ----
//__SCRIPT__

// ---- test driver (scenarios built from the real holiday JSON) ----
;(async () => {
  const assert = require("assert");
  for (let i = 0; i < 200 && NYSE_HOLIDAYS.size === 0; i++)
    await new Promise(r => setTimeout(r, 20));
  await loadHolidays();
  assert(NYSE_HOLIDAYS.size > 0, "holiday set loaded via stubbed fetch");
  assert(NYSE_HOLIDAYS.has("__CLOSED__"), "__CLOSED__ in set");
  assert(!NYSE_HOLIDAYS.has("__OPEN__"), "__OPEN__ not in set");
  const sess = (utcMs) => { FIXED = utcMs; return marketSession(); };
  // __CLOSED__ 10:00 ET: real holiday -> closed
  assert.strictEqual(sess(__UTC_CLOSED__).key, "closed");
  // __OPEN__ 10:00 ET: weekday, not a holiday -> open
  assert.strictEqual(sess(__UTC_OPEN__).key, "open");
  // __SAT__ is a Saturday -> closed
  assert.strictEqual(sess(__UTC_SAT__).key, "closed");
  console.log("NODE-FUNCTIONAL: all assertions passed");
  process.exit(0);
})().catch(e => { console.error("NODE-FUNCTIONAL FAIL:", e.message); process.exit(1); });
"""
    harness = (driver.replace("//__SCRIPT__", script)
               .replace("__CLOSED__", closed_day)
               .replace("__OPEN__", open_day)
               .replace("__SAT__", sat_day)
               .replace("__UTC_CLOSED__", utc_args(closed_day))
               .replace("__UTC_OPEN__", utc_args(open_day))
               .replace("__UTC_SAT__", utc_args(sat_day)))
    with open("/tmp/portal_holiday_harness.js", "w") as f:
        f.write(harness)
    env = dict(os.environ, WSJSON=WORKSPACE_JSON)
    r = subprocess.run(["node", "/tmp/portal_holiday_harness.js"],
                       capture_output=True, text=True, env=env, timeout=60)
    ok = r.returncode == 0 and "NODE-FUNCTIONAL: all assertions passed" in r.stdout
    check("node functional: real marketSession vs real holiday JSON", ok,
          (r.stdout + r.stderr).strip()[-500:])

print()
if failures:
    print(f"{len(failures)} FAILING CHECK(S): {', '.join(failures)}")
    sys.exit(1)
print("ALL CHECKS PASSED")
