"""Cheap raw-record indexing over the existing immutable observation store.

An indexed note or catalog pointer is never promoted to primary-source evidence.
There is no network, model, forecast update or semantic admission in this module.
"""
import re

from .artifacts import SourceError, digest, encoded, read, require, save
from .store import Store, instant

VERSION = 'raw-index-v1.0.1'
KINDS = {'catalog_metadata', 'section_metadata', 'evidence_note', 'assessment_note', 'source_document'}
LEVELS = {'metadata_only', 'secondary_note', 'document'}


def normalize(record):
    required = {'namespace', 'record_id', 'entity', 'kind', 'title', 'source_family',
                'available_at', 'content_access', 'content'}
    require(isinstance(record, dict) and set(record) == required, 'INDEX_RECORD_SCHEMA')
    for key in ('namespace', 'record_id', 'entity', 'source_family'):
        require(isinstance(record[key], str) and 0 < len(record[key]) <= 512, 'INDEX_ID_INVALID')
    require(isinstance(record['title'], str) and len(record['title']) <= 4096, 'INDEX_TITLE_INVALID')
    require(isinstance(record['kind'], str) and record['kind'] in KINDS and
            isinstance(record['content_access'], str) and record['content_access'] in LEVELS, 'INDEX_KIND_INVALID')
    expected = ('metadata_only' if record['kind'] in {'catalog_metadata', 'section_metadata'}
                else 'document' if record['kind'] == 'source_document' else 'secondary_note')
    require(record['content_access'] == expected, 'INDEX_CONTENT_LEVEL_MISMATCH')
    require(isinstance(record['content'], (dict, str)) and bool(record['content']), 'INDEX_CONTENT_EMPTY')
    require(len(encoded(record)) <= 1024 * 1024, 'INDEX_RECORD_TOO_LARGE')
    if record['available_at'] is not None:
        instant(record['available_at'])
    entity = record['entity'].strip().upper()
    require(bool(entity), 'INDEX_ENTITY_REQUIRED')
    return {**record, 'entity': entity}


def binding(row):
    return {'observation_id': row['id'], 'revision': row['revision'],
            'lifecycle_revision': row['lifecycle_revision']}


