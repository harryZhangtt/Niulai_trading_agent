import json
from pathlib import Path
from . import launcher

def main():
 try:p=launcher.validate_profile(launcher.load_json(launcher.PROFILE_PATH),launcher.EXPECTED_WORKSPACE)
 except (launcher.V6ContractError,OSError) as exc:print(f'INVALID {type(exc).__name__}');return 2
 print(json.dumps({'valid':True,'status':'selected-disabled','runnable':False,'apply_allowed':False,'sha256':launcher.digest(p)},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
