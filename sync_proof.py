#!/usr/bin/env python3
"""Auto-proof feed for slipbuilder.io (ZIMMMZ approved 2026-10-17).

PER-PICK ONLY (ZIMMMZ 2026-11-16, best-picks direction): no slip/card record is published. PER_PICK_ONLY=True stops adding 4/4
card items, drops the existing card items + proof/cards/*.png from the public feed, and retitles the legs pages "Legs Hit"
(re-rendered once; file names/ids stay cashed-legs-N so existing image URLs keep working). Card grading stays internal in the
ledger. Misses are public in results.json (every graded leg). PER_PICK_ONLY=False = previous behavior.

Keeps zimmmz21/slipbuilder-stats:proof/ in sync with the graded slip ledger:
  proof/cards/*.png   every official 4/4 results card (11 historical site cards + every 4/4 Discord results card posted)
  proof/legs/*.png    Cashed Legs pages (pages 1-4 = existing site pages; new pages only when 12 new official hits fill one)
  proof/proof.json    every item {type: card|legs_page, date, title, image, legs, summary}, newest first

Idempotent + dedupes: state is the committed proof.json itself (cards deduped by date+legs signature,
legs by date|player|stat|line|side). Renders only new items; commits/pushes only when something changed.
Never posts to Discord/X. Images/JSON carry only player, stat, line, More/Less, final stat, HIT/CASHED -
no confidence, model names or sources.

Usage: sync_proof.py [--dry-run]   (dry-run: build in a temp copy, print the plan, no commit/push)
Push: git over https with `gh auth git-credential` (same gh login lib.sh/update_record.py use).
"""
from __future__ import annotations
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path("/workspace/proof")
AP = HERE / "autoproof"
BRANCH = os.environ.get("SB_STATS_BRANCH", "main")   # non-main only for end-to-end tests
CLONE = AP / ("slipbuilder-stats" if BRANCH == "main" else f"slipbuilder-stats-{BRANCH}")
OWNER, REPO = "zimmmz21", os.environ.get("SB_STATS_REPO", "slipbuilder-stats")
RAW = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"
LEDGER = os.environ.get("SB_LEDGER", "/workspace/slip-ledger.json")
ASSETS = Path("/home/box/agent-data/agents/2bf461f0-c668-495d-8532-d920b6d759af/assets")
GH = shutil.which("gh") or "/usr/local/bin/gh"
CT = ZoneInfo("America/Chicago")
PAGE_SIZE = 12
PER_PICK_ONLY = True
LEGS_TITLE = "Legs Hit" if PER_PICK_ONLY else "Cashed Legs"
TITLE_V = 2   # legs-page title version: pages rendered before the per-pick change are re-rendered once

sys.path.insert(0, str(ASSETS)); sys.path.insert(0, "/workspace/site-stats")
from render_results_card import render_results_card  # noqa: E402  gold CASHED 4/4 treatment
from update_record import official                   # noqa: E402  record.json's own definition of an official slip
from PIL import Image, ImageDraw, ImageFont           # noqa: E402

# ---------------------------------------------------------------- helpers
def fnum(v):
    """Display a number the way the cards do (184, 225.5); keep '3+' style strings."""
    if isinstance(v, str):
        try: v = float(v)
        except ValueError: return v
    v = float(v)
    return int(v) if v == int(v) else float(f"{v:g}")

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
def dlong(ds): d = datetime.date.fromisoformat(ds); return f"{d:%b} {d.day}, {d.year}"
def dshort(ds): d = datetime.date.fromisoformat(ds); return f"{d:%b} {d.day}"
def leg_key(date, l): return "|".join(str(x) for x in (date, l["player"], l["stat"], fnum(l["line"]), l["side"].title()))
def card_sig(date, legs): return date + "||" + "||".join(sorted(leg_key(date, l) for l in legs))
def leg_txt(l): return f"{l['player']} {l['stat']} {fnum(l['line'])} {l['side']} (final {fnum(l['final'])})"

def git(*a, cwd=CLONE, check=True):
    cmd = ["git", "-c", "credential.helper=", "-c", f"credential.helper=!{GH} auth git-credential",
           "-c", "user.name=SlipBuilder Stats Bot", "-c", "user.email=zimmmz21@users.noreply.github.com", *a]
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)

def ensure_clone():
    if not (CLONE / ".git").exists():
        AP.mkdir(parents=True, exist_ok=True)
        git("clone", f"https://github.com/{OWNER}/{REPO}.git", str(CLONE), cwd=AP)
    git("fetch", "-q", "origin", "main")
    base = "origin/main"
    if BRANCH != "main" and git("fetch", "-q", "origin", BRANCH, check=False).returncode == 0:
        base = f"origin/{BRANCH}"
    git("checkout", "-q", "-B", BRANCH, base)
    git("reset", "-q", "--hard", base)            # dedicated scratch clone; origin is authoritative