class RecordIndex:
    def __init__(self, directory):
        self.store = Store(directory)

    def put(self, record, *, expected_revision=None):
        record = normalize(record)
        oid = 'index:' + digest([record['namespace'], record['record_id'], record['entity']])
        record_hash = digest(record)
        try:
            prior = self.store.read(oid)
        except SourceError as exc:
            if str(exc) != 'OBSERVATION_NOT_FOUND':
                raise
            prior = None
        revision = prior['revision'] if prior else 0
        require(expected_revision is None or type(expected_revision) is int and
                expected_revision == revision, 'INDEX_REVISION_CONFLICT')
        if prior and prior['payload'].get('record_hash') == record_hash:
            source = read(prior['payload']['source_ref'])
            read(source['raw'], json_value=False)  # A hit must not hide damaged bytes.
            return {'route': 'reused', 'binding': binding(prior), 'record_hash': record_hash}
        raw = save(self.store.blobs, encoded(record['content']))
        source = save(self.store.blobs, {'provider': 'local_record_index',
            'source_url': 'local-record://' + digest([record['namespace'], record['record_id']]),
            'upstream_id': record['namespace'] + ':' + record['record_id'], 'raw': raw,
            'available_at': record['available_at'],
            'access_level': record['content_access'], 'source_family': record['source_family'],
            'limitations': ['Stored record bytes, not proof of original document access or claim truth.']})
        payload = {**record, 'record_hash': record_hash, 'metric': record['kind'],
                   'source_ref': source, 'semantic_verification': 'not_performed'}
        request = 'index-put:' + digest([oid, record_hash, revision])
        try:
            row = (self.store.create(request, oid, payload) if prior is None else
                   self.store.revise(request, oid, payload, revision))
        except SourceError as exc:
            if str(exc) != 'STORE_REVISION_CONFLICT' or expected_revision is not None:
                raise
            current = self.store.read(oid)
            require(current['payload'].get('record_hash') == record_hash, 'INDEX_REVISION_CONFLICT')
            source = read(current['payload']['source_ref']); read(source['raw'], json_value=False)
            return {'route': 'reused_after_race', 'binding': binding(current), 'record_hash': record_hash}
        route = 'reused_after_race' if row.get('idempotent_replay') else ('created' if revision == 0 else 'revised')
        return {'route': route, 'binding': binding(row),
                'record_hash': record_hash}

    def select(self, *, entity, baseline_hash, requirement_id, cutoff, terms=(), limit=32):
        require(isinstance(baseline_hash, str) and re.fullmatch('[a-f0-9]{64}', baseline_hash),
                'INDEX_BASELINE_REQUIRED')
        require(isinstance(requirement_id, str) and 0 < len(requirement_id) <= 192, 'INDEX_REQUIREMENT_REQUIRED')
        require(isinstance(entity, str) and bool(entity.strip()), 'INDEX_ENTITY_REQUIRED')
        require(type(limit) is int and 1 <= limit <= 128, 'INDEX_LIMIT_INVALID')
        require(isinstance(terms, (list, tuple)) and len(terms) <= 16 and
                all(isinstance(x, str) and 0 < len(x) <= 100 for x in terms), 'INDEX_TERMS_INVALID')
        at = instant(cutoff)
        rows = self.store.find(entity=entity.strip().upper(), limit=1000)
        selected, excluded, deferred = [], [], []
        for row in rows:
            p = row['payload']
            if p.get('kind') not in KINDS:
                continue
            if p.get('available_at') is not None and instant(p['available_at']) > at:
                excluded.append({'id': row['id'], 'reason': 'available_after_cutoff'}); continue
            text = (p['title'] + ' ' + encoded(p['content']).decode()).casefold()
            if terms and not any(term.casefold() in text for term in terms):
                excluded.append({'id': row['id'], 'reason': 'terms_not_matched'}); continue
            if len(selected) < limit:
                source = read(p['source_ref']); read(source['raw'], json_value=False)
            candidate = {'binding': binding(row), 'record_hash': p['record_hash'], 'title': p['title'],
                'kind': p['kind'], 'content_access': p['content_access'], 'source_family': p['source_family'],
                'available_at': p['available_at'], 'source_ref': p['source_ref'],
                'limitations': ['semantic_support_not_reviewed'] +
                    (['availability_unknown'] if p['available_at'] is None else []) +
                    (['original_document_not_present'] if p['content_access'] != 'document' else [])}
            (selected if len(selected) < limit else deferred).append(candidate)
        context = {'id': requirement_id, 'entity': entity.strip().upper(), 'baseline_hash': baseline_hash,
                   'cutoff': cutoff, 'terms': list(terms), 'limit': limit, 'index_version': VERSION}
        return {'context': context, 'candidates': selected, 'deferred': deferred, 'excluded': excluded,
                'candidate_scan_limit_reached': len(rows) == 1000,
                'scope': 'discovery_candidates_only', 'semantic_verification': 'not_performed',
                'auto_commit_research': False}

    def checkpoint(self, request_id, selection):
        require(selection.get('scope') == 'discovery_candidates_only', 'INDEX_SELECTION_REQUIRED')
        context_ref = save(self.store.blobs, selection['context'])
        receipt_ref = save(self.store.blobs, selection)
        require(bool(selection['candidates']), 'INDEX_SELECTION_EMPTY')
        committed = self.store.commit_snapshot(request_id, context_ref,
            [candidate['binding'] for candidate in selection['candidates']])
        return {**committed, 'selection_ref': receipt_ref, 'scope': 'indexed_candidates',
                'semantic_verification': 'not_performed', 'auto_commit_research': False}
