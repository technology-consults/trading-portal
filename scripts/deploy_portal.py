#!/usr/bin/env python3
"""Assemble and deploy the trading-portal GitHub Pages branch (API-only).

Replaces the old scripts/deploy.sh, which used git CLI (prohibited).

Sources of truth:
  - portal code/assets : technology-consults/trading-portal @ main
  - holiday list       : technology-consults/cross-thread-task-status-tracker
                         holidays/nyse_holidays.json @ main (single canonical copy)

The deployable is the `gh-pages` branch: a self-contained copy of main's
files plus nyse-holidays.json (generated deploy output — never edited by
hand, never synced back into the workspace). The page reads
nyse-holidays.json same-origin at runtime and never fetches holiday data
from GitHub while a visitor is using it.

Usage:
  python3 scripts/deploy_portal.py            # --dry-run (default), read-only
  python3 scripts/deploy_portal.py --dry-run  # same: show what would deploy
  python3 scripts/deploy_portal.py --live     # actually write the gh-pages branch

Pre-deploy gate: tests/test_portal_holiday_regression.py must pass, else abort.
Deploy policy (2026-09-29): the portal's own files are hard requirements —
any read/write failure aborts the deploy. The holiday JSON is best-effort:
if it cannot be fetched or fails validation, the previously deployed copy
is carried forward untouched (never overwritten with bad data, never
deleted) and the deploy continues with a loud warning. A dead holiday
pipeline must not block shipping a page fix.
Auth: the github skill's gh_api.py (stored custom.github credential) — this
script never handles tokens directly.
"""
import base64
import datetime
import json
import os
import re
import subprocess
import sys

GH = [sys.executable,
      os.path.expanduser("~/workspace/skills/github/bin/gh_api.py")]
PORTAL_REPO = "technology-consults/trading-portal"
CROSS_REPO = "technology-consults/cross-thread-task-status-tracker"
DEPLOY_BRANCH = "gh-pages"
HOLIDAYS_SRC = "holidays/nyse_holidays.json"
HOLIDAYS_DST = "nyse-holidays.json"


def api(method, path, payload=None):
    cmd = GH + [method, path]
    if payload is not None:
        cmd.append(json.dumps(payload))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"GitHub API {method} {path} failed:\n{r.stderr}")
    return json.loads(r.stdout or "{}")


def get_file_text(repo, path, ref):
    r = api("GET", f"/repos/{repo}/contents/{path}?ref={ref}")
    if r.get("type") != "file":
        raise RuntimeError(f"{repo}/{path}@{ref} is not a file")
    return base64.b64decode(r["content"]).decode("utf-8")


def validate_holidays(text):
    """Validate the exact holiday JSON being assembled for deploy.

    This runs against the REMOTE copy fetched from the cross-thread repo —
    the same bytes that will ship — not the local workspace file. It checks
    structure plus freshness: the canonical list is a rolling next-four-
    months file refreshed quarterly.

    A validation failure does NOT abort the deploy (policy 2026-09-29): the
    caller treats it as soft — the previously deployed copy is carried
    forward untouched and the deploy continues with a warning. It is never
    correct to overwrite a good deployed file with a bad one, and a dead
    holiday pipeline must not block shipping a page fix.
    """
    d = json.loads(text)
    for k in ("updated", "sources", "note", "holidays"):
        assert k in d, f"holiday JSON missing key: {k}"
    try:
        upd = datetime.date.fromisoformat(d["updated"])
    except (ValueError, TypeError):
        raise AssertionError(f'"updated" is not a YYYY-MM-DD date: '
                             f"{d['updated']!r}")
    today = datetime.date.today()
    assert upd <= today, f'"updated" {upd} is in the future'
    assert (today - upd).days <= 120, (
        f'"updated" {upd} is {(today - upd).days} days old — the quarterly '
        "refresh may have failed")
    hs = d["holidays"]
    assert isinstance(hs, list) and hs, "holiday list empty"
    assert hs == sorted(hs), "holiday list not sorted"
    assert len(hs) == len(set(hs)), "duplicate holiday dates"
    for h in hs:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", h), f"bad date: {h}"
        try:
            dd = datetime.date.fromisoformat(h)
        except ValueError:
            raise AssertionError(f"not a real calendar date: {h}")
        assert dd >= today - datetime.timedelta(days=100), (
            f"holiday {h} is stale (over 100 days past) — mirror is outdated")
        assert dd <= today + datetime.timedelta(days=150), (
            f"holiday {h} is beyond the 4-month rolling window — "
            "unexpected content")
    return d


