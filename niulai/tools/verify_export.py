#!/usr/bin/env python3
"""Read-only integrity verification; no network or credential access."""
import hashlib,json,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[1]
m=json.loads((root/'MANIFEST.json').read_text())
bad=[]
for row in m['files']:
 p=root/row['path']
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:bad.append(row['path'])
print(json.dumps({'status':'FAIL' if bad else 'PASS','checked':len(m['files']),'mismatches':bad},indent=2))
sys.exit(bool(bad))
