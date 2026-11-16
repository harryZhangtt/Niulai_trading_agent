#!/usr/bin/env python3
"""Provider-free closure verifier; performs no sockets, subprocesses, or external effects."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def digest(p:Path):
 raw=p.read_bytes();return len(raw),hashlib.sha256(raw).hexdigest()
def main():
 closure=json.loads((Path(__file__).with_name('source-closure-v1.json')).read_text())
 assert closure['activation'] is False and closure['effects']=={'account':False,'business':False,'email':False,'non_loopback_network':False,'private_live_root':False,'provider':False}
 for item in closure['files']:
  assert digest(ROOT/item['path'])==(item['bytes'],item['sha256']),item['path']
 for item in closure['external_predecessors']:
  assert digest(ROOT/item['path'])==(item['bytes'],item['sha256']),item['path']
 schemas=ROOT/'shared/job_runtime/candidates/r6_one_off_codex_live_integration_v1/schemas'
 assert len(list(schemas.glob('*.schema.json')))==3
 print(json.dumps({'result':'PASS','files':len(closure['files']),'predecessors':len(closure['external_predecessors']),'effects':closure['effects']},sort_keys=True,separators=(',',':')))
if __name__=='__main__':main()