def assemble():
    """Read-only: gather every deployable file. No writes.

    Portal files from main are hard requirements: any read failure raises
    and aborts the deploy. The holiday JSON is best-effort (soft): if it
    cannot be fetched or fails validation, the previously deployed copy is
    carried forward untouched and the deploy continues with a loud warning.
    """
    tree = api("GET", f"/repos/{PORTAL_REPO}/git/trees/main?recursive=1")
    files = {}
    for entry in tree["tree"]:
        if entry["type"] != "blob":
            continue
        if entry["path"] == "docs/trading-portal-documentation.pdf" or \
                entry["path"].startswith("docs/"):
            # Documentation is not site content — the served branch is the
            # website. (docs/trading-portal-documentation.pdf is binary and would also break the
            # text assembly below.)
            continue
        files[entry["path"]] = get_file_text(PORTAL_REPO, entry["path"],
                                             "main")
    try:
        hol_text = get_file_text(CROSS_REPO, HOLIDAYS_SRC, "main")
        doc = validate_holidays(hol_text)
    except Exception as e:
        try:
            files[HOLIDAYS_DST] = get_file_text(PORTAL_REPO, HOLIDAYS_DST,
                                                DEPLOY_BRANCH)
            print(f"WARNING: holiday list unavailable/invalid ({e}); "
                  f"carrying forward the deployed copy unchanged.",
                  file=sys.stderr)
        except Exception:
            print(f"WARNING: holiday list unavailable/invalid ({e}); no "
                  f"deployed copy exists — the page will run with "
                  f"weekday-only session labels until a good list deploys.",
                  file=sys.stderr)
        doc = None
    else:
        files[HOLIDAYS_DST] = hol_text
    return files, doc


def run_regression():
    here = os.path.dirname(os.path.abspath(__file__))
    test = os.path.normpath(os.path.join(here, "..", "tests",
                                         "test_portal_holiday_regression.py"))
    r = subprocess.run([sys.executable, test], capture_output=True, text=True)
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    return r.returncode == 0


def deploy(files):
    entries = [{"path": p, "mode": "100644", "type": "blob", "content": t}
               for p, t in sorted(files.items())]
    tree = api("POST", f"/repos/{PORTAL_REPO}/git/trees", {"tree": entries})
    try:
        ref = api("GET",
                  f"/repos/{PORTAL_REPO}/git/refs/heads/{DEPLOY_BRANCH}")
        parents = [ref["object"]["sha"]]
        exists = True
    except RuntimeError:
        parents, exists = [], False
    commit = api("POST", f"/repos/{PORTAL_REPO}/git/commits",
                 {"message": "portal deploy: assemble gh-pages "
                             "(portal source + canonical holiday list)",
                  "tree": tree["sha"], "parents": parents})
    if exists:
        # NOTE: plural /git/refs/ — the singular /git/ref/ answers GET but
        # PATCH on it drops the connection (learned 2026-09-27).
        api("PATCH",
            f"/repos/{PORTAL_REPO}/git/refs/heads/{DEPLOY_BRANCH}",
            {"sha": commit["sha"]})
    else:
        api("POST", f"/repos/{PORTAL_REPO}/git/refs",
            {"ref": f"refs/heads/{DEPLOY_BRANCH}", "sha": commit["sha"]})
    return commit["sha"]


def main():
    live = "--live" in sys.argv
    print("=== pre-deploy regression gate ===")
    if not run_regression():
        print("REGRESSION FAILED — deploy aborted.", file=sys.stderr)
        return 1
    print("=== assembling deployable (read-only) ===")
    files, doc = assemble()
    print(f"deploy branch: {DEPLOY_BRANCH}")
    print(f"sources: {PORTAL_REPO}@main + {CROSS_REPO} {HOLIDAYS_SRC}@main")
    for p in sorted(files):
        print(f"  {p} ({len(files[p])} bytes)")
    if doc:
        print(f"holidays embedded: {len(doc['holidays'])} dates, "
              f"{doc['holidays'][0]} .. {doc['holidays'][-1]}")
    else:
        print("holidays: refreshed copy unavailable — deployed copy carried "
              "forward or omitted (see WARNING above)")
    if not live:
        print("DRY RUN: no branch changes made. Re-run with --live to deploy.")
        return 0
    sha = deploy(files)
    print(f"deployed {DEPLOY_BRANCH} @ {sha[:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
