#!/usr/bin/env python3
"""Recompute SlipScore model.json and commit to GitHub <owner>/slipbuilder-stats (main) only on change.
Run after the nightly v3 retrain and after each board scan. Token: $GITHUB_TOKEN/$GH_TOKEN, else `gh auth token`."""
import json, os, sys, glob, base64, datetime, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_record import token, api, CT, REPO
LED = "/home/box/agent-data/agents/2bf461f0-c668-495d-8532-d920b6d759af/ledger"
V3 = os.path.join(LED, "slipscore_v3")

def training_set():
    # Exactly what v3 fits on (fit_final.py / v3live.wf_logloss): lines_all.pkl rows with a graded outcome in CATS.
    import pandas as pd
    sys.path.insert(0, V3)
    from v3all.lines import CATS
    L = pd.read_pickle(os.path.join(V3, "results", "lines_all.pkl"))
    T = L[L.y.notna() & L.market.isin(CATS)]
    return len(T), int(T.market.nunique()), int(T.t.max())

def latest_slate():
    files = sorted(f for f in glob.glob(os.path.join(LED, "board-scan", "*.jsonl"))
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.jsonl", os.path.basename(f)))
    f = files[-1]; rows = [json.loads(l) for l in open(f) if l.strip()]
    lines = {(r.get("player"), r.get("market"), r.get("line")) for r in rows}
    return dict(slate_date=os.path.basename(f)[:10], lines_scanned=len(lines),
                slate_games=len({r.get("game") for r in rows}), slate_markets=len({r.get("market") for r in rows}))

def compute():
    n, cats, tt = training_set()
    s = latest_slate()
    return dict(graded_props=n, prop_categories=cats, trained_through=f"{tt//100} W{tt%100}", **s,
                # static: walk-forward confident Unders, REPORT_REFINE.md "Confident picks (P>=0.58)"
                calib_under_n=2492, calib_under_stated_pct=64.7, calib_under_hit_pct=65.4)

def main():
    tok = token(); owner = api("GET", "/user", tok)["login"]
    stats = compute(); path = f"/repos/{owner}/{REPO}/contents/model.json"
    cur = api("GET", path + "?ref=main", tok)
    if cur and {k: v for k, v in json.loads(base64.b64decode(cur["content"])).items() if k != "updated_at"} == stats:
        print("model.json unchanged:", json.dumps(stats)); return
    rec = dict(stats, updated_at=datetime.datetime.now(CT).isoformat(timespec="seconds"))
    body = {"message": f"model: {rec['graded_props']} graded props, {rec['lines_scanned']} lines {rec['slate_date']}",
            "content": base64.b64encode((json.dumps(rec, indent=2) + "\n").encode()).decode(), "branch": "main"}
    if cur: body["sha"] = cur["sha"]
    api("PUT", path, tok, body); print("committed:", json.dumps(rec))

if __name__ == "__main__":
    print(json.dumps(compute(), indent=2)) if "--dry-run" in sys.argv else main()
