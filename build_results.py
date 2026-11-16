#!/usr/bin/env python3
"""Build results.json: every graded official leg (hits AND misses) from the slip ledger.
PER-PICK ONLY (ZIMMMZ 2026-11-16, best-picks direction): the public file carries the per-pick record and the graded legs list.
No slip/card record is published: no cards_graded, no cards_cashed, no per-card results (hits/misses/result per card). Card
grading stays internal in the ledger; this file just stops publishing it.
Same filter and definitions as record.json (site-stats/update_record.py):
official Discord cards, not superseded; HIT/MISS counted, VOID listed but not counted, ungraded excluded.
DRY RUN ONLY: writes a local file. Publishing to zimmmz21/slipbuilder-stats is a separate, approved step.

  python3 build_results.py [OUT.json]
"""
import json, re, sys, datetime
sys.path.insert(0, '/workspace/site-stats')
import update_record as UR

NETWORKS = re.compile(r'\b(on\s+)?(ESPN2?|ABC|CBS|FOX|NBC|Prime Video|Amazon|Peacock|TNT|TBS|NFL Network|NFLN|Netflix|YouTube)\b', re.I)
clean = lambda s: re.sub(r'\s{2,}', ' ', NETWORKS.sub('', str(s or ''))).strip(' ·-')
SIDE = {}  # keep the card wording (More/Less), same as the site's cards

def build():
    slips = json.load(open(UR.LEDGER))['slips']
    legs = []
    for s in filter(UR.official, slips):
        for p in s.get('picks', []):
            g = p.get('grade')
            if g not in ('HIT', 'MISS', 'VOID'):
                continue  # ungraded legs are not listed or counted
            legs.append({
                'date': s.get('date'), 'nfl_week': UR.nfl_week(s),
                'player': p.get('player'), 'team': p.get('team'), 'game': clean(p.get('game_display') or p.get('game')),
                'stat': p.get('stat'), 'side': SIDE.get(p.get('side'), p.get('side')), 'line': p.get('line'),
                'confidence': p.get('conf'), 'actual': p.get('actual'), 'grade': g, 'free_pick': bool(p.get('potd')),
            })
    hit = sum(l['grade'] == 'HIT' for l in legs); miss = sum(l['grade'] == 'MISS' for l in legs)
    potd = [l for l in legs if l['free_pick'] and l['grade'] != 'VOID']
    rec = UR.compute()
    summary = {
        'legs_hit': hit, 'legs_missed': miss, 'legs_void': sum(l['grade'] == 'VOID' for l in legs),
        'legs_hit_pct': round(100 * hit / (hit + miss), 1) if hit + miss else None,
        'free_pick_hit': sum(l['grade'] == 'HIT' for l in potd), 'free_pick_missed': sum(l['grade'] == 'MISS' for l in potd),
        'by_week': {},
    }
    for l in legs:
        if l['grade'] == 'VOID': continue
        w = summary['by_week'].setdefault(str(l['nfl_week']), {'hit': 0, 'missed': 0})
        w['hit' if l['grade'] == 'HIT' else 'missed'] += 1
    assert (hit, miss) == (rec['season_w'], rec['season_l']), f'mismatch vs record.json math: {(hit, miss)} vs {rec}'
    out = {'updated_at': datetime.datetime.now(UR.CT).isoformat(timespec='seconds'),
           'definitions': 'Every official pick, graded after the game, hits and misses. Voids (player did not play) are listed, not counted.',
           'summary': summary, 'legs': sorted(legs, key=lambda l: (l['date'] or '', l['player'] or ''), reverse=True)}
    bad = NO_SLIP.search(json.dumps(out))
    assert not bad, f'slip/card record field in public results.json: {bad.group(0)}'
    return out

NO_SLIP = re.compile(r'"(cards_cashed|cards_graded|cashed_4of4|cashed|result)"|"card"\s*:')

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'results.preview.json'
    data = build()
    json.dump(data, open(out, 'w'), indent=1)
    print(out, json.dumps(data['summary']))
