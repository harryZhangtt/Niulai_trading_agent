"""Bounded read-only datasource projection for the local observability UI.

No database, source, pipeline or evaluation status is mutated. A registry may add
pinned catalog/report/temporal receipts without editing this module. Output is an
allowlisted public DTO: references and private paths never cross the boundary.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, INVESTMENT_STATE, SourceError, digest, private_path, require, save
from .information_labels import DIRECTORY as LABEL_DIRECTORY, POLICY_VERSION, classify, read_sidecar
from . import document_preview, acquisition_projection

BASE = SOURCE_STATE / 'runtime'
CATALOG = BASE / 'raw-index-integration-20261031/record.json'
NOW = BASE / 'now-contribution-e2e-20261031'
REGISTRY = INVESTMENT_STATE / 'datasource/registry.json'
MAX_READS = 512
MAX_BYTES = 64 * 1024 * 1024
METRICS = {
    'actions': ('Actions', 'count'), 'model_turns': ('Model turns', 'count'),
    'elapsed_seconds': ('Elapsed time', 'seconds'), 'wall_seconds': ('Wall time', 'seconds'),
    'tokens': ('Tokens', 'tokens'), 'cost': ('Cost', 'currency_unknown'),
    'provider_source_calls': ('Provider source calls', 'count'),
    'supported_facts': ('Supported facts', 'count'), 'total_facts': ('Total facts', 'count'),
    'fact_support': ('Source support rubric', 'rubric_0_2'),
    'baseline_novelty': ('Novelty classification accuracy rubric', 'rubric_0_2'),
    'mechanism_calibration': ('Mechanism calibration rubric', 'rubric_0_2'),
    'counterevidence': ('Counterevidence rubric', 'rubric_0_2'),
    'forecast_discipline': ('Forecast discipline rubric', 'rubric_0_2'),
    'unproved_links': ('Unproved-link reasoning rubric', 'rubric_0_2'),
    'false_novelty': ('False novelty', 'count'),
    'unsupported_forecast_revision': ('Unsupported forecast revisions', 'count'),
    'unsupported_inferences': ('Unsupported inferences', 'count'),
    'critical_error_count': ('Critical errors', 'count'), 'passed_cases': ('Passed cases', 'count'),
    'requirements': ('Requirements', 'count'), 'fulfilled': ('Fulfilled requirements', 'count'), 'unknown': ('Unknown requirement outcomes', 'count'),
    'unavailable': ('Unavailable requirements', 'count'), 'provider_calls': ('Adapter dispatches', 'adapter_dispatch'),
    'cache_hits': ('Cache hits', 'count'), 'fallbacks': ('Cache fallbacks', 'count'), 'retries': ('Retries', 'count'),
    'unique_new_units': ('Supported answer-bearing new units', 'count'),
    'supported_reference_coverage': ('Adjudicated pool coverage', 'ratio'),
    'supported_unit_precision': ('Passage support precision', 'ratio'),
    'search_items': ('Search items', 'count'), 'open_items': ('Open items', 'count'),
    'provider_items': ('Provider logical items', 'count'), 'cache_attempts': ('Cache receipts', 'count'),
    'eligible_sources': ('Screened source captures', 'count'), 'proposed_units': ('Extracted units', 'count'),
    'judged_units': ('Reviewed units', 'count'), 'original_lineages': ('Original lineages', 'count'),
    'facet_coverage': ('Broad topic coverage', 'ratio'), 'redundancy': ('Within-arm redundancy', 'ratio'),
    'detection_lag_seconds': ('Detection lag', 'seconds'),
}
METRIC_CAVEATS = {
    'baseline_novelty': 'Correct known/refined/new/contrary classification on a fixed evidence packet. This does not measure acquired information richness or retrieval improvement.',
    'unproved_links': 'Ordinal 0–2 missing-link reasoning score, not the number of links identified.',
    'unique_new_units': 'Deduplicated against the six-unit common baseline at the stated epistemic role; support does not certify independent truth.',
    'supported_reference_coverage': 'Coverage of the jointly collected, adjudicated pool; not recall against all available knowledge.',
    'facet_coverage': 'At least one answer-bearing unit touches each broad topic; this does not resolve every underlying gap.',
}
TOKEN = re.compile(r'(?i)(?:bearer\s+\S+|(?:sk|ghp|gho)[-_][A-Za-z0-9_-]{8,}|(?:api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]+)')
PATH = re.compile(r'(?:/(?:Users|home|workspace|private|tmp|var)/[^\s<>"]+|[A-Za-z]:\\[^\s]+)')
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')


def text(value, maximum=320):
    if not isinstance(value, str): return None
    value = EMAIL.sub('[redacted]', TOKEN.sub('[redacted]', PATH.sub('[private path]', value)))
    value = ''.join(c for c in value if c >= ' ' and c != '\x7f')
    return value[:maximum]


def identifier(value, fallback='unknown'):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:@-]{0,95}', value) else fallback


def sha(value):
    return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) else None


def timestamp(value):
    if not isinstance(value, str): return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None and len(value) != 10: return None
        return value if len(value) <= 40 else None
    except ValueError: return None


def url(value):
    if not isinstance(value, str) or len(value) > 2000: return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        if parsed.scheme not in {'https', 'http'} or parsed.username or parsed.password or not host: return None
        if host in {'localhost', '127.0.0.1', '::1'} or host.endswith(('.local', '.internal')): return None
        try:
            if not ipaddress.ip_address(host).is_global: return None
        except ValueError: pass
        if TOKEN.search(unquote(value)) or EMAIL.search(unquote(parsed.path)) or PATH.search(unquote(parsed.path)): return None
        # Public source links never need credential-bearing queries/fragments.
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError: return None


def numeric_metrics(value):
    return {key: number if type(number) in (int, float) and math.isfinite(number) else None
            for key, number in (value or {}).items() if key in METRICS} if isinstance(value, dict) else {}


def aggregate(rows):
    keys = sorted(set().union(*(row.keys() for row in rows))) if rows else []
    result = {}
    for key in keys:
        known = [row[key] for row in rows if type(row.get(key)) in (int, float)]
        result[key] = {'sum': sum(known) if known else None, 'mean': sum(known) / len(known) if known else None,
                       'known': len(known), 'unknown': len(rows) - len(known), 'denominator': len(rows),
                       'unit': METRICS.get(key, ('', 'unknown'))[1]}
    return result


class Reader:
    """Cache immutable refs; double-check mutable heads for a coherent response."""
    def __init__(self):
        self.cache = {}; self.heads = {}; self.warnings = Counter(); self.bytes = 0

    def file(self, path, *, immutable=False, json_value=True):
        path = private_path(path)
        if path in self.cache:
            return json.loads(self.cache[path][1]) if json_value else self.cache[path][1]
        require(len(self.cache) < MAX_READS, 'PROJECTION_READ_BUDGET')
        require(path.is_file() and not path.is_symlink(), 'PROJECTION_FILE_UNAVAILABLE')
        require(path.stat().st_size <= 8 * 1024 * 1024, 'PROJECTION_FILE_TOO_LARGE')
        raw = path.read_bytes(); self.bytes += len(raw)
        require(self.bytes <= MAX_BYTES, 'PROJECTION_BYTE_BUDGET')
        fingerprint = hashlib.sha256(raw).hexdigest()
        self.cache[path] = (fingerprint, raw)
        if not immutable: self.heads[path] = fingerprint
        return json.loads(raw) if json_value else raw

    def ref(self, ref, *, json_value=True):
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'} and sha(ref['sha256']), 'PROJECTION_REF_INVALID')
        path = private_path(ref['path']); value = self.file(path, immutable=True, json_value=json_value)
        require(self.cache[path][0] == ref['sha256'], 'PROJECTION_HASH_MISMATCH')
        return value

    def optional(self, operation, code):
        try: return operation()
        except (SourceError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            self.warnings[code] += 1
            return None

    def coherent(self):
        for path, fingerprint in self.heads.items():
            require(hashlib.sha256(path.read_bytes()).hexdigest() == fingerprint, 'PROJECTION_SNAPSHOT_CHANGED')


def bounded_files(directory, maximum=64, suffix='.json'):
    if not directory.exists(): return []
    private_path(directory)
    result = []
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            require(index < maximum + 32, 'PROJECTION_SCAN_BUDGET')
            if entry.name.endswith(suffix) and entry.is_file(follow_symlinks=False): result.append(Path(entry.path))
            require(len(result) <= maximum, 'PROJECTION_SCAN_BUDGET')
    return sorted(result)


def source_dto(receipt, source_ref, subject, *, persisted=None):
    label = persisted['label'] if persisted else classify(receipt, source_ref)
    public_url = url(receipt.get('source_url'))
    parsed = urlsplit(public_url) if public_url else None
    segments = [part for part in parsed.path.split('/') if part and not part.isdigit() and part.lower() not in {'default.aspx', 'index.html', 'ta-p'}] if parsed else []
    title = text(receipt.get('title')) or (unquote(segments[-1]).replace('-', ' ') if segments else 'Captured source')
    title = text(title) or 'Captured source'
    return {'id': 'src_' + source_ref['sha256'], 'title': title, 'url': public_url, 'subject': subject,
            'scope': 'source_capture', 'content_access': identifier(receipt.get('access_level')),
            'source_sha256': source_ref['sha256'],
            'version_sha256': digest([receipt.get('source_version'), receipt.get('raw'), receipt.get('text')]),
            'timestamps': {'published_at': timestamp(receipt.get('published_at')), 'available_at': timestamp(receipt.get('available_at')),
                'fetched_at': timestamp(receipt.get('retrieved_at')), 'recorded_at': timestamp(persisted.get('recorded_at')) if persisted else None},
            'labels': {'scope': 'document', **{key: label[key] for key in ('publisher_kind', 'perspectives', 'document_type', 'topics', 'epistemic_status')},
                'annotation_status': label['annotation']['status'], 'policy_version': identifier(label['annotation']['policy_version']),
                'policy_sha256': persisted.get('policy_sha256') if persisted else None,
                'provenance_status': 'hash_bound_capture' if persisted else 'receipt_hash_checked_capture_not_rechecked',
                'persistence': 'immutable_sidecar' if persisted else 'projection_only'},
            'temporal': {'cutoff': None, 'status': 'not_evaluated', 'reason_codes': ['NO_TEMPORAL_GUARD_RECEIPT'],
                'worker_visible': None, 'basis': None, 'view': 'reviewer_diagnostic',
                'semantics': 'source_version_at_displayed_cutoff'}, 'temporal_checks': [],
            'run_ids': [], 'limitations': ['Labels do not admit evidence or certify truth.',
                *[text(item, 400) for item in receipt.get('limitations', [])[:6] if isinstance(item, str)]]}


def catalog_preview(reader, row, roster_ref):
    record = document_preview.metadata_preview(roster_ref, row); preview_hash = None
    head = document_preview.DIRECTORY / (document_preview.key(roster_ref, row) + '.head.json')
    if reader is not None and head.exists():
        def frozen():
            ref = reader.file(head); value = reader.ref(ref)
            require(value.get('kind') == 'registered_research_document_preview'
                    and value.get('catalog_sha256') == roster_ref['sha256'] and value.get('record_id') == row['record_id']
                    and value.get('subject') == row['entity'], 'DOCUMENT_PREVIEW_CATALOG_BINDING_INVALID')
            return value, ref['sha256']
        result = reader.optional(frozen, 'DOCUMENT_PREVIEW_UNAVAILABLE')
        if result: record, preview_hash = result
    return document_preview.public_preview(record, preview_sha256=preview_hash)


def catalog_dto(row, roster_ref, reader=None):
    content = row.get('content', {}); metadata = content.get('catalog_record', {})
    family = row.get('kind', 'unknown'); note = content.get('note', {})
    return {'id': 'cat_' + digest([roster_ref['sha256'], row.get('record_id'), row.get('entity')]),
        'title': text(row.get('title')) or 'Catalog record', 'url': url(metadata.get('url') or note.get('source_url')),
        'subject': identifier(row.get('entity')), 'scope': identifier(family),
        'content_access': identifier(row.get('content_access')), 'source_sha256': roster_ref['sha256'],
        'version_sha256': digest(row), 'timestamps': {'published_at': None, 'available_at': timestamp(row.get('available_at')),
            'fetched_at': None, 'recorded_at': timestamp(metadata.get('created_at'))},
        'labels': {'publisher_kind': 'unknown', 'perspectives': ['unknown'], 'document_type': 'unknown',
            'topics': ['unclassified'], 'epistemic_status': 'mixed' if family == 'assessment_note' else 'unknown',
            'annotation_status': 'provisional', 'policy_version': POLICY_VERSION, 'provenance_status': 'catalog_metadata_only', 'persistence': 'projection_only'},
        'temporal': {'cutoff': None, 'status': 'unknown', 'reason_codes': ['CATALOG_NOT_ORIGINAL_SOURCE'],
            'worker_visible': None, 'basis': None, 'view': 'reviewer_diagnostic',
                'semantics': 'source_version_at_displayed_cutoff'}, 'temporal_checks': [],
        'local_preview': catalog_preview(reader, row, roster_ref) if row.get('title', '').lower().endswith('.json') else None,
        'run_ids': [], 'limitations': ['Catalog association only; original report bytes, availability and support are unverified.']}


def freeze_catalog_preview(*, subject, title):
    """Explicit local operation over registered rosters, never a file endpoint."""
    require(isinstance(subject, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', subject)
            and isinstance(title, str) and len(title) <= 200 and Path(title).name == title and title.endswith('.json'),
            'DOCUMENT_PREVIEW_REQUEST_INVALID')
    reader = Reader(); registry = _registry(reader); refs = list(registry.get('catalog_refs', []))
    if CATALOG.exists():
        marker = reader.file(CATALOG)
        if marker.get('roster_ref'): refs.append(marker['roster_ref'])
    found = {}; seen = set()
    for ref in refs:
        if ref['sha256'] in seen: continue
        seen.add(ref['sha256']); roster = reader.ref(ref)
        require(isinstance(roster.get('records'), list) and len(roster['records']) <= 12000, 'PROJECTION_CATALOG_LIMIT')
        for row in roster['records']:
            if row.get('entity') == subject.upper() and row.get('title') == title and row.get('kind') == 'catalog_metadata':
                found[document_preview.key(ref, row)] = (ref, row)
    require(len(found) == 1, 'DOCUMENT_PREVIEW_REGISTERED_ROW_REQUIRED')
    ref, row = next(iter(found.values())); reader.coherent()
    preview_ref = document_preview.freeze(ref, row, directory=document_preview.DIRECTORY)
    return {'source_id': 'cat_' + document_preview.key(ref, row), 'preview_ref': preview_ref,
            'status': catalog_preview(Reader(), row, ref)['status'], 'scope': 'local_preview_not_historical_eligibility'}


def pipeline_dto(reader, report_ref, *, subject, query=None):
    report = reader.ref(report_ref)
    require(isinstance(report, dict) and {'run_id', 'pipeline_id', 'input_manifest', 'status'} <= report.keys(), 'PROJECTION_REPORT_INVALID')
    config_ref = report['input_manifest'].get('config_ref')
    config = reader.ref(config_ref) if config_ref else {}
    elapsed = None
    try:
        elapsed = (datetime.fromisoformat(report['finished_at']) - datetime.fromisoformat(report['started_at'])).total_seconds()
    except (KeyError, TypeError, ValueError): pass
    metrics = {**numeric_metrics(report.get('counts')), 'elapsed_seconds': elapsed, 'tokens': None, 'cost': None}
    phases = []
    for phase in config.get('phases', [])[:16]:
        phases.append({'id': identifier(phase.get('id')), 'status': 'completed' if phase.get('id') in report.get('phases', {}) else 'not_completed',
                       'mode': phase.get('mode') if phase.get('mode') in {'agent', 'action'} else None,
                       'action': identifier(phase.get('action'), None)})
    scripts = []
    if report.get('checkpoint_ref'):
        checkpoint = reader.optional(lambda: reader.ref(report['checkpoint_ref']), 'CHECKPOINT_UNAVAILABLE')
        if checkpoint and sha(checkpoint.get('executor_sha256')): scripts.append({'id': 'investment.research.execution', 'sha256': checkpoint['executor_sha256']})
    output = reader.optional(lambda: query_output(reader, report), 'QUERY_OUTPUT_UNAVAILABLE') if report.get('final_ref') else None
    return {'id': 'run_' + report_ref['sha256'], 'execution_id': identifier(report.get('run_id'), None),
        'query': text(query, 800) or 'Query text unavailable in this receipt', 'subject': subject,
        'pipeline_id': identifier(report.get('pipeline_id')), 'pipeline_version': identifier(report.get('pipeline_version')),
        'config_sha256': sha(config_ref.get('sha256')) if config_ref else None,
        'status': identifier(report.get('status')), 'scope': identifier(report.get('completion_scope')),
        'started_at': timestamp(report.get('started_at')), 'finished_at': timestamp(report.get('finished_at')),
        'script_versions': scripts, 'phases': phases, 'metrics': metrics, 'source_ids': [], 'output': output,
        'temporal': {'cutoff': None, 'status': 'not_evaluated', 'execution_id': identifier(report.get('run_id'), None),
            'report_sha256': report_ref['sha256'], 'diagnostic_sha256': None, 'semantics': 'run_bound_diagnostic',
            'reason_codes': ['NO_RUN_BOUND_TEMPORAL_RECEIPT'], 'source_decisions': []}}


def query_output(reader, report):
    final = reader.ref(report['final_ref'])
    if not isinstance(final, dict) or final.get('kind') != 'datasource_query_snapshot': return None
    require(final.get('execution_id') == report['run_id'], 'PROJECTION_QUERY_OUTPUT_RUN_MISMATCH')
    catalog_ref = final['catalog_ref']; catalog = reader.ref(catalog_ref)
    require(isinstance(catalog, dict) and isinstance(catalog.get('proposal'), dict), 'PROJECTION_QUERY_CATALOG_INVALID')
    questions = catalog['proposal'].get('questions')
    require(isinstance(questions, list) and len(questions) <= 6, 'PROJECTION_QUERY_QUESTION_LIMIT')
    public_questions = []
    for row in questions:
        require(isinstance(row, dict) and row.get('priority') in {'required', 'optional', 'exploration'}
                and isinstance(row.get('question'), str), 'PROJECTION_QUERY_QUESTION_INVALID')
        public_questions.append({'id': identifier(row.get('id')), 'facet': identifier(row.get('facet')),
            'question': text(row['question'], 1800), 'priority': row['priority']})
    pinned_sources = final.get('source_refs')
    require(isinstance(pinned_sources, list) and 0 < len(pinned_sources) <= 32, 'PROJECTION_QUERY_SOURCE_INVALID')
    source_hashes = set()
    for ref in pinned_sources:
        reader.ref(ref); source_hashes.add(ref['sha256'])
    refs = final.get('observation_refs')
    require(isinstance(refs, list) and len(refs) <= 4, 'PROJECTION_QUERY_OBSERVATION_LIMIT')
    observations = []
    for ref in refs:
        record = reader.ref(ref)
        require(isinstance(record, dict) and record.get('kind') == 'datasource_query_observation', 'PROJECTION_QUERY_OBSERVATION_INVALID')
        source_ref = record.get('source_ref'); observation = record.get('observation')
        require(isinstance(source_ref, dict) and source_ref.get('sha256') in source_hashes and isinstance(observation, dict)
                and observation.get('source_id') == source_ref['sha256'], 'PROJECTION_QUERY_OBSERVATION_SOURCE_MISMATCH')
        reader.ref(source_ref)
        require(isinstance(observation.get('quote'), str) and observation.get('claim') == observation['quote']
                and observation.get('epistemic_status') in {'reported_actual', 'measured_result', 'contractual_definition',
                    'management_target', 'author_opinion', 'unknown'}, 'PROJECTION_QUERY_OBSERVATION_SHAPE_INVALID')
        topics = observation.get('topics')
        require(isinstance(topics, list) and len(topics) <= 6 and all(isinstance(topic, str) and
                re.fullmatch(r'[a-z][a-z0-9_.-]{0,79}', topic) for topic in topics), 'PROJECTION_QUERY_TOPICS_INVALID')
        observations.append({'source_sha256': source_ref['sha256'], 'quote': text(observation['quote'], 800),
            'epistemic_status': observation['epistemic_status'], 'topics': [text(topic, 80) for topic in topics]})
    return {'summary': 'Source-grounded quotations and provisional catalog', 'catalog_sha256': catalog_ref['sha256'],
            'questions': public_questions, 'observations': observations, 'annotation_status': 'provisional',
            'scope': 'not_semantic_admission'}


def temporal_decisions(reader, diagnostic_ref):
    diagnostic = reader.ref(diagnostic_ref)
    require(isinstance(diagnostic, dict) and diagnostic.get('view') == 'reviewer_diagnostic', 'PROJECTION_TEMPORAL_DIAGNOSTIC_INVALID')
    rows = diagnostic.get('sources', [])
    require(isinstance(rows, list) and len(rows) <= 256, 'PROJECTION_TEMPORAL_DIAGNOSTIC_LIMIT')
    decisions = []
    for row in rows:
        if not isinstance(row, dict) or not sha(row.get('source_sha256')): continue
        if row.get('status') not in {'eligible', 'blocked', 'unknown', 'qualified_reconstruction'}: continue
        source_ref = row.get('source_ref')
        require(isinstance(source_ref, dict) and source_ref.get('sha256') == row['source_sha256'], 'PROJECTION_TEMPORAL_SOURCE_MISMATCH')
        decisions.append({'source_sha256': row['source_sha256'], 'view': 'reviewer_diagnostic',
            'cutoff': timestamp(row.get('cutoff') or diagnostic.get('cutoff')), 'status': row['status'],
            'reason_codes': [identifier(code) for code in row.get('reason_codes', [])[:12]],
            'worker_visible': row.get('worker_visible') if type(row.get('worker_visible')) is bool else None,
            'basis': text(row.get('basis'))})
    return diagnostic, decisions


def run_temporal(reader, report_ref, diagnostic_ref, declared_sources):
    report = reader.ref(report_ref)
    require(isinstance(report.get('final_ref'), dict), 'PROJECTION_RUN_TEMPORAL_BINDING_MISSING')
    final = reader.ref(report['final_ref'])
    require(final.get('execution_id') == report['run_id'] and final.get('temporal_diagnostic_ref') == diagnostic_ref,
            'PROJECTION_RUN_TEMPORAL_BINDING_MISMATCH')
    pinned = final.get('source_refs')
    require(isinstance(pinned, list) and 0 < len(pinned) <= 32, 'PROJECTION_RUN_TEMPORAL_SOURCES_MISSING')
    source_hashes = set()
    for ref in pinned:
        source = reader.ref(ref)
        require(isinstance(source, dict) and {'source_url', 'provider'} <= source.keys(), 'PROJECTION_RUN_TEMPORAL_SOURCE_INVALID')
        source_hashes.add(ref['sha256'])
    require(source_hashes <= set(declared_sources), 'PROJECTION_RUN_TEMPORAL_SOURCE_MISMATCH')
    diagnostic, decisions = temporal_decisions(reader, diagnostic_ref)
    require(diagnostic.get('execution_id') in (None, report['run_id']), 'PROJECTION_RUN_TEMPORAL_EXECUTION_MISMATCH')
    by_hash = {row['source_sha256']: row for row in decisions}
    require(source_hashes <= by_hash.keys(), 'PROJECTION_RUN_TEMPORAL_DECISIONS_MISSING')
    return {'cutoff': timestamp(diagnostic.get('cutoff')), 'status': 'guarded', 'execution_id': identifier(report['run_id'], None),
        'report_sha256': report_ref['sha256'], 'diagnostic_sha256': diagnostic_ref['sha256'],
        'semantics': 'run_bound_diagnostic', 'reason_codes': ['EXACT_FINAL_SNAPSHOT_GUARD_BINDING'],
        'source_decisions': [by_hash[key] for key in sorted(source_hashes)]}


def proposal_summary(reader, output_ref, case_id):
    submission = reader.ref(output_ref)
    require(isinstance(submission, dict) and isinstance(submission.get('case_result_ref'), dict), 'PROJECTION_SUMMARY_SUBMISSION_INVALID')
    case = reader.ref(submission['case_result_ref'])
    require(case.get('case_id') == case_id, 'PROJECTION_SUMMARY_CASE_MISMATCH')
    proposal = reader.ref(case['proposal_ref'])
    require(proposal.get('entity') == 'NOW' and proposal.get('case_id') == case_id, 'PROJECTION_SUMMARY_BINDING_INVALID')
    contribution = proposal.get('incremental_contribution')
    explanation = contribution.get('explanation') if isinstance(contribution, dict) else None
    return {'incremental_contribution': text(explanation, 1800),
            'economic_inference': text(proposal.get('economic_inference'), 1800),
            'unproved_links': [text(link, 500) for link in proposal.get('unproved_links', [])[:8] if isinstance(link, str)]}


def batch_dto(reader, batch_ref, *, subject, labels=None):
    """Project only hash-bound acquisition manifests; no acquisition is executed."""
    manifest = reader.ref(batch_ref)
    require(isinstance(manifest, dict) and manifest.get('kind') == 'acquisition_batch'
            and manifest.get('schema_version') == 1, 'PROJECTION_BATCH_KIND_INVALID')
    execution_id = identifier(manifest.get('execution_id'), None)
    require(execution_id is not None and manifest.get('status') in {'completed', 'partial', 'failed', 'unknown', 'interrupted'}, 'PROJECTION_BATCH_IDENTITY_INVALID')
    subjects = manifest.get('subjects')
    require(isinstance(subjects, list) and 0 < len(subjects) <= 32 and subject in subjects
            and all(identifier(item, None) == item for item in subjects), 'PROJECTION_BATCH_SUBJECT_INVALID')
    config_ref = manifest.get('config_ref'); config = reader.ref(config_ref)
    require(isinstance(config, dict) and config.get('schema_version') == 1
            and manifest.get('config_sha256') == config_ref['sha256']
            and config.get('batch_id') == manifest.get('batch_id')
            and config.get('query') == manifest.get('query'), 'PROJECTION_BATCH_CONFIG_BINDING_INVALID')
    requirements = config.get('requirements'); budget = config.get('budget')
    require(isinstance(requirements, list) and 0 < len(requirements) <= 32 and isinstance(budget, dict), 'PROJECTION_BATCH_CONFIG_INVALID')
    by_id = {}
    public_config = []
    for item in requirements:
        rid = identifier(item.get('id'), None) if isinstance(item, dict) else None
        require(rid is not None and rid not in by_id and item.get('subject') in subjects
                and item.get('access') in {'document', 'metadata'}, 'PROJECTION_BATCH_REQUIREMENT_INVALID')
        routes = item.get('routes')
        require(isinstance(routes, list) and 0 < len(routes) <= 3, 'PROJECTION_BATCH_ROUTE_LIMIT')
        public_routes = []
        for route in routes:
            require(isinstance(route, dict) and identifier(route.get('capability'), None) is not None
                    and isinstance(route.get('parameters'), dict), 'PROJECTION_BATCH_ROUTE_INVALID')
            params = route['parameters']; public_params = {}
            for key in ['url', 'paper_id', 'query']:
                if key in params:
                    public_params[key] = url(params[key]) if key == 'url' else text(params[key], 800)
            public_routes.append({'capability': route['capability'], 'parameters': public_params})
        by_id[rid] = item
        public_config.append({'id': rid, 'subject': item['subject'], 'access': item['access'], 'routes': public_routes,
            **{key: item.get(key) if type(item.get(key)) in (int, float) and math.isfinite(item[key]) and item[key] >= 0 else None
               for key in ['max_attempts', 'cache_max_age_seconds', 'timeout_seconds']}})
    result_refs = manifest.get('requirement_result_refs'); source_refs = manifest.get('source_refs'); observation_refs = manifest.get('observation_refs')
    require(isinstance(result_refs, list) and len(result_refs) == len(requirements)
            and isinstance(source_refs, list) and len(source_refs) <= 32
            and isinstance(observation_refs, list) and len(observation_refs) <= 32, 'PROJECTION_BATCH_REF_LIMIT')
    pinned_sources = {}
    for ref in source_refs:
        source = reader.ref(ref)
        require(isinstance(source, dict) and {'provider', 'source_url'} <= source.keys(), 'PROJECTION_BATCH_SOURCE_INVALID')
        pinned_sources[ref['sha256']] = (ref, source)
    for ref in observation_refs: reader.ref(ref)
    rows = []; seen = set(); source_subjects = {}; attempt_hashes = set(); total_fulfilled = 0
    for ref in result_refs:
        result = reader.ref(ref); rid = result.get('requirement_id') if isinstance(result, dict) else None
        require(isinstance(result, dict) and result.get('kind') == 'acquisition_requirement_result'
                and result.get('execution_id') == execution_id and rid in by_id and rid not in seen
                and result.get('subject') == by_id[rid]['subject']
                and result.get('status') in {'available', 'unavailable', 'unknown'}, 'PROJECTION_BATCH_RESULT_BINDING_INVALID')
        seen.add(rid); selected = result.get('selected_source_ref')
        if selected is not None:
            reader.ref(selected)
            require(selected['sha256'] in pinned_sources and result['status'] == 'available', 'PROJECTION_BATCH_SELECTED_SOURCE_INVALID')
            source_subjects.setdefault(selected['sha256'], set()).add(result['subject']); total_fulfilled += 1
        else:
            require(result['status'] != 'available', 'PROJECTION_BATCH_AVAILABLE_SOURCE_MISSING')
        refs = result.get('attempt_refs')
        require(isinstance(refs, list) and len(refs) <= 6, 'PROJECTION_BATCH_ATTEMPT_LIMIT')
        attempts = []
        for attempt_ref in refs:
            attempt = reader.ref(attempt_ref)
            require(isinstance(attempt, dict) and attempt.get('kind') == 'acquisition_attempt'
                    and attempt.get('execution_id') == execution_id and attempt.get('requirement_id') == rid,
                    'PROJECTION_BATCH_ATTEMPT_BINDING_INVALID')
            attempt_hashes.add(attempt_ref['sha256'])
            attempts.append({'ordinal': attempt.get('ordinal') if type(attempt.get('ordinal')) is int else None,
                'capability': identifier(attempt.get('capability')), 'status': identifier(attempt.get('status')),
                'route': identifier(attempt.get('route'), None), 'fetch_key_sha256': sha(attempt.get('fetch_key_sha256')),
                'fetch_executed': attempt.get('fetch_executed') if type(attempt.get('fetch_executed')) is bool else None,
                'cache_hit': attempt.get('cache_hit') if type(attempt.get('cache_hit')) is bool else None,
                'reasons': [identifier(reason) for reason in attempt.get('reasons', [])[:12] if isinstance(reason, str)],
                'started_at': timestamp(attempt.get('started_at')), 'finished_at': timestamp(attempt.get('finished_at')),
                'receipt_sha256': attempt_ref['sha256'],
                'action_execution_sha256': sha(attempt.get('action_execution_ref', {}).get('sha256')) if isinstance(attempt.get('action_execution_ref'), dict) else None})
        if result['subject'] == subject:
            rows.append({'id': rid, 'subject': subject, 'status': result['status'],
                'source_id': 'src_' + selected['sha256'] if selected else None, 'route': identifier(result.get('route'), None),
                'cache_hit': result.get('cache_hit') if type(result.get('cache_hit')) is bool else None,
                'reasons': [identifier(reason) for reason in result.get('reasons', [])[:12] if isinstance(reason, str)],
                'elapsed_seconds': result.get('elapsed_seconds') if type(result.get('elapsed_seconds')) in (int, float) and math.isfinite(result['elapsed_seconds']) else None,
                'attempts': attempts, 'receipt_sha256': ref['sha256']})
    require(seen == set(by_id), 'PROJECTION_BATCH_RESULTS_INCOMPLETE')
    require(set(source_subjects) == set(pinned_sources), 'PROJECTION_BATCH_SOURCE_ASSOCIATION_INVALID')
    counts = manifest.get('counts')
    require(isinstance(counts, dict) and all(type(counts.get(key)) is int and counts[key] >= 0
            for key in ['requirements', 'fulfilled', 'unavailable', 'unknown', 'provider_calls', 'cache_hits', 'fallbacks', 'retries'])
            and counts['requirements'] == len(requirements) and counts['fulfilled'] == total_fulfilled
            and counts['fulfilled'] + counts['unavailable'] + counts['unknown'] == len(requirements),
            'PROJECTION_BATCH_COUNTS_INVALID')
    require(manifest.get('counting_unit') == 'adapter_dispatch' and manifest.get('http_requests') is None,
            'PROJECTION_BATCH_COUNTING_UNIT_INVALID')
    retention = manifest.get('retention')
    require(isinstance(retention, dict) and retention.get('snapshots') == 'retain_until_explicit_gc'
            and retention.get('cache_is_disposable_index') is True, 'PROJECTION_BATCH_RETENTION_INVALID')
    source_rows = [source_dto(source, ref, subject, persisted=(labels or {}).get(key)) for key, (ref, source) in pinned_sources.items()
                   if subject in source_subjects[key]]
    metrics = {**numeric_metrics(counts), 'elapsed_seconds': None, 'tokens': None, 'cost': None}
    elapsed = manifest.get('elapsed_seconds')
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0: metrics['elapsed_seconds'] = elapsed
    scripts = [{'id': identifier(row.get('id')), 'sha256': sha(row.get('sha256'))}
               for row in manifest.get('script_versions', [])[:16] if isinstance(row, dict)]
    return {'id': 'batch_' + batch_ref['sha256'], 'execution_id': execution_id, 'batch_id': identifier(manifest.get('batch_id')),
        'query': text(manifest.get('query'), 1800), 'subjects': subjects, 'version': identifier(manifest.get('version')),
        'status': manifest['status'], 'scope': 'acquisition_only_not_semantic_admission',
        'manifest_sha256': batch_ref['sha256'], 'config_sha256': config_ref['sha256'],
        'capability_catalog_sha256': sha(manifest.get('capability_catalog_sha256')), 'script_versions': scripts,
        'started_at': timestamp(manifest.get('started_at')), 'finished_at': timestamp(manifest.get('finished_at')),
        'metrics': metrics, 'metrics_scope': 'whole_batch', 'counting_unit': 'adapter_dispatch', 'http_requests': None,
        'configuration': {'requirements': public_config, 'budget': {key: budget.get(key) if type(budget.get(key)) in (int, float)
            and math.isfinite(budget[key]) and budget[key] >= 0 else None for key in ['deadline_seconds', 'max_workers', 'max_provider_calls']}},
        'requirements': rows, 'requirements_scope': 'requested_subject', 'source_ids': [row['id'] for row in source_rows],
        'retention': {'snapshots': retention['snapshots'], 'cache_is_disposable_index': True, 'manifest_receipts': 1,
            'configuration_receipts': 1, 'requirement_receipts': len(result_refs), 'attempt_receipts': len(attempt_hashes),
            'source_receipts': len(pinned_sources), 'observation_receipts': len(observation_refs),
            'scope': 'hash_checked_receipts_not_storage_inventory'},
        'limitations': ['Acquisition outcomes and provisional source labels do not establish semantic admission or investment quality.',
            'Provider calls count adapter dispatches, not HTTP requests. HTTP request counts are unknown.',
            'Source labels are current annotations on pinned captures, not labels frozen in the batch manifest.',
            'Retention counts cover hash-checked manifest and receipt references, not a global storage inventory.']}, source_rows


def comparison_runtime(reader, output_ref, case_id):
    submission = reader.ref(output_ref); case_ref = submission['case_result_ref']; case = reader.ref(case_ref)
    require(isinstance(case, dict) and case.get('case_id') == case_id, 'PROJECTION_COMPARISON_RUNTIME_CASE_MISMATCH')
    packet = reader.ref(case['packet_ref']); proposal = reader.ref(case['proposal_ref'])
    report_ref = case['pipeline_report_ref']; report = reader.ref(report_ref)
    request = reader.ref(report['input_manifest']['request_ref'])
    require(isinstance(request, dict) and isinstance(packet, dict) and isinstance(proposal, dict)
            and request.get('packet') == packet and packet.get('case_id') == case_id
            and proposal.get('case_id') == case_id
            and report.get('phases', {}).get('contribution', {}).get('data') == proposal
            and report.get('status') == case.get('status'), 'PROJECTION_COMPARISON_RUNTIME_BINDING_INVALID')
    return {'runtime_status': identifier(report.get('status')), 'pipeline_status': identifier(report.get('status')),
        'pipeline_reason': identifier(report.get('reason'), None), 'case_result_sha256': case_ref['sha256'],
        'pipeline_report_sha256': report_ref['sha256'], 'execution_id': identifier(report.get('run_id'), None)}


def comparison_order(reader, study, record, case_id, arms):
    require(isinstance(study, dict) and (record.get('original_contract_ref') == study.get('contract_ref')
            or record.get('contract_ref') == study.get('contract_ref')), 'PROJECTION_COMPARISON_ORDER_CONTRACT_INVALID')
    mapping = study['blind_mapping'][case_id]; passes = study['review'][case_id]['passes']
    require(len(passes) == 2 and set(mapping) == {'X', 'Y'} and set(mapping.values()) == {'A', 'B'}, 'PROJECTION_COMPARISON_ORDER_ROSTER_INVALID')
    responses = []
    for ref in passes:
        reviewed = reader.ref(ref); response = reader.ref(reviewed['response_ref']); execution = reader.ref(reviewed['execution_ref'])
        require(reviewed.get('response') == response and execution.get('status') == 'succeeded'
                and execution.get('receipt', {}).get('turn_completed') is True
                and execution['receipt'].get('response_sha256') == reviewed['response_ref']['sha256'],
                'PROJECTION_COMPARISON_ORDER_RESPONSE_INVALID')
        require(isinstance(response.get('assessments'), list) and len(response['assessments']) == 2
                and {row.get('label') for row in response['assessments']} == {'X', 'Y'}, 'PROJECTION_COMPARISON_ORDER_ASSESSMENTS_INVALID')
        for assessment in response['assessments']:
            arm = mapping[assessment['label']]; case_ref = study['cases'][case_id][arm]; case = reader.ref(case_ref)
            require(arms[arm].get('case_result_sha256') == case_ref['sha256'] and assessment.get('case_id') == case_id
                    and assessment['proposal_ref']['sha256'] == case['proposal_ref']['sha256'], 'PROJECTION_COMPARISON_ORDER_CASE_INVALID')
        responses.append(response)
    preferences = [mapping.get(response['pairwise_preference'], response['pairwise_preference']) for response in responses]
    changed = set()
    for blind in ['X', 'Y']:
        scores = [next(row['scores'] for row in response['assessments'] if row['label'] == blind) for response in responses]
        changed.update(key for key in scores[0] if scores[0].get(key) != scores[1].get(key))
    preference_consistent = preferences[0] == preferences[1]
    return {'status': 'consistent' if preference_consistent and not changed else 'disagreement',
        'preferences': [identifier(value) for value in preferences], 'preference_consistent': preference_consistent,
        'score_consistent': not changed, 'score_disagreements': sorted(identifier(key) for key in changed),
        'scope': 'two_captured_review_orders_not_calibrated_confidence'}


def comparison_dto(reader, path, *, name, scope, review_study=None):
    record = reader.file(path); arms = []; case_rows = {}; cohorts = []
    contract = reader.optional(lambda: reader.ref(record['contract_ref']), 'COMPARISON_CONTRACT_UNAVAILABLE') if record.get('contract_ref') else None
    expected_cases = len(contract.get('cases', [])) if contract else None
    for arm, ref in record.get('host_results', record.get('results', {})).items():
        if arm not in {'A', 'B'}: continue
        result = reader.ref(ref); cases = result.get('cases', [])[:32]
        metrics = [numeric_metrics(row.get('metrics')) for row in cases]
        arm_metrics = aggregate(metrics)
        arms.append({'id': arm, 'status': identifier(result.get('status')), 'denominator': len(cases),
                     'expected_cases': expected_cases, 'graded_cases': len(cases), 'denominator_scope': 'graded_cases',
                     'metrics': arm_metrics, 'errors': [identifier(error) for error in result.get('errors', [])[:8]],
                     'usage': numeric_metrics(result.get('usage')), 'receipt_sha256': ref['sha256']})
        for row in cases:
            cid = identifier(row.get('id'))
            summary = reader.optional(lambda: proposal_summary(reader, row['output_ref'], cid), 'COMPARISON_SUMMARY_UNAVAILABLE') if row.get('output_ref') else None
            runtime = reader.optional(lambda: comparison_runtime(reader, row['output_ref'], cid), 'COMPARISON_RUNTIME_UNVERIFIED') if row.get('output_ref') else None
            case_rows.setdefault(cid, {'case_id': cid})[arm] = {'status': 'passed' if row.get('passed') is True else 'failed',
                'review_status': 'passed' if row.get('passed') is True else 'failed',
                **(runtime or {'runtime_status': 'unknown', 'pipeline_status': 'unknown', 'pipeline_reason': None}),
                'metrics': numeric_metrics(row.get('metrics')), 'summary': summary}
        cohorts.append({'id': name + ':' + arm, 'scope': scope, 'denominator': len(cases), 'metrics': arm_metrics,
                        'unknowns': {'cost': 'not_observed', 'superiority': 'not_established',
                                     'expected_cases': expected_cases, 'ungraded_cases': max(0, expected_cases - len(cases)) if expected_cases is not None else None}})
    rows = []
    for cid, row in sorted(case_rows.items()):
        for arm in ['A', 'B']: row.setdefault(arm, {'status': 'unknown', 'review_status': 'unknown', 'runtime_status': 'unknown', 'pipeline_status': 'unknown', 'pipeline_reason': None, 'metrics': {}, 'summary': None})
        order = reader.optional(lambda: comparison_order(reader, review_study, record, cid, row), 'COMPARISON_ORDER_UNVERIFIED') if review_study else None
        row['review_order'] = order or {'status': 'unavailable', 'preferences': [], 'preference_consistent': None, 'score_consistent': None, 'score_disagreements': []}
        keys = row['A']['metrics'].keys() | row['B']['metrics'].keys()
        row['differences'] = {key: row['A']['metrics'].get(key) - row['B']['metrics'].get(key)
            if type(row['A']['metrics'].get(key)) in (int, float) and type(row['B']['metrics'].get(key)) in (int, float) else None for key in sorted(keys)}
        rows.append(row)
    failed = any(arm['status'] == 'failed' for arm in arms)
    runtime_counts = dict(Counter(row[arm]['runtime_status'] for row in rows for arm in ['A', 'B']))
    blocked = sum(count for status, count in runtime_counts.items() if status != 'completed')
    preference_disagreements = sum(row['review_order']['preference_consistent'] is False for row in rows)
    score_disagreements = sum(row['review_order']['score_consistent'] is False for row in rows)
    return {'id': name, 'title': name.replace('_', ' '), 'scope': scope, 'status': 'failed' if failed else 'passed' if arms and all(a['status'] == 'passed' for a in arms) else 'unknown',
            'arms': arms, 'rows': rows, 'superiority_established': False,
            'conclusion': {'status': 'limited' if blocked or preference_disagreements or score_disagreements else 'descriptive_only',
                'runtime_counts': runtime_counts, 'noncompleted_executions': blocked,
                'review_order_known': sum(row['review_order']['status'] != 'unavailable' for row in rows),
                'preference_disagreements': preference_disagreements, 'score_disagreements': score_disagreements,
                'scope': 'captured_review_gate_not_pipeline_completion_or_acquisition_quality'},
            'limitations': ['Development evidence from correlated cases; no statistical superiority or investment alpha established.',
                'Captured repair reuses answers and reviews; it does not replace original failed grader receipts.',
                'Historical answer runs predate the strict temporal broker and used reconstructed dated sources. Captured/regrade metrics are not strict historical replay.']}, cohorts


def _registry(reader, registry_ref=None):
    registry = reader.ref(registry_ref) if registry_ref else reader.file(REGISTRY) if REGISTRY.exists() else {}
    require(isinstance(registry, dict) and set(registry) <= {'schema_version', 'catalog_refs', 'report_refs', 'source_refs', 'temporal_diagnostic_refs', 'batch_refs', 'acquisition_comparison_refs'}, 'PROJECTION_REGISTRY_INVALID')
    for key in ['catalog_refs', 'report_refs', 'source_refs', 'temporal_diagnostic_refs', 'batch_refs', 'acquisition_comparison_refs']:
        require(isinstance(registry.get(key, []), list) and len(registry.get(key, [])) <= (4 if key == 'acquisition_comparison_refs' else 32), 'PROJECTION_REGISTRY_LIMIT')
    return registry


def snapshot(*, subject='NOW', limit=100, offset=0, snapshot_id=None, registry_ref=None):
    require(isinstance(subject, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', subject), 'PROJECTION_SUBJECT_INVALID')
    require(type(limit) is int and 1 <= limit <= 200 and type(offset) is int and 0 <= offset <= 10000, 'PROJECTION_PAGE_INVALID')
    subject = subject.upper(); reader = Reader(); sources = {}; runs = {}; batches = {}; comparisons = []; cohorts = []
    registry = reader.optional(lambda: _registry(reader, registry_ref), 'REGISTRY_UNAVAILABLE') or {}
    catalog_refs = list(registry.get('catalog_refs', []))
    if CATALOG.exists():
        marker = reader.optional(lambda: reader.file(CATALOG), 'CATALOG_UNAVAILABLE')
        if marker and marker.get('roster_ref'): catalog_refs.append(marker['roster_ref'])
    for ref in catalog_refs:
        roster = reader.optional(lambda: reader.ref(ref), 'CATALOG_UNAVAILABLE')
        if not roster: continue
        rows = roster.get('records', [])
        require(isinstance(rows, list) and len(rows) <= 12000, 'PROJECTION_CATALOG_LIMIT')
        for row in rows:
            if row.get('entity', '').upper() == subject:
                item = catalog_dto(row, ref, reader); sources[item['id']] = item
    labels = {}
    for path in reader.optional(lambda: bounded_files(LABEL_DIRECTORY, 256), 'LABEL_SCAN_UNAVAILABLE') or []:
        try:
            ref = {'path': str(path), 'sha256': path.stem}
            bound = read_sidecar(ref, loader=reader.ref); label = bound['label']
            # Claim estimates/opinions never become document-wide labels.
            if label['scope'] != 'document': continue
            previous = labels.get(label['source_ref']['sha256'])
            if previous is None or bound['recorded_at'] > previous['recorded_at']: labels[label['source_ref']['sha256']] = bound
        except (SourceError, OSError, ValueError, TypeError, KeyError): reader.warnings['LABEL_PROVENANCE_INVALID'] += 1
    source_refs = list(registry.get('source_refs', []))
    if subject == 'NOW':
        for path in reader.optional(lambda: bounded_files(NOW / 'prepared-v1/sources', 32), 'SOURCE_SCAN_UNAVAILABLE') or []:
            source_refs.append({'path': str(path), 'sha256': path.stem})
    for entry in source_refs:
        ref = entry.get('source_ref', entry) if isinstance(entry, dict) else entry
        target = entry.get('subject', subject) if isinstance(entry, dict) else subject
        if target != subject: continue
        receipt = reader.optional(lambda: reader.ref(ref), 'SOURCE_RECEIPT_UNAVAILABLE')
        if receipt and isinstance(receipt, dict) and {'provider', 'source_url'} <= receipt.keys():
            item = source_dto(receipt, ref, subject, persisted=labels.get(ref['sha256'])); sources[item['id']] = item
    report_entries = list(registry.get('report_refs', []))
    if subject == 'NOW':
        study = reader.optional(lambda: reader.file(NOW / 'round-v1.0.1/record.json'), 'NOW_STUDY_UNAVAILABLE')
        if study:
            for cid, arms in list(study.get('cases', {}).items())[:32]:
                for arm, ref in arms.items():
                    case = reader.optional(lambda: reader.ref(ref), 'CASE_UNAVAILABLE')
                    if case and case.get('pipeline_report_ref'):
                        packet = reader.optional(lambda: reader.ref(case['packet_ref']), 'PACKET_UNAVAILABLE')
                        report_entries.append({'report_ref': case['pipeline_report_ref'], 'subject': 'NOW',
                            'query': packet.get('question') if packet else None, 'source_sha256s': [e.get('source_sha256') for e in packet.get('evidence', [])] if packet else []})
        for path, name, scope in [
            (NOW / 'record.json', 'now_original_1.0.0', 'stopped_failed_implementation'),
            (NOW / 'round-v1.0.1/record.json', 'now_original_grader_1.0.1', 'original_failed_quality_grader'),
            (NOW / 'round-v1.0.1/captured-regrade-1.0.2/record.json', 'now_captured_regrade_1.0.2', 'captured_only_grading_repair')]:
            if path.exists():
                result = reader.optional(lambda: comparison_dto(reader, path, name=name, scope=scope, review_study=study), 'COMPARISON_UNAVAILABLE')
                if result: comparisons.append(result[0]); cohorts.extend(result[1])
    # Audit heads are a bounded read-only projection, never Audit()/Store()
    # constructors (those create files and update SQLite schemas).
    audit = INVESTMENT_STATE / 'executions'
    if audit.exists():
        try:
            with os.scandir(private_path(audit)) as entries:
                for index, entry in enumerate(entries):
                    require(index < 100, 'PROJECTION_AUDIT_SCAN_BUDGET')
                    if not entry.is_dir(follow_symlinks=False): continue
                    state = reader.optional(lambda: reader.ref(reader.file(Path(entry.path) / 'latest.json')), 'AUDIT_UNAVAILABLE')
                    if not state or not isinstance(state.get('result'), dict) or not state['result'].get('report_ref'): continue
                    # Do not project unrelated account/job prompts. Query filter is
                    # metadata only; explicit registry binds subjects more strongly.
                    query = state.get('query')
                    if isinstance(query, str) and re.search(r'(?i)\b' + re.escape(subject) + r'\b', query):
                        report_entries.append({'report_ref': state['result']['report_ref'], 'subject': subject, 'query': query})
        except (SourceError, OSError): reader.warnings['AUDIT_SCAN_UNAVAILABLE'] += 1
    diagnostic_refs = list(registry.get('temporal_diagnostic_refs', []))
    for entry in report_entries[:96]:
        if entry.get('subject') != subject: continue
        item = reader.optional(lambda: pipeline_dto(reader, entry['report_ref'], subject=subject, query=entry.get('query')), 'RUN_UNAVAILABLE')
        if item:
            for source_hash in entry.get('source_sha256s', []):
                sid = 'src_' + source_hash if sha(source_hash) else None
                if sid in sources:
                    if sid not in item['source_ids']: item['source_ids'].append(sid)
                    if item['id'] not in sources[sid]['run_ids']: sources[sid]['run_ids'].append(item['id'])
            if entry.get('temporal_diagnostic_ref'):
                temporal_ref = entry['temporal_diagnostic_ref']
                bound = reader.optional(lambda: run_temporal(reader, entry['report_ref'], temporal_ref,
                    entry.get('source_sha256s', [])), 'RUN_TEMPORAL_BINDING_UNVERIFIED')
                if bound:
                    item['temporal'] = bound
                    diagnostic_refs.append(temporal_ref)
                else:
                    item['temporal'].update(status='unverified', reason_codes=['RUN_TEMPORAL_BINDING_UNVERIFIED'])
            previous = runs.get(item['id'])
            # Audit projection must not erase an explicitly bound registry row.
            if previous and previous['temporal']['status'] == 'guarded' and item['temporal']['status'] != 'guarded':
                continue
            runs[item['id']] = item
    registered_batches = 0; seen_batch_refs = set(); batch_executions = {}; conflicting_batch_executions = set(); batch_only_sources = set()
    for entry in registry.get('batch_refs', []):
        if not isinstance(entry, dict) or entry.get('subject') != subject: continue
        ref_hash = entry.get('batch_ref', {}).get('sha256') if isinstance(entry.get('batch_ref'), dict) else None
        if sha(ref_hash) and ref_hash in seen_batch_refs: continue
        if sha(ref_hash): seen_batch_refs.add(ref_hash)
        registered_batches += 1
        result = reader.optional(lambda: batch_dto(reader, entry['batch_ref'], subject=subject, labels=labels), 'BATCH_UNAVAILABLE')
        if result is None: continue
        batch, selected_sources = result
        execution = batch['execution_id']
        if execution in batch_executions or execution in conflicting_batch_executions:
            reader.warnings['BATCH_EXECUTION_CONFLICT'] += 1
            previous = batch_executions.pop(execution, None)
            if previous: batches.pop(previous, None)
            conflicting_batch_executions.add(execution)
            continue
        batch_executions[execution] = batch['id']
        for source in selected_sources:
            sid = source['id']
            if sid not in sources:
                sources[sid] = source; batch_only_sources.add(sid)
            if batch['id'] not in sources[sid].setdefault('batch_ids', []): sources[sid]['batch_ids'].append(batch['id'])
        batch['sources'] = [sources[row['id']] for row in selected_sources]
        batches[batch['id']] = batch
    valid_batch_sources = {sid for batch in batches.values() for sid in batch['source_ids']}
    for sid in batch_only_sources - valid_batch_sources: sources.pop(sid, None)
    for source in sources.values():
        if 'batch_ids' in source: source['batch_ids'] = [bid for bid in source['batch_ids'] if bid in batches]
    seen_acquisitions = set()
    for entry in registry.get('acquisition_comparison_refs', []):
        if not isinstance(entry, dict) or entry.get('subject') != subject: continue
        ref = entry.get('report_ref')
        if isinstance(ref, dict) and ref.get('sha256') in seen_acquisitions: continue
        result = reader.optional(lambda: acquisition_projection.project(reader, ref, subject, text=text, identifier=identifier,
            timestamp=timestamp, sha=sha, source_dto=source_dto, numeric_metrics=numeric_metrics, aggregate=aggregate), 'ACQUISITION_COMPARISON_UNAVAILABLE')
        if result is None: continue
        comparison, captured = result; comparisons.append(comparison); seen_acquisitions.add(ref['sha256'])
        for source in captured:
            sid = source['id']
            if sid not in sources: sources[sid] = source
            collection_ids = [collection['execution_id'] for collection in comparison['acquisition']['collections']
                              if sid in {row['id'] for row in collection['sources']}]
            sources[sid]['collection_ids'] = sorted(set(sources[sid].get('collection_ids', []) + collection_ids))
    seen_diagnostics = set()
    for ref in diagnostic_refs:
        if isinstance(ref, dict) and ref.get('sha256') in seen_diagnostics: continue
        result = reader.optional(lambda: temporal_decisions(reader, ref), 'TEMPORAL_DIAGNOSTIC_UNAVAILABLE')
        if result is None: continue
        seen_diagnostics.add(ref['sha256'])
        for row in result[1]:
            sid = 'src_' + row['source_sha256']
            if sid in sources:
                check = {**row, 'diagnostic_sha256': ref['sha256'], 'semantics': 'source_version_at_displayed_cutoff'}
                sources[sid]['temporal_checks'].append(check)
                # This source-level view never supplies selected-run eligibility.
                sources[sid]['temporal'] = check
    cohorts.append({'id': 'pipeline_runs:' + subject, 'scope': 'ordered_research_component', 'denominator': len(runs),
                    'metrics': aggregate([r['metrics'] for r in runs.values()]), 'unknowns': {'tokens': 'not_in_pipeline_receipts', 'cost': 'not_in_pipeline_receipts'}})
    cohorts.append({'id': 'acquisition_batches:' + subject, 'scope': 'acquisition_only_not_semantic_admission', 'denominator': len(batches),
        'metrics': aggregate([batch['metrics'] for batch in batches.values()]),
        'unknowns': {'http_requests': 'not_observed_adapter_dispatches_only', 'semantic_admission': 'not_established'}})
    source_rows = sorted(sources.values(), key=lambda row: (row['scope'] != 'source_capture', row['title'], row['id']))
    run_rows = sorted(runs.values(), key=lambda row: (row['started_at'] or '', row['id']), reverse=True)
    batch_rows = sorted(batches.values(), key=lambda row: (row['started_at'] or '', row['id']), reverse=True)
    reader.coherent()
    fingerprint = digest({'subject': subject, 'sources': source_rows, 'runs': run_rows, 'batches': batch_rows, 'comparisons': comparisons})
    require(snapshot_id is None or snapshot_id == fingerprint, 'PROJECTION_SNAPSHOT_CHANGED')
    if not sources and not runs and not batches: reader.warnings['NO_MATCHING_RECEIPTS'] += 1
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(), 'snapshot_id': fingerprint,
        'status': 'partial' if reader.warnings else 'ok', 'warnings': [{'code': key, 'count': count} for key, count in sorted(reader.warnings.items())],
        'subject': subject, 'pagination': {'offset': offset, 'limit': limit, 'total_sources': len(source_rows), 'total_runs': len(run_rows),
            'total_batches': len(batch_rows),
            'total_native_collections': sum(len(row['acquisition']['collections']) for row in comparisons if row.get('acquisition')),
            'next_offset': offset + limit if max(len(source_rows), len(run_rows), len(batch_rows)) > offset + limit else None},
        'sources': source_rows[offset:offset + limit], 'runs': run_rows[offset:offset + limit], 'batches': batch_rows[offset:offset + limit],
        'comparisons': comparisons, 'aggregates': {'cohorts': cohorts, 'source_counts': {'total': len(source_rows),
            'by_scope': dict(Counter(s['scope'] for s in source_rows)),
            'by_publisher': dict(Counter(s['labels']['publisher_kind'] for s in source_rows)),
            'by_document_type': dict(Counter(s['labels']['document_type'] for s in source_rows)),
            'persisted_labels': sum(s['labels']['persistence'] == 'immutable_sidecar' for s in source_rows),
            'unknown_available_at': sum(s['timestamps']['available_at'] is None for s in source_rows)},
            'batch_counts': {'registered': registered_batches, 'total': len(batch_rows),
                'unavailable_batches': registered_batches - len(batch_rows), 'by_status': dict(Counter(batch['status'] for batch in batch_rows)),
                'scope': 'registered_batches_for_requested_subject', 'counting_unit': 'adapter_dispatch', 'http_requests': None,
                'counts': {key: sum(batch['metrics'][key] for batch in batch_rows) for key in
                    ['requirements', 'fulfilled', 'unavailable', 'unknown', 'provider_calls', 'cache_hits', 'fallbacks', 'retries']}},
            'retention_counts': {**{key: sum(batch['retention'][key] for batch in batch_rows) for key in
                    ['manifest_receipts', 'configuration_receipts', 'requirement_receipts', 'attempt_receipts', 'source_receipts', 'observation_receipts']},
                'scope': 'per_batch_hash_checked_receipt_references_not_unique_storage_objects', 'snapshots': 'retain_until_explicit_gc', 'cache_is_disposable_index': True},
            'unknowns': {'investment_alpha': 'not_established', 'runtime_acceptance': 'requires_future_scheduled_execution_and_email'}},
        'metric_definitions': {key: {'label': label, 'unit': unit, 'aggregation': 'descriptive_only', 'caveat': METRIC_CAVEATS.get(key, 'Missing values are unknown; no universal quality or superiority score.')} for key, (label, unit) in METRICS.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--subject', default='NOW'); parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--offset', type=int, default=0); parser.add_argument('--snapshot-id')
    parser.add_argument('--registry-ref', help='Optional pinned JSON ArtifactRef')
    parser.add_argument('--freeze-preview-title', help='Explicitly freeze a preview for one registered local research JSON title')
    args = parser.parse_args()
    try:
        value = freeze_catalog_preview(subject=args.subject, title=args.freeze_preview_title) if args.freeze_preview_title else snapshot(
            subject=args.subject, limit=args.limit, offset=args.offset, snapshot_id=args.snapshot_id,
            registry_ref=json.loads(args.registry_ref) if args.registry_ref else None)
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        require(len(payload.encode()) <= 2 * 1024 * 1024, 'PROJECTION_RESPONSE_TOO_LARGE')
        print(payload)
    except Exception as error:
        code = str(error) if isinstance(error, SourceError) and re.fullmatch('[A-Z_]{1,80}', str(error)) else 'PROJECTION_UNAVAILABLE'
        print(json.dumps({'schema_version': 1, 'status': 'unavailable', 'warnings': [{'code': code, 'count': 1}],
                          'sources': [], 'runs': [], 'comparisons': [], 'aggregates': {'cohorts': [], 'unknowns': {}}}))
        raise SystemExit(1)


if __name__ == '__main__': main()
