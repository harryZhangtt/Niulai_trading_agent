import argparse
import json
import os
from pathlib import Path
from .artifacts import SourceError, private_path
from .fetch import discover_openalex, discover_arxiv, fetch_arxiv, fetch_document, passages


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description='Fetch public evidence; does not mark investment requirements complete.')
    p.add_argument('operation', choices=['openalex-discover', 'arxiv-discover', 'arxiv-read', 'document-read', 'passage'])
    p.add_argument('--value', required=True, help='Public query, versioned paper ID, URL, or receipt-ref JSON')
    p.add_argument('--out', type=Path)
    p.add_argument('--start', type=int, default=0)
    p.add_argument('--max-chars', type=int, default=6000)
    a = p.parse_args()
    try:
        if a.operation == 'passage':
            result = passages(json.loads(a.value), a.start, a.max_chars)
        else:
            private_path(a.out, create=True)
            result = {'source': {'openalex-discover': discover_openalex,
                'arxiv-discover': discover_arxiv, 'arxiv-read': fetch_arxiv, 'document-read': fetch_document}[a.operation](a.value, a.out)}
        print(json.dumps(result)); return 0
    except Exception as e:
        print(json.dumps({'status': 'failed', 'error': str(e) if isinstance(e, SourceError) else 'SOURCE_OPERATION_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
