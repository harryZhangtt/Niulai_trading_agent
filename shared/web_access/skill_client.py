"""Sandbox-side closed client. This command never launches the browser itself."""
import argparse
import json
from .skill_bridge import client


def main():
    p=argparse.ArgumentParser();p.add_argument('--operation',required=True);a=p.parse_args()
    try:r=client(a.operation)
    except Exception:r={'status':'blocked','code':'SKILL_BRIDGE_CLIENT_FAILED'}
    print(json.dumps(r));return 0 if r['status']=='observed' else 2


if __name__=='__main__':raise SystemExit(main())
