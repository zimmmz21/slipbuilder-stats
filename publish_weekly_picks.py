#!/usr/bin/env python3
"""BOX side: weekly free-pick content for slipbuilder.io -> zimmmz21/slipbuilder-stats/potd.json (the file the live site already reads
through its commit-pinned slipbuilder-stats fetch: weeks["N"].potd {player, stat, line (string), side More|Less, reason <= 20 words} and
weeks["N"].games [{away, home, kickoff ISO}]). Extra fields per week (for the archive page add-on): range, potds (every free pick of the
week with its grade), last_week (graded legs and free-pick results; PER-PICK ONLY since 2026-11-16: no card count, no 4/4 count, no slip record), season (through last week), writeup (150-300 words,
plain English, template-built from real data only; no LLM, no source/model names).

Data: the graded slip ledger (official Discord cards, same filter/definitions as record.json: legs, Tue-Mon weeks, Week 1 = Tue 2026-09-08)
and the public NFL scoreboard (kickoffs, 1 request per day of the current week; past weeks are kept from the published file).
Publishes through the GitHub contents API exactly like update_record.py; commits only when content (minus updated_at) changes.
Usage: publish_weekly_picks.py [--dry-run] [--now ISO] [--out FILE]"""
import os, re, sys, json, base64, datetime as dt, urllib.request, collections
from zoneinfo import ZoneInfo
sys.path.insert(0, "/workspace/site-stats")
import update_record as UR          # token(), api(), official(), REPO, BRANCH (same publish path as record.json)
CT = ZoneInfo("America/Chicago"); UTC = dt.timezone.utc
W1 = dt.date(2026, 9, 8)
LEDGER = os.environ.get("SB_LEDGER", "/workspace/slip-ledger.json")
LOCAL = os.environ.get("WEEKLY_PICKS_LOCAL", "/workspace/weekly-picks/potd.json")
PATH = "potd.json"
FIRST_WEEK = 5          # first full week of Thu/Sun/Mon official cards (Week 4 had only a Monday catch-up card)
BANNED = re.compile(r"\b(espn|propline|prop-?line|covers|odds ?api|draftkings|dk|fanduel|fd|betmgm|mgm|bet365|caesars|prizepicks|underdog|sleeper|"
                    r"pick6|dabble|parlayplay|nflverse|pff|model|slipscore|algorithm|algo|v\d|engine|confidence|ai)\b", re.I)

def week_of(d): return (d - W1).days // 7 + 1
def week_range(n): s = W1 + dt.timedelta(days=7 * (n - 1)); return s, s + dt.timedelta(days=6)
def slip_week(s):
    try: return week_of(dt.date.fromisoformat(str(s.get("date"))[:10]))
    except Exception: return None
def fmt_day(d): return f"{d:%a} {d:%b} {d.day}"
def num(x): x = float(x); return str(int(x)) if x == int(x) else f"{x:g}"
def clean(t):
    """keep only clauses with no source/model wording"""
    parts = [p.strip() for p in re.split(r"[;|]", str(t or "")) if p.strip() and not BANNED.search(p)]
    return "; ".join(parts)
def words(t, n): w = str(t).split(); return " ".join(w[:n])

# ---------------------------------------------------------------- ledger
def ledger():
    return [s for s in json.load(open(LEDGER))["slips"] if UR.official(s) and s.get("posted") is not False]
def legs(slips, wk=None, upto=None):
    for s in slips:
        w = slip_week(s)
        if w is None or (wk is not None and w != wk) or (upto is not None and w > upto): continue
        for p in s.get("picks", []): yield s, p
def wl(it):
    w = l = 0
    for _, p in it:
        g = p.get("grade")
        if g == "HIT": w += 1
        elif g == "MISS": l += 1
    return w, l
def pct(w, l): return round(100 * w / (w + l), 1) if w + l else None
def potd_obj(s, p):
    reason = clean(p.get("card_why") or p.get("why_live") or "")
    if not reason and p.get("player_last5"):
        reason = "Last games: " + ", ".join(num(v) for v in p["player_last5"][:5])
    o = {"player": p["player"], "stat": p["stat"], "line": num(p["line"]), "side": p["side"], "reason": words(reason, 20),
         "game": p.get("game_display") or (p.get("game") or "").replace("@", " @ "), "kickoff": p.get("kickoff_ct"), "date": s.get("date")}
    if p.get("grade") in ("HIT", "MISS", "VOID"): o["result"] = p["grade"]
    if p.get("grade") in ("HIT", "MISS") and p.get("actual") is not None: o["actual"] = num(p["actual"])
    return o
