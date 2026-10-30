import argparse
import json
import os
from pathlib import Path
from shared.research_sources.artifacts import SourceError, read, save
from .requirements import freeze
from .routing import routes
from .coverage import validate
from .pipeline import finalize, complete


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description='Investment requirements snapshot, source coverage and checked completion.')
    p.add_argument('operation', choices=['freeze', 'routes', 'assess', 'finalize', 'complete'])
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    try:
        body = json.loads(a.request.read_text())
        if a.operation == 'freeze': result = freeze(body, a.out)
        elif a.operation == 'routes': result = routes(body)
        elif a.operation == 'assess': result = validate(body['contract'], body['packet'])
        elif a.operation == 'finalize':
            result = finalize(body['item'], a.out, contract=body['contract'], packet=body['packet'])
        else: result = complete(body['item'], body['run_id'], contract=body['contract'])
        print(json.dumps(result)); return 0
    except Exception as e:
        print(json.dumps({'status': 'failed', 'error': str(e) if isinstance(e, SourceError) else 'RESEARCH_SOURCE_OPERATION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