# ---------------------------------------------------------------- 4/4 cards
def card_candidates(slips):
    """(date, title, legs) for every 4/4 card that belongs in the gallery."""
    out = []
    for c in json.load(open(AP / "seed_cards.json")):           # the 11 cards already on the site
        out.append(dict(date=c["date"], title=c["title"], legs=c["legs"]))
    for s in slips:                                              # every 4/4 official Discord results card posted
        ps = s.get("picks") or []
        if not (official(s) and s.get("discord_results_posted") and len(ps) == 4
                and all((p.get("grade") or "").upper() == "HIT" for p in ps)):
            continue
        title = (s.get("header") or "Discord Card").split("·")[0].strip()
        m = re.search(r"Card (\d+) of (\d+)", s.get("meta") or "")
        if title.endswith("Card") and m and int(m.group(2)) > 1: title += f" {m.group(1)}"
        legs = [dict(player=p["player"], stat=p["stat"], line=fnum(p["line"]), side=str(p["side"]).title(),
                     final=fnum(p["actual"])) for p in ps]
        out.append(dict(date=str(s["date"])[:10], title=title, legs=legs))
    return out

def render_card(c, path):
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    title = next(t for t in (f"{c['title']} · {dlong(c['date'])}", f"{c['title']} · {dshort(c['date'])}", c["title"])
                 if d.textlength(t, font=f) <= 1080 - 128 or t == c["title"])
    picks = [dict(player=l["player"], stat=f"{l['stat']} {fnum(l['line'])}", side=l["side"], grade="HIT",
                  actual=str(fnum(l["final"]))) for l in c["legs"]]
    render_results_card(title=title, picks=picks, out_path=path, score_label="4/4")   # gold -> "CASHED 4/4"
    return title

# ---------------------------------------------------------------- Cashed Legs pages (same layout as pages 1-4)
# Night Forest (#07090C bg, money green #348F52; the retired neon mint (57,255,136) is never used) + brand fonts Syne/Outfit
BG, ELEV, LINE, ACCENT, MUTED, FG, SIDE_FILL = (7,9,12), (16,22,20), (34,46,40), (0x34,0x8F,0x52), (140,160,180), (236,242,248), (14,48,32)
BRAND_FONTS = Path("/workspace/google-ads-20261025/fonts")
W, CW, CH, GAP, TOP = 1080, 460, 230, 24, 210
def _font(n, b=False, title=False):
    f = BRAND_FONTS / ("Syne-700.ttf" if title else ("Outfit-700.ttf" if b else "Outfit-400.ttf"))
    if not f.exists(): raise SystemExit(f"brand font missing: {f} (substitutes are never OK)")
    return ImageFont.truetype(str(f), n)

def _side_pill(d, x, mid, side, font):
    tw = d.textlength(side, font=font); x0 = round(x); x1 = round(x + tw + 28); y0 = round(mid - 20); y1 = y0 + 40
    d.rounded_rectangle([x0, y0, x1, y1], radius=20, fill=SIDE_FILL, outline=ACCENT, width=2)
    d.text(((x0 + x1) / 2, (y0 + y1) / 2), side, font=font, fill=ACCENT, anchor="mm"); return x1

def leg_card(x):
    im = Image.new("RGB", (CW + 8, CH + 8), BG); d = ImageDraw.Draw(im)
    d.rounded_rectangle([4, 4, CW + 4, CH + 4], radius=24, fill=ELEV, outline=LINE, width=2)
    f = _font(20, True); t = "HIT"; tw = d.textlength(t, font=f)
    d.rounded_rectangle([28, 28, 28 + tw + 32, 64], radius=18, fill=ACCENT); d.text((28 + (tw + 32) / 2, 46), t, font=f, fill=BG, anchor="mm")
    lab = dlong(x["date"]); fl = _font(20)
    while d.textlength(lab, font=fl) > CW - 150: fl = _font(fl.size - 1)
    d.text((CW - 20, 46), lab, font=fl, fill=MUTED, anchor="rm")
    fp = _font(32, True)
    while d.textlength(x["player"], font=fp) > CW - 50: fp = _font(fp.size - 2, True)
    d.text((28, 84), x["player"], font=fp, fill=FG)
    body = f"{x['stat']} {fnum(x['line'])}"; fs = _font(24); fside = _font(20, True)
    while 28 + d.textlength(body, font=fs) + 10 + d.textlength(x["side"], font=fside) + 28 > CW - 8 and fs.size > 16: fs = _font(fs.size - 1)
    d.text((28, 154), body, font=fs, fill=MUTED, anchor="lm")
    _side_pill(d, 28 + d.textlength(body, font=fs) + 10, 154, x["side"], fside)
    d.text((28, 198), f"Final: {fnum(x['final'])}", font=_font(28, True), fill=ACCENT, anchor="lm")
    return im

