import json, glob, sys
from datetime import datetime

path = '/opt/arss/engine/arss-protocol/evidence/eag_approvals/'
files = sorted(glob.glob(path + '*.json'))

ready = []
for f in files:
    with open(f) as fp:
        d = json.load(fp)
    if d.get('status') == 'READY':
        ready.append({'file': f, 'approval_id': d.get('approval_id')})

print(f"READY: {len(ready)}")
for r in ready:
    print(f"  - {r['approval_id']}")

if len(ready) == 0:
    print('POOL_EMPTY')
    sys.exit(1)
