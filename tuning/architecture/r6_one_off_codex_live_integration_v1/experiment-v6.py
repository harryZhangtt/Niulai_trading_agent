#!/usr/bin/env python3
"""Effect-free v6 source-closure verifier."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def identity(path):
 raw=path.read_bytes();return len(raw),hashlib.sha256(raw).hexdigest()
def main():
 closure=json.loads(Path(__file__).with_name("source-closure-v6.json").read_text())
 assert closure["activation"] is False and not any(closure["effects"].values())
 assert closure["p0_reclosure"]=="P0_V10_RECLOSURE_REQUIRED" and closure["fresh_independent_review"]=="REQUIRED_NOT_YET_PERFORMED"
 for row in closure["files"]+closure["external_predecessors"]:assert identity(ROOT/row["path"])==(row["bytes"],row["sha256"]),row["path"]
 assert all(x["status"]=="OPEN_SUPERSEDED_PRESERVED" for x in closure["history"])
 print(json.dumps({"result":"PASS","files":len(closure["files"]),"predecessors":len(closure["external_predecessors"]),"p0_reclosure":closure["p0_reclosure"],"effects":closure["effects"]},sort_keys=True,separators=(",",":")))
if __name__=="__main__":main()
