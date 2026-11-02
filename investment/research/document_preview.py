"""Bounded previews of registered local research JSON, never semantic admission.

Only the explicit freezer reads local report paths. The datasource projection
reads frozen preview refs or the already registered catalog row; it never follows
a path supplied by the browser and never writes during a read.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, INVESTMENT_STATE, SourceError, digest, require, save

DIRECTORY = SOURCE_STATE / 'runtime/document-previews'
ALLOWED_ROOTS = (ROOT / 'niulai-private/reports', ROOT / 'niulai-private/research',
                 ROOT / 'niulai-private/registered_dependencies', SOURCE_STATE / 'local-research',
                 INVESTMENT_STATE / 'local-documents')
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_CHARS = 24000
MAX_NODES = 1600
SECRET_KEY = re.compile(r'(?i)(api[_ -]?key|password|secret|authorization|credential|private[_ -]?key|access[_ -]?token|refresh[_ -]?token|cookie|^token$|account[_ -]?(?:id|number)|auth[_ -]?home|^email$|^phone$)')
SECRET_TEXT = re.compile(r'''(?i)(?:bearer\s+\S+|(?:sk|ghp|gho)[-_][A-Za-z0-9_-]{8,}|["']?(?:api[_ -]?key|token|password|secret)["']?\s*[:=]\s*["']?[^\s,"';}]+)''')
PRIVATE_PATH = re.compile(r'(?:/(?:Users|home|workspace|private|tmp|var)/[^\s<>"]+|[A-Za-z]:\\[^\s]+)')
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PEM = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', re.S)


def sanitize(value):
    visited = [0]; truncated = [False]; redacted = [0]
    def clean(item, depth=0):
        visited[0] += 1
        if visited[0] > MAX_NODES or depth > 10:
            truncated[0] = True; return '[preview truncated]'
        if isinstance(item, dict):
            result = {}
            for index, (key, val) in enumerate(item.items()):
                if index >= 100 or visited[0] >= MAX_NODES:
                    result['__preview_truncated__'] = True; truncated[0] = True; break
                key = str(key)[:160]
                if SECRET_KEY.search(key): result[key] = '[redacted]'; redacted[0] += 1
                else: result[key] = clean(val, depth + 1)
            return result
        if isinstance(item, list):
            result = [clean(val, depth + 1) for val in item[:60]]
            if len(item) > 60: result.append('[additional items truncated]'); truncated[0] = True
            return result
        if isinstance(item, str):
            cleaned = EMAIL.sub('[redacted]', PRIVATE_PATH.sub('[private path]', PEM.sub('[redacted]', SECRET_TEXT.sub('[redacted]', item))))
            if cleaned != item: redacted[0] += 1
            if len(cleaned) > 2400: cleaned = cleaned[:2400] + ' [string truncated]'; truncated[0] = True
            return cleaned
        if item is None or type(item) in (bool, int, float): return item
        return '[unsupported value]'
    result = clean(value)
    return result, {'truncated': truncated[0], 'redacted_fields': redacted[0]}


def key(roster_ref, row):
    return digest([roster_ref['sha256'], row['record_id'], row['entity']])


def metadata_preview(roster_ref, row):
    content, counts = sanitize(row.get('content'))
    catalog = row.get('content', {}).get('catalog_record', {}) if isinstance(row.get('content'), dict) else {}
    local = catalog.get('local_working_copy', {}) if isinstance(catalog, dict) else {}
    return {'schema_version': 1, 'kind': 'registered_research_document_preview',
        'catalog_sha256': roster_ref['sha256'], 'record_id': row['record_id'], 'subject': row['entity'],
        'filename': row['title'], 'status': 'missing', 'content_scope': 'catalog_metadata_not_document_body',
        'origin': 'registered_catalog_row', 'content': content, 'document_sha256': None,
        'declared_document_sha256': local.get('sha256') if isinstance(local, dict) else None,
        'document_bytes': None, 'declared_document_bytes': local.get('size_bytes') if isinstance(local, dict) else None,
        'frozen_at': None, 'original_availability': None, 'canonical_byte_identity_verified': False,
        'reason_codes': ['DOCUMENT_BODY_NOT_CAPTURED'], **counts}


def read_local_json(path, *, allowed_roots=ALLOWED_ROOTS):
    """Use no-follow directory descriptors; no path escape or symlink traversal."""
    require(isinstance(path, str), 'DOCUMENT_PREVIEW_PATH_INVALID')
    candidate = Path(path).absolute()
    require('..' not in candidate.parts and candidate.suffix.lower() == '.json', 'DOCUMENT_PREVIEW_PATH_INVALID')
    matches = [Path(root).absolute() for root in allowed_roots if candidate.is_relative_to(Path(root).absolute())]
    require(bool(matches), 'DOCUMENT_PREVIEW_PATH_NOT_ALLOWED')
    root = max(matches, key=lambda item: len(item.parts))
    require(root.is_relative_to(ROOT), 'DOCUMENT_PREVIEW_PATH_NOT_ALLOWED')
    for parent in [root, *root.parents]:
        require(not parent.is_symlink(), 'DOCUMENT_PREVIEW_SYMLINK_REJECTED')
        if parent == ROOT: break
    descriptors = []
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW); descriptors.append(descriptor)
        parts = candidate.relative_to(root).parts
        require(bool(parts), 'DOCUMENT_PREVIEW_PATH_INVALID')
        for part in parts[:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor); descriptors.append(descriptor)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor); descriptors.append(descriptor)
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_FILE_BYTES, 'DOCUMENT_PREVIEW_FILE_SIZE_INVALID')
        raw = b''
        while len(raw) <= MAX_FILE_BYTES:
            part = os.read(descriptor, min(65536, MAX_FILE_BYTES + 1 - len(raw)))
            if not part: break
            raw += part
        after = os.fstat(descriptor)
        require(len(raw) <= MAX_FILE_BYTES and before.st_ino == after.st_ino and before.st_mtime_ns == after.st_mtime_ns
                and before.st_size == after.st_size == len(raw), 'DOCUMENT_PREVIEW_FILE_CHANGED')
        return raw
    except OSError:
        raise SourceError('DOCUMENT_PREVIEW_LOCAL_COPY_UNAVAILABLE') from None
    finally:
        for descriptor in reversed(descriptors): os.close(descriptor)


def freeze(roster_ref, row, *, directory=DIRECTORY, allowed_roots=ALLOWED_ROOTS):
    """Called explicitly for a registered row; never from an HTTP read."""
    require(row.get('kind') == 'catalog_metadata' and row.get('title', '').endswith('.json'), 'DOCUMENT_PREVIEW_RECORD_UNSUPPORTED')
    record = metadata_preview(roster_ref, row)
    catalog = row.get('content', {}).get('catalog_record', {}); local = catalog.get('local_working_copy', {})
    try:
        require(isinstance(local, dict) and isinstance(local.get('path'), str)
                and Path(local['path']).name == row['title'], 'DOCUMENT_PREVIEW_LOCATOR_MISSING')
        raw = read_local_json(local['path'], allowed_roots=allowed_roots)
        fingerprint = hashlib.sha256(raw).hexdigest()
        require(local.get('sha256') == fingerprint and local.get('size_bytes') == len(raw), 'DOCUMENT_PREVIEW_SOURCE_HASH_MISMATCH')
        value = json.loads(raw.decode('utf-8')); content, counts = sanitize(value)
        record.update(status='available', content_scope='local_research_json_not_primary_source',
            origin='registered_local_working_copy', content=content, document_sha256=fingerprint,
            document_bytes=len(raw), reason_codes=[], **counts)
    except (SourceError, ValueError, UnicodeError, RecursionError) as error:
        record['reason_codes'] = [str(error) if isinstance(error, SourceError) else 'DOCUMENT_PREVIEW_JSON_INVALID']
    record['frozen_at'] = datetime.now(timezone.utc).isoformat()
    directory = Path(directory); ref = save(directory, record)
    head = directory / (key(roster_ref, row) + '.head.json')
    require(not head.is_symlink(), 'DOCUMENT_PREVIEW_HEAD_UNSAFE')
    atomic(head, ref)
    return ref


def public_preview(record, *, preview_sha256=None):
    """Redact again at the output boundary, including registered metadata."""
    content, counts = sanitize(record.get('content'))
    rendered = json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False)
    truncated = bool(record.get('truncated')) or counts['truncated'] or len(rendered) > MAX_PREVIEW_CHARS
    if len(rendered) > MAX_PREVIEW_CHARS: rendered = rendered[:MAX_PREVIEW_CHARS] + '\n… [preview truncated]'
    def fingerprint(value): return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) else None
    def byte_count(value): return value if type(value) is int and 0 <= value <= 1024 ** 4 else None
    frozen_at = record.get('frozen_at')
    try:
        if not isinstance(frozen_at, str) or len(frozen_at) > 40 or datetime.fromisoformat(frozen_at.replace('Z', '+00:00')).tzinfo is None: frozen_at = None
    except ValueError: frozen_at = None
    filename = sanitize(str(record.get('filename', '')))[0][:200]
    return {'status': record.get('status') if record.get('status') in {'available', 'missing'} else 'missing',
        'content_scope': record.get('content_scope') if record.get('content_scope') in {'catalog_metadata_not_document_body', 'local_research_json_not_primary_source'} else 'unknown',
        'origin': record.get('origin') if record.get('origin') in {'registered_catalog_row', 'registered_local_working_copy'} else 'unknown', 'filename': filename,
        'text': rendered, 'truncated': truncated, 'redacted_fields': (record.get('redacted_fields') or 0) + counts['redacted_fields'],
        'document_sha256': fingerprint(record.get('document_sha256')), 'declared_document_sha256': fingerprint(record.get('declared_document_sha256')),
        'document_bytes': byte_count(record.get('document_bytes')), 'declared_document_bytes': byte_count(record.get('declared_document_bytes')),
        'preview_sha256': fingerprint(preview_sha256), 'frozen_at': frozen_at,
        'original_availability': None, 'canonical_byte_identity_verified': False,
        'reason_codes': [value if isinstance(value, str) and re.fullmatch('[A-Z_]{1,100}', value) else 'PREVIEW_DIAGNOSTIC_UNAVAILABLE'
                         for value in record.get('reason_codes', [])[:8]]}
