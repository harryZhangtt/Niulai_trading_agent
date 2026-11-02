"""Inspect copied calculators without importing or executing their code."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
WORKSPACE = PACKAGE.parents[1]


def catalog():
    return json.loads((PACKAGE / 'manifest.json').read_text())


def checked_path(base, relative):
    path = base / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('MANIFEST_PATH_INVALID')
    if not path.resolve().is_relative_to(base.resolve()) or path.is_symlink():
        raise ValueError('MANIFEST_PATH_OUTSIDE_BOUNDARY')
    return path


def verify():
    rows = catalog()['files']
    failures = []
    for row in rows:
        for field, base in [('copy_path', PACKAGE), ('source_path', WORKSPACE)]:
            path = checked_path(base, row[field])
            if not path.is_file():
                failures.append({'path': row[field], 'code': 'FILE_MISSING'})
                continue
            raw = path.read_bytes()
            if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
                failures.append({'path': row[field], 'code': 'COPY_OR_SOURCE_CHANGED'})
            if path.suffix == '.py':
                ast.parse(raw, filename=row[field])
    return {'status': 'passed' if not failures else 'failed',
            'files_checked': len(rows), 'failures': failures,
            'scope': 'Source/copy byte parity and Python syntax only; no numerical certification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'verify'])
    args = parser.parse_args()
    if args.action == 'verify':
        result = verify()
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'passed' else 2
    value = catalog()
    print(json.dumps({'stage': value['stage'], 'production_wiring': False,
                     'numerical_certification': value['numerical_certification'],
                     'modules': [{k: row[k] for k in ('copy_path', 'capabilities', 'dependencies', 'limitations')}
                                 for row in value['files']
                                 if row['kind'] in ('calculator', 'calculator_or_support', 'validator')],
                     'missing_capabilities': value['missing_capabilities']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
