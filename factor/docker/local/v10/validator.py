"""Validate inert v10 health lifecycle documents."""
import json
from factor.docker.local.v10.lifecycle import PROFILE_PATH,load,validate_profile,digest,commands

def main():
 try:
  value=validate_profile(load(PROFILE_PATH));out={'valid':True,'status':value['status'],'runnable':value['runnable'],'apply_allowed':value['apply_allowed'],'profile_sha256':digest(value),'commands':commands(value)};print(json.dumps(out,sort_keys=True,separators=(',',':')));return 0
 except Exception:print(json.dumps({'valid':False,'code':'V10_INVALID'},sort_keys=True,separators=(',',':')));return 2
if __name__=='__main__':raise SystemExit(main())
