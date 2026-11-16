#!/usr/bin/env python3
"""Effect-free v3 closure verifier."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def identity(path):
 raw=path.read_bytes();return len(raw),hashlib.sha256(raw).hexdigest()
def main():
 closure=json.loads((Path(__file__).with_name('source-closure-v3.json')).read_text());assert closure['activation'] is False and not any(closure['effects'].values())
 for row in closure['files']+closure['external_predecessors']:assert identity(ROOT/row['path'])==(row['bytes'],row['sha256']),row['path']
 expected=[('1515116fdef27fe585151a3d1e2e7d81ebb94260a59219c6329b01cb8e3c62ff','OPEN_SUPERSEDED_PRESERVED'),('2f742d45199ba16abee393829a98bf28b886acb1e8df2f5a8bc92484cf2966c8','OPEN_SUPERSEDED_PRESERVED')];assert [(x['sha256'],x['status']) for x in closure['history']]==expected
 print(json.dumps({'result':'PASS','files':len(closure['files']),'predecessors':len(closure['external_predecessors']),'history':[x['status'] for x in closure['history']],'effects':closure['effects']},sort_keys=True,separators=(',',':')))
if __name__=='__main__':main()