def render_page(legs, n, path):
    cs = [leg_card(x) for x in legs]; rows = (len(cs) + 1) // 2; Hh = TOP + rows * (CH + 8 + GAP) + 70
    img = Image.new("RGB", (W, Hh), BG); d = ImageDraw.Draw(img); d.rectangle([0, 0, W, 8], fill=ACCENT)
    logo = Image.open("/workspace/xweekly/nightforest-mark-800.png").convert("RGBA").resize((72, 72), Image.LANCZOS)
    m = Image.new("L", (72, 72)); ImageDraw.Draw(m).ellipse((0, 0, 72, 72), fill=255); img.paste(logo, (64, 56), m)
    d.ellipse([64, 56, 136, 128], outline=ACCENT, width=3); d.text((160, 92), LEGS_TITLE, font=_font(48, True, title=True), fill=FG, anchor="lm")
    d.text((W - 64, 92), f"Page {n}", font=_font(22), fill=MUTED, anchor="rm")
    d.line([(64, 160), (W - 64, 160)], fill=LINE, width=2)
    for i, c in enumerate(cs): img.paste(c, (60 + (i % 2) * (CW + 8 + GAP), TOP + (i // 2) * (CH + 8 + GAP)))
    d.text((W // 2, Hh - 45), "slipbuilder.io", font=_font(20), fill=ACCENT, anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True); img.save(path)

def official_hit_pool(slips, after):
    """Unique official HIT legs dated after the seed pages' cutoff, oldest first."""
    seen, pool = set(), []
    rows = []
    for si, s in enumerate(slips):
        if not official(s): continue
        for pi, p in enumerate(s.get("picks") or []):
            if (p.get("grade") or "").upper() != "HIT" or p.get("actual") is None: continue
            ds = str(p.get("date") or s["date"])[:10]
            if ds <= after: continue
            rows.append(((ds, str(p.get("kickoff_ct") or ""), si, pi),
                         dict(date=ds, player=p["player"], stat=p["stat"], line=fnum(p["line"]),
                              side=str(p["side"]).title(), final=fnum(p["actual"]))))
    for _, l in sorted(rows, key=lambda r: r[0]):
        k = leg_key(l["date"], l)
        if k not in seen: seen.add(k); pool.append(l)
    return pool

# ---------------------------------------------------------------- main
def item_order(it): return (it["date"], it.get("page", 0) if it["type"] == "legs_page" else 0, it["id"])

def build(root: Path):
    """Update root/proof in place. Returns (changed, report)."""
    P = root / "proof"; (P / "legs").mkdir(parents=True, exist_ok=True)
    if not PER_PICK_ONLY: (P / "cards").mkdir(parents=True, exist_ok=True)
    pj = P / "proof.json"
    cur = json.loads(pj.read_text()) if pj.exists() else {}
    items = json.loads(json.dumps(cur.get("items", [])))  # deep copy: compare against the committed state
    rep = dict(new_cards=[], new_pages=[], carried_over=0)
    slips = json.load(open(LEDGER))["slips"]

    if PER_PICK_ONLY:                      # no card record in the public feed: drop card items and their images
        items = [it for it in items if it["type"] != "card"]
        if (P / "cards").exists(): shutil.rmtree(P / "cards")
    # cards
    have = {card_sig(it["date"], it["legs"]) for it in items if it["type"] == "card"}
    ids = {it["id"] for it in items}
    for c in ([] if PER_PICK_ONLY else sorted(card_candidates(slips), key=lambda c: (c["date"], c["title"]))):
        sig = card_sig(c["date"], c["legs"])
        if sig in have: continue
        cid = f"{c['date']}-{slug(c['title'])}"; n = 2
        while cid in ids: cid = f"{c['date']}-{slug(c['title'])}-{n}"; n += 1
        title = render_card(c, P / "cards" / f"{cid}.png")
        items.append(dict(type="card", id=cid, date=c["date"], title=title, image=f"{RAW}/proof/cards/{cid}.png",
                          score="4/4", summary="CASHED 4/4 · " + " · ".join(leg_txt(l) for l in c["legs"]), legs=c["legs"]))
        have.add(sig); ids.add(cid); rep["new_cards"].append(str(P / "cards" / f"{cid}.png"))

    # legs pages
    seed = json.load(open(AP / "seed_legs_pages.json"))
    pages = {it["page"]: it for it in items if it["type"] == "legs_page"}
    for sp in seed["pages"]:
        if sp["page"] in pages: continue
        dst = P / "legs" / f"cashed-legs-{sp['page']}.png"; shutil.copyfile(sp["source_png"], dst)
        items.append(page_item(sp["page"], sp["legs"])); pages[sp["page"]] = items[-1]
    on_pages = {leg_key(l["date"], l) for it in pages.values() for l in it["legs"]}
    pending = [l for l in official_hit_pool(slips, seed["cutoff_date"]) if leg_key(l["date"], l) not in on_pages]
    nxt = max(pages) + 1
    while len(pending) >= PAGE_SIZE:
        chunk, pending = pending[:PAGE_SIZE], pending[PAGE_SIZE:]
        show = [l for _, l in sorted(enumerate(chunk), key=lambda t: (t[1]["date"], -t[0]), reverse=True)]  # newest first, like pages 1-4
        path = P / "legs" / f"cashed-legs-{nxt}.png"; render_page(show, nxt, path)
        items.append(page_item(nxt, show)); rep["new_pages"].append(str(path)); nxt += 1
    if PER_PICK_ONLY:                      # one-time retitle + re-render of pages made under the old "Cashed Legs" title
        for i, it in enumerate(items):
            if it["type"] == "legs_page" and it.get("title_v") != TITLE_V:
                render_page(it["legs"], it["page"], P / "legs" / f"{it['id']}.png")
                items[i] = page_item(it["page"], it["legs"]); rep.setdefault("retitled_pages", []).append(it["page"])
    rep["carried_over"] = len(pending); rep["carried_over_legs"] = [leg_txt(l) + f" [{l['date']}]" for l in pending]

    for it in items:                       # intrinsic size so the site can reserve space (no layout shift)
        if "width" not in it:
            sub = "cards" if it["type"] == "card" else "legs"   # (no card items when PER_PICK_ONLY)
            with Image.open(P / sub / f"{it['id']}.png") as im: it["width"], it["height"] = im.size
    items.sort(key=item_order, reverse=True)
    changed = items != cur.get("items")
    if changed:
        out = dict(updated_at=datetime.datetime.now(CT).isoformat(timespec="seconds"),
                   page_size=PAGE_SIZE, counts=dict(legs_pages=sum(i["type"] == "legs_page" for i in items)),
                   items=items, legs_pages=[i["id"] for i in items if i["type"] == "legs_page"])
        if not PER_PICK_ONLY:
            out["counts"]["cards"] = sum(i["type"] == "card" for i in items); out["cards"] = [i["id"] for i in items if i["type"] == "card"]
        pj.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    rep["counts"] = dict(cards=sum(i["type"] == "card" for i in items), legs_pages=sum(i["type"] == "legs_page" for i in items))
    if PER_PICK_ONLY: assert rep["counts"]["cards"] == 0
    return changed, rep

def page_item(n, legs):
    ds = sorted(l["date"] for l in legs)
    word = "legs hit" if PER_PICK_ONLY else "cashed legs"
    return dict(type="legs_page", id=f"cashed-legs-{n}", page=n, date=ds[-1], date_from=ds[0], title_v=TITLE_V,
                title=f"{LEGS_TITLE} · Page {n}", image=f"{RAW}/proof/legs/cashed-legs-{n}.png",
                summary=f"{len(legs)} {word} · " + (dlong(ds[0]) if ds[0] == ds[-1] else f"{dshort(ds[0])} – {dlong(ds[-1])}"), legs=legs)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); a = ap.parse_args()
    # one run at a time per clone (cron backup run, post-Discord hook, manual runs all share this lock); waits up to 15 min
    import fcntl, time
    AP.mkdir(parents=True, exist_ok=True); lk = open(AP / f".sync-{BRANCH}.lock", "w"); t0 = time.time()
    while True:
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() - t0 > 900: sys.exit("sync_proof: lock wait timeout")
            time.sleep(2)
    ensure_clone()
    if a.dry_run:
        tmp = Path(tempfile.mkdtemp(prefix="proof-dry-"))
        if (CLONE / "proof").exists(): shutil.copytree(CLONE / "proof", tmp / "proof")
        changed, rep = build(tmp); rep["dry_run_dir"] = str(tmp); rep["changed"] = changed
        print(json.dumps(rep, indent=2)); return
    changed, rep = build(CLONE)
    git("add", "-A", "proof")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print(json.dumps(dict(rep, changed=False, pushed=False), indent=2)); return
    msg = f"proof: {rep['counts']['legs_pages']} legs pages (+{len(rep['new_cards'])} cards, +{len(rep['new_pages'])} pages)"
    git("commit", "-q", "-m", msg)
    for attempt in range(4):
        r = git("push", "-q", "origin", f"HEAD:{BRANCH}", check=False)
        if r.returncode == 0: break
        git("pull", "-q", "--rebase", "origin", BRANCH)  # record.json/model.json commits land via the API; proof/ never conflicts
    else:
        sys.exit("push failed: " + r.stderr[-500:])
    print(json.dumps(dict(rep, changed=True, pushed=True, commit=git("rev-parse", "HEAD").stdout.strip()), indent=2))

if __name__ == "__main__":
    main()
