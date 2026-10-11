#!/usr/bin/env python3
"""Recompute SlipBuilder record.json from the graded ledger and commit it to
GitHub <owner>/slipbuilder-stats (main) only if the content changed.
Token: $GITHUB_TOKEN / $GH_TOKEN, else `gh auth token`."""
import json, os, re, sys, base64, subprocess, datetime, urllib.request, urllib.error
from zoneinfo import ZoneInfo

LEDGER = os.environ.get("SB_LEDGER", "/workspace/slip-ledger.json")
REPO = os.environ.get("SB_STATS_REPO", "slipbuilder-stats")
CT = ZoneInfo("America/Chicago")
WEEK1_TUESDAY = datetime.date(2026, 9, 8)  # NFL weeks run Tue..Mon; Week 5 TNF = 2026-10-08

def nfl_week(slip):
    m = re.search(r"Week\s+(\d+)", str(slip.get("week") or ""))
    if m: return int(m.group(1))
    d = datetime.date.fromisoformat(slip["date"])
    return (d - WEEK1_TUESDAY).days // 7 + 1

def official(slip):
    return (slip.get("channel") == "discord" and not slip.get("superseded")
            and slip.get("status") != "superseded")

def compute(now=None):
    now = now or datetime.datetime.now(CT)
    slips = json.load(open(LEDGER))["slips"]
    cur_week = (now.date() - WEEK1_TUESDAY).days // 7 + 1
    last_week = cur_week - 1
    sw = sl = lw = ll = 0
    for s in filter(official, slips):
        wk = nfl_week(s)
        for p in s.get("picks", []):
            g = p.get("grade")
            if g not in ("HIT", "MISS"): continue   # VOID / ungraded excluded
            hit = g == "HIT"
            sw += hit; sl += not hit
            if wk == last_week: lw += hit; ll += not hit
    tot = sw + sl
    return {
        "season_w": sw, "season_l": sl,
        "legs_hit_pct": round(100 * sw / tot, 1) if tot else None,
        "cashed_legs": sw,
        "last_week_w": lw, "last_week_l": ll,
    }

def token():
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(k): return os.environ[k]
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sys.exit("No GitHub token: set GITHUB_TOKEN (repo scope) or run `gh auth login`.")

def api(method, path, tok, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                 "User-Agent": "slipbuilder-stats"})
    try:
        with urllib.request.urlopen(req) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise

def main():
    tok = token()
    owner = api("GET", "/user", tok)["login"]
    stats = compute()
    path = f"/repos/{owner}/{REPO}/contents/record.json"
    cur = api("GET", path + "?ref=main", tok)
    if cur:
        old = json.loads(base64.b64decode(cur["content"]))
        if {k: v for k, v in old.items() if k != "updated_at"} == stats:
            print("record.json unchanged:", json.dumps(stats)); return
    rec = dict(stats, updated_at=datetime.datetime.now(CT).isoformat(timespec="seconds"))
    body = {"message": f"record: {rec['season_w']}-{rec['season_l']} season, last week {rec['last_week_w']}-{rec['last_week_l']}",
            "content": base64.b64encode((json.dumps(rec, indent=2) + "\n").encode()).decode(), "branch": "main"}
    if cur: body["sha"] = cur["sha"]
    api("PUT", path, tok, body)
    print("committed:", json.dumps(rec))

if __name__ == "__main__":
    if "--dry-run" in sys.argv: print(json.dumps(compute(), indent=2))
    else: main()
