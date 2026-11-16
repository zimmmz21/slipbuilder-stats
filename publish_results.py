#!/usr/bin/env python3
"""Publish results.json (every graded leg, hits AND misses) to zimmmz21/slipbuilder-stats
next to record.json. Same token + commit path as site-stats/update_record.py.
DEFAULT IS DRY RUN. Only commits with --publish (needs ZIMMMZ's OK; makes the file public).
Intended hook after approval: run right after update_record.py in the grading jobs."""
import base64, json, sys
sys.path.insert(0, '/workspace/site-stats'); sys.path.insert(0, '/workspace/site-stats')
import update_record as UR
from build_results import build

data = build()
if '--publish' not in sys.argv:
    json.dump(data, open('/workspace/site-stats/results.preview.json', 'w'), indent=1)
    print('DRY RUN (nothing published):', json.dumps(data['summary'])); sys.exit(0)
tok = UR.token(); owner = UR.api('GET', '/user', tok)['login']
path = f'/repos/{owner}/{UR.REPO}/contents/results.json'
cur = UR.api('GET', path + f'?ref={UR.BRANCH}', tok)
if cur:
    old = json.loads(base64.b64decode(cur['content']))
    if {k: v for k, v in old.items() if k != 'updated_at'} == {k: v for k, v in data.items() if k != 'updated_at'}:
        print('results.json unchanged'); sys.exit(0)
s = data['summary']
body = {'message': f"results: {s['legs_hit']}-{s['legs_missed']} legs",
        'content': base64.b64encode((json.dumps(data, separators=(',', ':')) + '\n').encode()).decode(), 'branch': UR.BRANCH}
if cur: body['sha'] = cur['sha']
UR.api('PUT', path, tok, body); print('committed results.json:', json.dumps(s))