POSTLOG = "/workspace/slipbuilder-x/post-log.jsonl"
def posted_potds():
    """free picks announced publicly (post log 'potd' rows: date + 'Player More 62.5 Stat'); covers picks posted before the ledger flag existed"""
    out = set()
    try:
        for ln in open(POSTLOG):
            try: r = json.loads(ln)
            except ValueError: continue
            if r.get("type") != "potd": continue
            m = re.match(r"^(.*?)\s+(MORE|LESS|More|Less)\s+([\d.]+)\s", str(r.get("leg") or ""))
            d = str(r.get("date") or r.get("ts") or "")[:10]
            if m and d: out.add((d, m.group(1).strip(), m.group(2).capitalize(), float(m.group(3))))
    except OSError: pass
    return out
def potds(slips, wk):
    out, seen, pub = [], set(), posted_potds()
    for s, p in legs(slips, wk):
        k = (p.get("player"), p.get("stat"), p.get("line"), p.get("side"))
        flagged = p.get("potd") or (str(s.get("date")), p.get("player"), p.get("side"), float(p.get("line") or -1)) in pub
        if flagged and k not in seen: seen.add(k); out.append(potd_obj(s, p))
    return sorted(out, key=lambda o: (o["date"] or "", o["kickoff"] or ""))
def week_summary(slips, wk):
    w, l = wl(legs(slips, wk))
    return {"week": wk, "w": w, "l": l, "pct": pct(w, l), "potds": potds(slips, wk)}   # per-pick only (no card count / 4-of-4 count)

