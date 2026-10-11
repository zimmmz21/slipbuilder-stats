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

FLOOR = 247510
PARQUET = "/workspace/props-all/graded_props_2023_2025.parquet"
WHY26 = "/workspace/why-tags/why_tags_2026.parquet"
MKT = {"tackles and assists": "tackles+assists", "tackles + assists": "tackles+assists", "solo tackles": "tackles",
       "rush attempts": "rushing attempts"}
def _p(n): return re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", re.sub(r"[^a-z ]", "", str(n).lower().replace("-", " "))).split().__str__()
def _m(m): m = str(m).strip().lower(); return MKT.get(m, m)
def _k(week, player, market, line): return (int(week), _p(player), _m(market), round(float(line), 1))

def graded_2026():
    """Unique graded 2026 props keyed (NFL week, player, market, line) - one key per prop regardless of side/source.
    Sources: v3 2026 DK board lines (graded y), why_tags_2026 (OVER/UNDER), ledger legs graded HIT/MISS (all slips)."""
    import pandas as pd
    from update_record import nfl_week, LEDGER
    K = {}; src = {}
    L = pd.read_pickle(os.path.join(V3, "results", "lines_all.pkl")); L = L[(L.season == 2026) & L.y.notna()]
    for r in L.itertuples(): K.setdefault(_k(r.week, r.player, r.market, r.line), "dk_board")
    W = pd.read_parquet(WHY26); W = W[W.result.isin(["OVER", "UNDER", "PUSH"]) & W.line.notna() & W.week.notna()]
    for r in W.itertuples(): K.setdefault(_k(r.week, r.player_name, r.market, r.line), "why_tags_2026")
    for s in json.load(open(LEDGER))["slips"]:
        if not s["date"].startswith("2026") or s["date"] < "2026-09-08": continue  # preseason legs are not REG props
        for p in s.get("picks", []):
            if p.get("grade") in ("HIT", "MISS") and p.get("line") is not None:
                K.setdefault(_k(nfl_week(s), p["player"], p.get("stat") or p.get("market"), p["line"]), "ledger")
    for v in K.values(): src[v] = src.get(v, 0) + 1
    return len(K), src

def compute():
    import pandas as pd
    hist = len(pd.read_parquet(PARQUET, columns=["season"]))
    n26, src26 = graded_2026()
    n, cats, tt = training_set()
    s = latest_slate()
    return dict(graded_props=hist + n26, graded_props_2023_2025=hist, graded_props_2026=n26,
                graded_2026_by_first_source=src26, trained_lines=n, prop_categories=cats, trained_through=f"{tt//100} W{tt%100}", **s,
                # static: walk-forward confident Unders, REPORT_REFINE.md "Confident picks (P>=0.58)"
                calib_under_n=2492, calib_under_stated_pct=64.7, calib_under_hit_pct=65.4)

def main():
    tok = token(); owner = api("GET", "/user", tok)["login"]
    stats = compute(); path = f"/repos/{owner}/{REPO}/contents/model.json"
    cur = api("GET", path + "?ref=main", tok)
    prev = json.loads(base64.b64decode(cur["content"])) if cur else {}
    # monotonic: never below 247,510 or the previously committed value
    prev_total = prev.get("graded_props", 0) if prev.get("graded_props_2023_2025") else 0  # ignore old trained-lines value
    stats["graded_props"] = max(FLOOR, prev_total, stats["graded_props"])
    today = datetime.datetime.now(CT).date().isoformat()
    if prev.get("day_start_date") == today: base = prev["day_start_graded_props"]
    else: base = max(FLOOR, prev_total)          # last committed total before today
    stats.update(day_start_date=today, day_start_graded_props=base, added_today=stats["graded_props"] - base)
    if cur and {k: v for k, v in json.loads(base64.b64decode(cur["content"])).items() if k != "updated_at"} == stats:
        print("model.json unchanged:", json.dumps(stats)); return
    rec = dict(stats, updated_at=datetime.datetime.now(CT).isoformat(timespec="seconds"))
    body = {"message": f"model: {rec['graded_props']} graded props, {rec['lines_scanned']} lines {rec['slate_date']}",
            "content": base64.b64encode((json.dumps(rec, indent=2) + "\n").encode()).decode(), "branch": "main"}
    if cur: body["sha"] = cur["sha"]
    api("PUT", path, tok, body); print("committed:", json.dumps(rec))

if __name__ == "__main__":
    print(json.dumps(compute(), indent=2)) if "--dry-run" in sys.argv else main()
