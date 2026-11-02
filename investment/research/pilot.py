"""Source-bound reported-revenue pilot; scoped extraction, never a full thesis.

The fixed known source/field anchors deliberately avoid a general financial
parser. New source formats or figures require a reviewed fixture/version.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from shared.research_sources.artifacts import digest, private_path, read, require, save
from shared.research_sources.fetch import Document, fetch_document, passages as source_passages
from shared.research_sources.store import Store
from .use_policy import resolve, schedule_check, stamp

VERSION = 'nvda-revenue-pilot-v1'
SOURCE = 'https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2025'
FIXTURE = Path(__file__).with_name('examples') / 'nvda-revenue-pilot.json'
PERIOD = {'start': '2024-01-29', 'end': '2024-04-28'}
ANCHORS = {'headline': 'Record quarterly revenue of $26.0 billion',
           'table_units': '($ in millions, except earnings\nper share)',
           'table_column': 'Q1 FY25', 'table_value': 'Revenue\n$26,044'}


def _source(ref):
    receipt = read(ref)
    require(isinstance(receipt, dict) and receipt.get('provider') == 'official_document'
            and receipt.get('source_url') == SOURCE and receipt.get('upstream_id') == SOURCE,
            'PILOT_SOURCE_IDENTITY_MISMATCH')
    require(receipt.get('access_level') == 'document', 'PILOT_DOCUMENT_REQUIRED')
    require(receipt.get('availability_basis') == 'first_observed'
            and receipt.get('available_at') == receipt.get('retrieved_at'), 'PILOT_AVAILABILITY_BASIS_INVALID')
    stamp(receipt['available_at'])
    raw = read(receipt['raw'], json_value=False)
    text = read(receipt['text'], json_value=False).decode('utf-8')
    parsed = Document(); parsed.feed(raw.decode('utf-8'))
    require('\n'.join(parsed.chunks) == text, 'PILOT_EXTRACTED_TEXT_MISMATCH')
    return receipt, text


def _extract(fixture, text):
    expected = {'case_id': 'nvda-fy2025-q1-revenue-rounding', 'source_url': SOURCE,
                'entity': 'NVDA', 'metric': 'revenue', 'definition': 'reported consolidated quarterly revenue',
                'period': 'FY2025Q1', 'period_end': PERIOD['end'], 'basis': 'GAAP', 'unit': 'USD millions',
                'upstream_lineage': 'NVIDIA:FY2025Q1:earnings-release'}
    require(all(fixture.get(k) == v for k, v in expected.items()), 'PILOT_FIXTURE_SCOPE_INVALID')
    require(fixture.get('comparison', {}).get('absolute_tolerance') == '50'
            and fixture['comparison'].get('relative_tolerance') == '0', 'PILOT_TOLERANCE_CHANGED')
    require('May 22, 2024' in text and 'first quarter ended April 28, 2024' in text,
            'PILOT_SOURCE_PERIOD_MISMATCH')
    # Prior fiscal-year end and three-month statement anchor the Q1 interval.
    # Midnight is a declared date representation, not an intraday timestamp.
    require('Three Months Ended\nApril 28,' in text and 'April 28,\nJanuary 28,\n2024\n2024' in text,
            'PILOT_FISCAL_CALENDAR_UNCONFIRMED')
    passages = {}
    for name in ('headline', 'table_units', 'table_column', 'table_value'):
        needle = fixture['anchors'][name]['text']
        require(needle == ANCHORS[name], 'PILOT_ANCHOR_INVALID')
        start = text.find(needle)
        require(start >= 0, 'PILOT_SOURCE_ANCHOR_MISSING')
        passages[name] = {'start': start, 'end': start + len(needle), 'text': needle}
    require(passages['table_units']['end'] < passages['table_column']['start'] < passages['table_value']['start']
            and passages['table_value']['end'] - passages['table_units']['start'] < 500,
            'PILOT_TABLE_CONTEXT_MISMATCH')
    headline = re.fullmatch(r'Record quarterly revenue of \$(\d+\.\d) billion', passages['headline']['text'])
    table = re.fullmatch(r'Revenue\n\$(\d{1,3}(?:,\d{3})+)', passages['table_value']['text'])
    require(headline is not None and table is not None, 'PILOT_NUMERIC_EXTRACTION_FAILED')
    values = [format(Decimal(headline.group(1)) * Decimal('1000'), 'f').split('.')[0], table.group(1).replace(',', '')]
    require(values == ['26000', '26044'] and [o['value'] for o in fixture['observations']] == values,
            'PILOT_FIXTURE_VALUE_MISMATCH')
    return passages, values


class Pilot:
    def __init__(self, directory, request):
        self.directory = private_path(directory, create=True)
        self._request = deepcopy(request)
        self._bindings()
        self._request_sha = digest(request)
        self.store = Store(request['store_directory'])
        self.output_schema = {'type': 'object', 'additionalProperties': False,
            'required': ['conclusion', 'independent_sources', 'source_ref', 'comparison_input_sha256', 'explanation', 'unresolved_gaps'],
            'properties': {'conclusion': {'type': 'string', 'const': 'same_release_rounding_reconciled'},
                'independent_sources': {'type': 'boolean', 'const': False},
                'source_ref': {'type': 'object', 'additionalProperties': False, 'required': ['path', 'sha256'],
                    'properties': {'path': {'type': 'string', 'const': request['source_ref']['path']},
                                   'sha256': {'type': 'string', 'const': request['source_ref']['sha256']}}},
                'comparison_input_sha256': {'type': 'string', 'const': request['packet_ref']['sha256']},
                'explanation': {'type': 'string', 'minLength': 20, 'maxLength': 3000},
                'unresolved_gaps': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string', 'maxLength': 500}}}}

    @property
    def request(self):
        return deepcopy(self._request)

    def _bindings(self):
        expected = ['pilot:' + self._request['source_ref']['sha256'][:16] + ':' + kind
                    for kind in ('headline', 'table')]
        bindings = self._request.get('bindings')
        require(isinstance(bindings, list) and len(bindings) == 2
                and [b.get('observation_id') for b in bindings if isinstance(b, dict)] == expected,
                'PILOT_OBSERVATION_ROSTER_CHANGED')

    def _validate(self, context):
        require(isinstance(context, dict) and digest(context.get('request')) == self._request_sha,
                'PILOT_REQUEST_CHANGED')
        self._bindings()
        requirement = read(self._request['requirement_ref'])
        fixture = read(self._request['fixture_ref'])
        source, text = _source(self._request['source_ref'])
        acquisition = self._request['acquisition']
        if acquisition['mode'] == 'registered_action':
            outcome = read(acquisition['outcome_ref'])
            execution = read(acquisition['execution_ref'])
            acquisition_request = read(acquisition['request_ref'])
            require(outcome.get('status') == 'success' and outcome.get('data') == {'source_ref': self._request['source_ref']}
                    and outcome.get('execution_ref') == acquisition['execution_ref']
                    and execution.get('action_id') == 'evidence.acquire_document'
                    and execution.get('status') == 'success'
                    and execution.get('data_sha256') == digest(outcome['data'])
                    and execution.get('request_sha256') == digest(acquisition_request), 'PILOT_ACQUISITION_RECEIPT_MISMATCH')
        passages, values = _extract(fixture, text)
        require(stamp(source['available_at']) <= stamp(requirement['cutoff']), 'PILOT_SOURCE_AFTER_CUTOFF')
        require(stamp(source['available_at']) <= datetime.now(timezone.utc), 'PILOT_SOURCE_TIME_IN_FUTURE')
        records = []
        for index, bound in enumerate(self._request['bindings']):
            record = self.store.read(bound['observation_id'])
            require(record['revision'] == bound['revision'] and record['lifecycle_revision'] == bound['lifecycle_revision'],
                    'PILOT_OBSERVATION_CHANGED')
            payload = record['payload']
            for name in ('entity', 'metric', 'definition', 'period', 'unit', 'basis', 'upstream_lineage'):
                require(payload.get(name) == fixture[name], 'PILOT_OBSERVATION_METADATA_CHANGED')
            require(payload.get('source_ref') == self._request['source_ref'] and payload.get('value') == values[index],
                    'PILOT_OBSERVATION_VALUE_CHANGED')
            require(payload.get('available_at') == source['available_at']
                    and payload.get('last_checked_at') == source['retrieved_at']
                    and payload.get('source_time') == PERIOD['end'] + 'T00:00:00Z', 'PILOT_OBSERVATION_TIME_CHANGED')
            require(payload.get('passages') == passages and payload.get('source_role') == 'primary',
                    'PILOT_OBSERVATION_PASSAGE_CHANGED')
            records.append(record)
        packet = read(self._request['packet_ref'])
        expected = _packet(requirement, source, values)
        require(packet == expected, 'PILOT_COMPARISON_INPUT_CHANGED')
        verdict = resolve(requirement, records, datetime.now(timezone.utc), remaining_attempts=0)
        require(verdict['status'] == 'supported', 'PILOT_CRITICAL_INPUT_UNRESOLVED')
        verdict.update(completion_scope='same_source_rounding_reconciliation', independent_sources=False,
                       source_ref=self._request['source_ref'], packet_ref=self._request['packet_ref'],
                       requirement_ref=self._request['requirement_ref'])
        return verdict

    def critical_guard(self, action_id, arguments, context):
        require(action_id == 'evidence.compare_numeric' and arguments == {'packet_ref': self._request['packet_ref']},
                'PILOT_ACTION_INPUT_NOT_BOUND')
        verdict = self._validate(context)
        receipt_ref = save(self.directory, verdict)
        return {'status': 'supported', 'receipt_ref': receipt_ref}

    def finalizer(self, context):
        guard = self.critical_guard('evidence.compare_numeric', {'packet_ref': self._request['packet_ref']}, context)
        phases, phase_refs = context.get('phases'), context.get('phase_refs')
        require(isinstance(phases, dict) and isinstance(phase_refs, dict), 'PILOT_PHASE_RECEIPTS_REQUIRED')
        comparison_found = interpretation_found = False
        for name, outcome in phases.items():
            require(name in phase_refs and read(phase_refs[name]).get('outcome') == outcome, 'PILOT_PHASE_RECEIPT_MISMATCH')
            if outcome.get('status') != 'success':
                continue
            if outcome.get('execution_ref') is not None:
                execution = read(outcome['execution_ref'])
                if execution.get('action_id') != 'evidence.compare_numeric':
                    continue
                data = outcome['data']
                require(execution.get('status') == 'success' and execution.get('data_sha256') == digest(data),
                        'PILOT_CALCULATION_RECEIPT_MISMATCH')
                require(data.get('input_sha256') == self._request['packet_ref']['sha256']
                        and data.get('status') == 'shared_upstream_corroboration'
                        and data.get('values') == ['26000', '26044'] and data.get('absolute_difference') == '44'
                        and data.get('allowed_difference') == '50', 'PILOT_CALCULATION_NOT_RECONCILED')
                comparison_found = True
            else:
                try:
                    Draft202012Validator(self.output_schema).validate(outcome.get('data'))
                    interpretation_found = True
                except Exception:
                    pass
        require(comparison_found, 'PILOT_CALCULATION_REQUIRED')
        require(interpretation_found, 'PILOT_INTERPRETATION_REQUIRED')
        source_read_ref = self._read_receipt(context)
        bindings = [{**b, 'use_receipt_ref': guard['receipt_ref']} for b in self._request['bindings']]
        request_id = 'pilot-snapshot:' + digest({'request': self._request, 'phases': phase_refs})
        snapshot = self.store.commit_snapshot(request_id, self._request['requirement_ref'], bindings)
        return save(self.directory, {'schema_version': 1, 'completion_scope': 'same_source_rounding_reconciliation',
            'status': 'supported', 'independent_sources': False, 'requirement_ref': self._request['requirement_ref'],
            'source_ref': self._request['source_ref'], 'packet_ref': self._request['packet_ref'],
            'use_receipt_ref': guard['receipt_ref'], 'source_read_ref': source_read_ref,
            'phase_refs': phase_refs, 'snapshot': snapshot,
            'limitations': read(self._request['fixture_ref'])['limitations']})

    def _read_receipt(self, context):
        """Configured pilot requires an observed source read, not a declaration."""
        from shared.actions.runtime import ActionError, validate
        records = context.get('action_records')
        require(isinstance(records, list), 'PILOT_SOURCE_READ_REQUIRED')
        for record in records:
            if not isinstance(record, dict) or record.get('action', '').split('@')[0] != 'evidence.read':
                continue
            require('record_ref' in record and read(record['record_ref']) == {k: v for k, v in record.items() if k != 'record_ref'},
                    'PILOT_READ_RECORD_MISMATCH')
            args = read(record['arguments_ref'])
            try:
                validate('Read', args)
            except ActionError:
                require(False, 'PILOT_READ_ARGUMENTS_INVALID')
            if args['source_ref'] != self._request['source_ref']:
                continue
            expected_passage = source_passages(self._request['source_ref'], args.get('start', 0), args.get('max_chars', 6000))
            if not all(anchor in expected_passage['text'] for anchor in ANCHORS.values()):
                continue
            outcome = read(record['outcome_ref'])
            if outcome.get('status') != 'success':
                continue
            require(outcome.get('execution_ref') == record.get('execution_ref'), 'PILOT_READ_EXECUTION_MISMATCH')
            execution = read(record['execution_ref'])
            data = outcome.get('data')
            require(execution.get('status') == 'success' and execution.get('action_id') == 'evidence.read'
                    and execution.get('data_sha256') == digest(data), 'PILOT_READ_EXECUTION_MISMATCH')
            expected_request = {'schema_version': 1, 'action': record['action'],
                'request_id': '%s:%s' % (context.get('run_id'), record['call_id']), 'arguments': args,
                'expected_release_sha256': execution.get('release_sha256')}
            if record.get('request_ref') is not None:
                canonical = read(record['request_ref'])
                try:
                    validate('Request', canonical)
                except ActionError:
                    require(False, 'PILOT_READ_REQUEST_MISMATCH')
                require(all(canonical.get(key) == value for key, value in expected_request.items()),
                        'PILOT_READ_REQUEST_MISMATCH')
                expected_request = canonical
            require(record.get('run_id') == context.get('run_id') and isinstance(context.get('run_id'), str)
                    and execution.get('request_sha256') == digest(expected_request), 'PILOT_READ_REQUEST_MISMATCH')
            require(data == {'source_ref': self._request['source_ref'], 'passage': expected_passage}, 'PILOT_READ_PASSAGE_MISMATCH')
            return record['record_ref']
        require(False, 'PILOT_SOURCE_READ_REQUIRED')


def _packet(requirement, source, values):
    rows = []
    for value in values:
        rows.append({'subject': requirement['entity'], 'metric': requirement['metric'], 'definition': requirement['definition'],
            'period': PERIOD, 'unit': requirement['unit'], 'basis': 'reported', 'value': value,
            'observed_at': PERIOD['end'] + 'T00:00:00Z', 'available_at': source['available_at'],
            'source': {'origin': 'NVIDIA', 'provider': source['provider'], 'upstream_family': requirement['upstream_lineage'],
                       'ref': source['source_url'], 'sha256': source['raw']['sha256']}})
    return {'version': '2026-10-24-evidence-crosscheck-1', 'as_of': requirement['cutoff'], 'comparison_kind': 'numeric',
        'max_age_seconds': 315576000, 'max_time_skew_seconds': 0,
        'absolute_tolerance': '50', 'relative_tolerance': '0', 'require_source_hashes': True, 'observations': rows}


def prepare(fixture_path, output_directory, *, source_ref=None, getter=None, cutoff=None, now=None):
    """Prepare one reviewed source/fact contract; returned Pilot owns its gates."""
    directory = private_path(output_directory, create=True)
    fixture = json.loads(Path(fixture_path).read_text())
    fixture_ref = save(directory, fixture)
    acquisition = {'mode': 'cached_source', 'request_ref': None, 'outcome_ref': None, 'execution_ref': None}
    if source_ref is None:
        if getter is not None:
            source_ref = fetch_document(SOURCE, directory / 'sources', getter=getter)
            acquisition['mode'] = 'injected_getter'
        else:
            from shared.actions import invoke, freeze_release
            from shared.research_sources.artifacts import SOURCE_STATE
            release = freeze_release('evidence.acquire_document@1', directory=SOURCE_STATE / 'action-releases')
            acquisition_request = {'schema_version': 1, 'action': 'evidence.acquire_document@1',
                'request_id': 'pilot-acquire:' + digest({'fixture_ref': fixture_ref, 'output': str(directory)}),
                'arguments': {'kind': 'official_document', 'value': SOURCE},
                'release_ref': release['release_ref'], 'expected_release_sha256': release['release_sha256']}
            request_ref = save(directory, acquisition_request)
            outcome = invoke(acquisition_request, output_directory=directory / 'acquisition', timeout_seconds=45)
            outcome_ref = save(directory, outcome)
            require(outcome.get('status') == 'success', 'PILOT_ACQUISITION_FAILED')
            source_ref = outcome['data']['source_ref']
            acquisition = {'mode': 'registered_action', 'request_ref': request_ref,
                           'outcome_ref': outcome_ref, 'execution_ref': outcome['execution_ref']}
    source, text = _source(source_ref)
    passages, values = _extract(fixture, text)
    at = stamp(now or datetime.now(timezone.utc))
    cutoff_at = stamp(cutoff) if cutoff is not None else at
    require(stamp(source['available_at']) <= cutoff_at, 'PILOT_SOURCE_AFTER_CUTOFF')
    requirement = {k: fixture[k] for k in ('entity', 'metric', 'definition', 'period', 'unit', 'basis', 'upstream_lineage')}
    requirement.update(id=fixture['case_id'], mode='historical', criticality='critical', value_kind='numeric',
        cutoff=cutoff_at.isoformat(), max_age_seconds=None, minimum_sources=1, refresh_after_seconds=None,
        decision_deadline=(at + timedelta(hours=1)).isoformat(), absolute_tolerance='50', relative_tolerance='0',
        extraction_version=VERSION, source_url=SOURCE,
        interval=PERIOD, interval_basis='Q1 starts day after disclosed prior fiscal year end; dates represented at midnight UTC',
        scope='same_source_rounding_reconciliation')
    requirement_ref = save(directory, requirement)
    store = Store(directory / 'evidence')
    bindings = []
    for kind, value in zip(('headline', 'table'), values):
        observation_id = 'pilot:' + source_ref['sha256'][:16] + ':' + kind
        payload = {k: fixture[k] for k in ('entity', 'metric', 'definition', 'period', 'unit', 'basis', 'upstream_lineage')}
        payload.update(source_ref=source_ref, source_identity=SOURCE + '#' + kind, value=value,
            source_time=PERIOD['end'] + 'T00:00:00Z', available_at=source['available_at'],
            last_checked_at=source['retrieved_at'], source_role='primary', passages=passages,
            extraction_version=VERSION, observation_time_basis='reported period-end date; midnight UTC date convention')
        record = store.create('create:' + observation_id, observation_id, payload)
        bindings.append({'observation_id': record['id'], 'revision': record['revision'], 'lifecycle_revision': record['lifecycle_revision']})
    packet_ref = save(directory, _packet(requirement, source, values))
    due = schedule_check(requirement, {'reasons': []}, at)
    store.save_check('pilot-check:' + requirement_ref['sha256'], requirement_ref, due)
    request = {'requirement_ref': requirement_ref, 'fixture_ref': fixture_ref, 'source_ref': source_ref, 'acquisition': acquisition,
               'packet_ref': packet_ref, 'bindings': bindings, 'store_directory': str(store.directory)}
    return Pilot(directory, request)