# ---------------------------------------------------------------- schedule
def games(wk):
    s, e = week_range(wk); out = {}
    for i in range(7):
        d = s + dt.timedelta(days=i)
        try:
            req = urllib.request.Request(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={d:%Y%m%d}",
                                         headers={"User-Agent": "Mozilla/5.0"})
            sb = json.load(urllib.request.urlopen(req, timeout=20))
        except Exception as ex:
            raise RuntimeError(f"schedule fetch failed for {d}: {type(ex).__name__}")
        for ev in sb.get("events", []):
            c = ev["competitions"][0]; t = {x["homeAway"]: x["team"]["abbreviation"] for x in c["competitors"]}
            ko = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            if s <= ko.astimezone(CT).date() <= e: out[ev["id"]] = {"away": t["away"], "home": t["home"], "kickoff": ko.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return sorted(out.values(), key=lambda g: (g["kickoff"], g["away"]))

# ---------------------------------------------------------------- write-up (template, real data only)
def phrase(p, done=True):
    st = p["stat"].lower(); side = "over" if p["side"] == "More" else "under"
    if "anytime td" in st:
        base = f"{p['player']} to score a touchdown" if p["side"] == "More" else f"{p['player']} not to score a touchdown"
    else: base = f"{p['player']} {side} {p['line']} {st}"
    if not done or "result" not in p: return base
    if p["result"] == "VOID": return base + " (voided)"
    act = p.get("actual")
    if "anytime td" in st: tail = "he found the end zone" if (act and float(act) > 0) else "no touchdown"
    else: tail = f"finished with {act}" if act is not None else ""
    return f"{base} ({'hit' if p['result'] == 'HIT' else 'missed'}{', ' + tail if tail else ''})"
def highlights(slips, wk, skip, n=2):
    c = []
    for s, p in legs(slips, wk):
        if p.get("grade") != "HIT" or p.get("actual") is None or p.get("potd") or "anytime td" in str(p.get("stat")).lower(): continue
        if (p["player"], p["stat"]) in skip: continue
        ln = float(p["line"]); a = float(p["actual"]); m = (a - ln) if p["side"] == "More" else (ln - a)
        c.append((m / max(ln, 1.0), p))
    out, seen = [], set()
    for _, p in sorted(c, key=lambda x: -x[0]):
        if p["player"] in seen: continue
        seen.add(p["player"]); out.append(p)
        if len(out) == n: break
    return out
def writeup(wk, gms, potd_now, wk_potds, last, season, so_far, by_week=(), final=False):
    s, e = week_range(wk); P = []
    by_day = collections.Counter(dt.datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00")).astimezone(CT).strftime("%A") for g in gms)
    if gms:
        f, l = gms[0], gms[-1]
        fk = dt.datetime.fromisoformat(f["kickoff"].replace("Z", "+00:00")).astimezone(CT)
        lk = dt.datetime.fromisoformat(l["kickoff"].replace("Z", "+00:00")).astimezone(CT)
        days = ", ".join(f"{v} on {k}" for k, v in sorted(by_day.items(), key=lambda kv: ["Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday","Monday"].index(kv[0])))
        P.append(f"Week {wk} runs {fmt_day(s)} to {fmt_day(e)} with {len(gms)} games ({days}). It opens with {f['away']} at {f['home']} on "
                 f"{fk:%A} at {fk.hour % 12 or 12}:{fk.minute:02d} {'PM' if fk.hour >= 12 else 'AM'} CT and closes with {l['away']} at {l['home']} on {lk:%A} night.")
    else: P.append(f"Week {wk} runs {fmt_day(s)} to {fmt_day(e)}.")
    if final:
        if wk_potds: P.append("The free pick" + (" was " if len(wk_potds) == 1 else "s were ") + "; ".join(phrase(p) for p in wk_potds) + ".")
        if so_far and so_far[0] + so_far[1]: P.append(f"The week's official picks finished {so_far[0]}-{so_far[1]} ({pct(*so_far)}% of legs hit).")
    elif potd_now:
        P.append(f"The free pick for this week is {phrase(potd_now, done=False)} in {potd_now['game']}."
                 + (f" The reason in one line: {potd_now['reason'].rstrip('.')}." if potd_now.get("reason") else ""))
        prev = [p for p in wk_potds if p is not potd_now and "result" in p]
        if prev: P.append("Earlier this week the free pick" + (" was " if len(prev) == 1 else "s were ") + "; ".join(phrase(p) for p in prev) + ".")
    else:
        P.append("The free pick posts on game-day mornings once the official cards are out, starting with the first game of the week.")
    if not final and so_far and so_far[0] + so_far[1]:
        P.append(f"So far this week the official picks are {so_far[0]}-{so_far[1]}.")
    if last and last["w"] + last["l"]:
        t = f"Last week (Week {last['week']}) the official picks went {last['w']}-{last['l']} ({last['pct']}% of legs hit)."
        if last["potds"]:
            pw = sum(p.get("result") == "HIT" for p in last["potds"]); pl = sum(p.get("result") == "MISS" for p in last["potds"])
            t += f" The free picks went {pw}-{pl}: " + "; ".join(phrase(p) for p in last["potds"]) + "."
        hl = last.get("highlights") or []
        if hl:
            t += " Other standouts: " + " and ".join(f"{p['player']} {'over' if p['side'] == 'More' else 'under'} {num(p['line'])} {p['stat'].lower()} ({num(p['actual'])})" for p in hl) + "."
        P.append(t)
    if season and season["w"] + season["l"]:
        P.append(f"That puts the season at {season['w']}-{season['l']} on legs ({season['pct']}%). Every official leg is graded after the final "
                 f"whistle and counted, wins and losses alike, and every graded pick is on the record page.")
    txt = " ".join(P)
    if len(txt.split()) < 150 and by_week:
        txt += " Week by week on legs: " + ", ".join(f"Week {k} {v[0]}-{v[1]}" for k, v in by_week) + "."
    if len(txt.split()) < 150:
        txt += (" Official picks post around 7 AM CT on Thursday, Sunday and Monday game days, and this page updates "
                "with the free pick and the graded results as each slate finishes.")
    return txt

# ---------------------------------------------------------------- build
def entry(wk, now, slips, gms):
    _, e = week_range(wk)
    wk_potds = potds(slips, wk)
    posted = [p for p in wk_potds if p["date"] and dt.date.fromisoformat(p["date"]) <= now.astimezone(CT).date()]
    potd_now = posted[-1] if posted else None
    last = week_summary(slips, wk - 1)
    last["highlights"] = highlights(slips, wk - 1, {(p["player"], p["stat"]) for p in last["potds"]})
    final = now.astimezone(CT).date() > week_range(wk)[1]
    sw, sl = wl(legs(slips, upto=wk if final else wk - 1))
    season = {"w": sw, "l": sl, "pct": pct(sw, sl)}
    so_far = wl(legs(slips, wk))
    by_week = [(k, wl(legs(slips, k))) for k in sorted({slip_week(x) for x in slips if slip_week(x) and slip_week(x) < wk})]
    text = writeup(wk, gms, potd_now, wk_potds, last, season, so_far, [(k, v) for k, v in by_week if sum(v)],
                    final=final)
    m = BANNED.search(text)
    assert not m, f"write-up contains a banned word: {m.group(0) if m else None}"
    site_potd = {k: potd_now[k] for k in ("player", "stat", "line", "side", "reason")} if potd_now else None
    last_out = {k: last[k] for k in ("week", "w", "l", "pct", "potds")}   # per-pick only: no card count / 4-of-4 count
    s, e = week_range(wk)
    return {"week": wk, "range": {"start": s.isoformat(), "end": e.isoformat()}, "games": gms, "potd": site_potd,
            "potd_game": ({"game": potd_now["game"], "kickoff": potd_now["kickoff"]} if potd_now else None),
            "potds": wk_potds, "last_week": last_out, "season": season, "so_far": {"w": so_far[0], "l": so_far[1]},
            "writeup": text, "writeup_words": len(text.split())}
def strip_ts(d): return json.loads(json.dumps(d, sort_keys=True), object_hook=lambda o: {k: v for k, v in o.items() if k != "updated_at"})
def main():
    a = sys.argv
    now = dt.datetime.fromisoformat(a[a.index("--now") + 1]).astimezone(CT) if "--now" in a else dt.datetime.now(CT)
    dry = "--dry-run" in a
    cur_wk = week_of(now.date())
    slips = ledger()
    tok = UR.token(); owner = UR.api("GET", "/user", tok)["login"]
    path = f"/repos/{owner}/{UR.REPO}/contents/{PATH}"
    cur = UR.api("GET", path + f"?ref={UR.BRANCH}", tok)
    old = json.loads(base64.b64decode(cur["content"])) if cur else {"v": 1, "weeks": {}}
    weeks = dict(old.get("weeks") or {})
    want = sorted({w for w in (slip_week(s) for s in slips) if w and FIRST_WEEK <= w <= cur_wk} | {cur_wk})
    for wk in want:
        frozen = weeks.get(str(wk)) or {}
        slip_rec = "cashed_4of4" in (frozen.get("last_week") or {}) or "cards" in (frozen.get("last_week") or {}) or "cashed" in (frozen.get("writeup") or "").lower()
        if wk < cur_wk - 1 and str(wk) in weeks and not slip_rec: continue          # finished weeks stay frozen (one-time per-pick rebuild if they carry a slip record)
        gms = weeks.get(str(wk), {}).get("games") if wk < cur_wk and weeks.get(str(wk), {}).get("games") else games(wk)
        wnow = now if wk == cur_wk else dt.datetime.combine(week_range(wk)[1] + dt.timedelta(days=1), dt.time(9, 30), CT)   # as of the Tuesday after
        e = entry(wk, wnow, slips, gms)
        prev = weeks.get(str(wk))
        e["updated_at"] = prev["updated_at"] if prev and strip_ts(prev) == strip_ts(e) else now.isoformat(timespec="seconds")
        weeks[str(wk)] = e
    doc = {"v": 1, "current_week": cur_wk, "weeks": dict(sorted(weeks.items(), key=lambda kv: int(kv[0])))}
    doc["updated_at"] = old.get("updated_at") if strip_ts(old) == strip_ts(doc) else now.isoformat(timespec="seconds")
    raw = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    out = a[a.index("--out") + 1] if "--out" in a else LOCAL
    os.makedirs(os.path.dirname(out), exist_ok=True); open(out, "w").write(raw)
    w = doc["weeks"][str(cur_wk)]
    summary = (f"week {cur_wk}: {len(w['games'])} games, potd {'set' if w['potd'] else 'pending'}, last week {w['last_week']['w']}-{w['last_week']['l']}, "
               f"writeup {w['writeup_words']} words, weeks {list(doc['weeks'])}")
    if cur and strip_ts(old) == strip_ts(doc): print("potd.json unchanged;", summary); return 0
    if dry: print("DRY RUN (not published);", summary); return 0
    body = {"message": f"weekly picks: week {cur_wk}" + (" (pick posted)" if w["potd"] else ""),
            "content": base64.b64encode(raw.encode()).decode(), "branch": UR.BRANCH}
    if cur: body["sha"] = cur["sha"]
    UR.api("PUT", path, tok, body)
    print("committed potd.json;", summary); return 0
if __name__ == "__main__": sys.exit(main())
