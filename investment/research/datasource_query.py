"""One maintained NOW datasource recipe, using the existing ordered phase runner.

Host temporal screening -> registered exact read -> one tool-free catalog/quote
proposal -> host catalog compilation. This is not full company research, semantic
evidence admission, a forecast, or a trade. Optional labels follow the authoritative
report and cannot change its execution status.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

from jsonschema import Draft202012Validator

from shared.actions.runtime import decode, validate as validate_action
from shared.research_sources.artifacts import SourceError, private_path, read, require, save
from shared.research_sources.temporal import prepare_corpus
from . import contribution_run, information_labels
from .execution import PhaseError, run
from .information_catalog import PLAN_SCHEMA, compile_plan, prepare_context


VERSION = 'datasource-query-1.0.0'
CONFIG_PATH = Path(__file__).with_name('examples') / 'datasource-query.pipeline.json'
FACETS = ['business_mechanism', 'technical_mechanism', 'unit_economics', 'adoption', 'counterevidence']
SUMMARY = 'Source-grounded quotations and a provisional question catalog; no forecast or trade.'
GAPS = ['source_is_issuer_not_independent', 'historical_capture_not_attested',
    'semantics_require_review', 'catalog_does_not_prove_coverage',
    'bounded_passage_not_full_document', 'no_forecast_or_trade']


def _obj(properties):
    return {'type': 'object', 'additionalProperties': False, 'required': list(properties), 'properties': properties}


OBSERVATION_SCHEMA = _obj({'source_id': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
    'quote': {'type': 'string', 'minLength': 8, 'maxLength': 800},
    'claim': {'type': 'string', 'minLength': 8, 'maxLength': 800,
        'description': 'Literal extracted source statement: must equal quote exactly, without paraphrase.'},
    'epistemic_status': {'enum': ['reported_actual', 'measured_result', 'contractual_definition',
        'management_target', 'author_opinion', 'unknown']},
    'topics': {**deepcopy(information_labels.SCHEMA['properties']['topics']), 'maxItems': 6}})
OUTPUT_SCHEMA = _obj({'catalog_proposal': deepcopy(PLAN_SCHEMA),
    'observations': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': OBSERVATION_SCHEMA},
    'summary': {'type': 'string', 'const': SUMMARY},
    'gaps': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'uniqueItems': True, 'items': {'enum': GAPS}}})
OUTPUT_SCHEMA['properties']['catalog_proposal']['properties']['questions']['maxItems'] = 6


def _safe_code(exc):
    value = str(exc)
    return value if isinstance(exc, (SourceError, PhaseError)) and re.fullmatch(r'[A-Z][A-Z_0-9]{0,99}', value) else 'DATASOURCE_QUERY_FAILED'


def _compatibility_receipt(original_ref, directory):
    """Explicit read-interface normalization; no new acquisition or date changes."""
    source = read(original_ref)
    parsed = urlsplit(source.get('source_url', ''))
    require(parsed.scheme == 'https' and (parsed.hostname == 'servicenow.com' or
            (parsed.hostname or '').endswith('.servicenow.com')), 'DATASOURCE_QUERY_NOW_SOURCE_REQUIRED')
    if source.get('provider') != 'native_open_primary_capture':
        validate_action('SourceReceipt', source)
        return original_ref
    normalized = {**deepcopy(source), 'provider': 'official_document', 'truth_or_independence_certified': False,
        'metadata': {**(source.get('metadata') or {}), 'original_capture_ref': deepcopy(original_ref),
            'original_capture_provider': 'native_open_primary_capture', 'capture_route': 'native_open_primary_capture',
            'normalization': 'read_schema_compatibility_only_no_new_acquisition'}}
    validate_action('SourceReceipt', normalized)
    return save(directory, normalized)


class _Query:
    def __init__(self, directory, execution_id):
        self.directory = directory
        self.execution_id = execution_id
        self.original_ref = None
        self.source_ref = None
        self.temporal_ref = None
        self.catalog_context_ref = None
        self.catalog_diagnostic_ref = None
        self.catalog_ref = None
        self.final_ref = None
        self.issued = None
        self.model_execution_refs = []

    def prepare(self, source_manifest_ref, roster_ref, cutoff, probe_pins):
        manifest = read(source_manifest_ref)
        require(isinstance(manifest, dict) and isinstance(manifest.get('source_refs'), dict)
                and 'S01' in manifest['source_refs'], 'DATASOURCE_QUERY_S01_REQUIRED')
        self.original_ref = deepcopy(manifest['source_refs']['S01'])
        self.original_broker = prepare_corpus([self.original_ref], cutoff=cutoff)
        # Screen the actual original capture before deriving a compatible copy.
        self.original_broker.open(self.original_ref['sha256'], max_chars=1)
        self.source_ref = _compatibility_receipt(self.original_ref, self.directory)
        self.broker = prepare_corpus([self.source_ref, *probe_pins], cutoff=cutoff)
        self._save_temporal()
        self.critical_guard('evidence.read', {'source_ref': self.source_ref, 'start': 0, 'max_chars': 12000}, {})
        catalog_request = {'subject': 'NOW',
            'objective': 'Build source-grounded research questions about the captured NOW disclosure, separating mechanisms, unit economics, adoption and adverse evidence.',
            'cutoff': cutoff, 'mode': 'historical', 'required_facets': FACETS,
            'budget': {'max_questions': 6, 'max_prior_records': 12, 'max_expansions': 0, 'max_provider_calls': 6}}
        # Strict mode at the supplied cutoff excludes future/unknown priors and
        # unauthenticated document bodies. Host diagnostics are never model input.
        prepared = prepare_context(catalog_request, roster_ref, self.directory)
        self.catalog_context_ref = prepared['context_ref']
        self.catalog_diagnostic_ref = prepared['diagnostic_ref']
        context = read(self.catalog_context_ref)
        source = self.broker.open(self.source_ref['sha256'], max_chars=1)
        return {'source_ref': self.source_ref, 'read_start': 0, 'read_max_chars': 12000,
            'catalog_context': context, 'catalog_context_sha256': self.catalog_context_ref['sha256'],
            'source_packet': {key: source[key] for key in ('source_id', 'source_version', 'title',
                'source_url', 'available_at', 'availability_basis', 'read_scope', 'scope')}}

    def _save_temporal(self):
        original = self.original_broker.host_diagnostics()
        if not hasattr(self, 'broker'):
            self.temporal_ref = save(self.directory, original)
            return
        diagnostic = self.broker.host_diagnostics()
        for row in diagnostic['sources']:
            if row['worker_visible'] and row['source_sha256'] != self.source_ref['sha256']:
                row.update(worker_visible=False, reason_codes=[*row['reason_codes'], 'RECIPE_PROBE_HOST_ONLY'])
        if self.original_ref != self.source_ref:
            for row in original['sources']:
                row.update(worker_visible=False, reason_codes=[*row['reason_codes'], 'READ_COMPATIBILITY_ORIGINAL_HOST_ONLY'])
            diagnostic['sources'].extend(original['sources'])
            diagnostic['lineage'] = {'original_capture_ref': self.original_ref,
                'read_compatibility_ref': self.source_ref, 'independent_sources': 1,
                'normalization': 'read_schema_compatibility_only_no_new_acquisition'}
        self.temporal_ref = save(self.directory, diagnostic)

    def critical_guard(self, action_id, arguments, context):
        """Application-owned read guard; invoked explicitly around this recipe."""
        require(action_id == 'evidence.read' and arguments.get('source_ref') == self.source_ref,
                'DATASOURCE_QUERY_READ_SOURCE_MISMATCH')
        original = read(self.original_ref)
        normalized = read(self.source_ref)
        self.original_broker.open(self.original_ref['sha256'], max_chars=1)
        for field in ('raw', 'text', 'source_version', 'retrieved_at', 'available_at', 'published_at',
                'modified_at', 'availability_basis', 'limitations', 'capture_method'):
            require(original.get(field) == normalized.get(field), 'DATASOURCE_QUERY_NORMALIZATION_DRIFT')
        if self.original_ref != self.source_ref:
            require(normalized.get('metadata', {}).get('original_capture_ref') == self.original_ref,
                    'DATASOURCE_QUERY_ORIGINAL_BINDING')
        opened = self.broker.open(self.source_ref['sha256'], start=arguments.get('start', 0),
            max_chars=arguments.get('max_chars', 6000))
        self._save_temporal()
        return {'status': 'bounded', 'receipt_ref': save(self.directory, {
            'kind': 'datasource_query_read_guard', 'source_ref': self.source_ref,
            'original_capture_ref': self.original_ref, 'cutoff': self.broker.cutoff,
            'text_sha256': opened['text_sha256'], 'start': opened['start'], 'end': opened['end'],
            'scope': 'exact_pinned_read_only_not_semantic_support'})}

    def issued_read(self, value):
        require(isinstance(value, dict) and value.get('source_ref') == self.source_ref and
                isinstance(value.get('passage'), dict), 'DATASOURCE_QUERY_ISSUED_READ_BINDING')
        passage = value['passage']
        require(passage.get('receipt_sha256') == self.source_ref['sha256'] and
                type(passage.get('start')) is int and type(passage.get('end')) is int,
                'DATASOURCE_QUERY_ISSUED_READ_BINDING')
        expected = self.broker.open(self.source_ref['sha256'], start=passage['start'],
            max_chars=passage['end'] - passage['start'])
        require(expected['text'] == passage.get('text') and expected['end'] == passage['end'],
                'DATASOURCE_QUERY_ISSUED_READ_CHANGED')
        return passage

    def validate(self, proposal, issued):
        require(Draft202012Validator(OUTPUT_SCHEMA).is_valid(proposal), 'DATASOURCE_QUERY_SCHEMA')
        passage = self.issued_read(issued)
        seen = set()
        for observation in proposal['observations']:
            require(observation['source_id'] == self.source_ref['sha256'], 'DATASOURCE_QUERY_SOURCE_UNKNOWN')
            quote = observation['quote']
            require(quote in passage['text'], 'DATASOURCE_QUERY_QUOTE_NOT_ISSUED')
            require(observation['claim'] == quote, 'DATASOURCE_QUERY_CLAIM_NOT_LITERAL')
            require(quote not in seen, 'DATASOURCE_QUERY_DUPLICATE_OBSERVATION')
            seen.add(quote)

    def callback(self, actual):
        def call(prompt, schema):
            value = json.loads(prompt)
            self.critical_guard('evidence.read', {'source_ref': self.source_ref,
                'start': 0, 'max_chars': 12000}, {})
            self.issued = deepcopy(value['inputs']['issued_read'])
            self.issued_read(self.issued)
            require(value['permitted_actions'] == {}, 'DATASOURCE_QUERY_TOOL_FREE_REQUIRED')
            response = actual(prompt, schema)
            response = decode(response) if isinstance(response, (str, bytes)) else decode(json.dumps(response, allow_nan=False))
            require(response.get('kind') == 'phase_result' and response.get('action') is None and
                    response.get('arguments') is None, 'DATASOURCE_QUERY_TOOL_FREE_REQUIRED')
            self.validate(response.get('data'), self.issued)
            return response
        return call

    def finalizer(self, context):
        issued = context['phases']['read']['data']
        require(len(context['action_records']) == 1, 'DATASOURCE_QUERY_READ_RECORD_REQUIRED')
        record = context['action_records'][0]
        require(record['action'] == 'evidence.read@1.1.1', 'DATASOURCE_QUERY_READ_VERSION')
        arguments = read(record['arguments_ref'])
        self.critical_guard('evidence.read', arguments, context)
        outcome = read(record['outcome_ref'])
        execution = read(record['execution_ref'])
        require(outcome.get('status') == 'success' and outcome.get('data') == issued and
                execution.get('status') == 'success' and execution.get('action_id') == 'evidence.read',
                'DATASOURCE_QUERY_READ_RECORD_MISMATCH')
        proposal = context['phases']['catalog']['data']
        self.validate(proposal, issued)
        # Compile before publishing any accepted final snapshot.
        self.catalog_ref = compile_plan(proposal['catalog_proposal'], self.catalog_context_ref, self.directory)
        observation_refs = []
        for observation in proposal['observations']:
            observation_refs.append(save(self.directory, {'schema_version': 1, 'kind': 'datasource_query_observation',
                'source_ref': self.source_ref, 'original_capture_ref': self.original_ref,
                'read_outcome_ref': record['outcome_ref'], 'observation': observation,
                'scope': 'literal_source_statement_not_truth', 'annotation_status': 'provisional',
                'semantic_support': 'requires_independent_review'}))
        self.final_ref = save(self.directory, {'schema_version': 1, 'kind': 'datasource_query_snapshot',
            'execution_id': context['run_id'], 'catalog_ref': self.catalog_ref,
            'proposal_ref': save(self.directory, proposal), 'observation_refs': observation_refs,
            'source_refs': [self.source_ref], 'original_capture_ref': self.original_ref,
            'read_outcome_ref': record['outcome_ref'], 'temporal_diagnostic_ref': self.temporal_ref,
            'completion_scope': 'source_bound_question_catalog_and_literal_observations',
            'semantic_support': 'not_independently_reviewed', 'auto_commit_research': False})
        return self.final_ref


def _observe(report_ref, directory):
    report = read(report_ref)
    if report['status'] != 'completed':
        return []
    final = read(report['final_ref'])
    refs = []
    for source_ref in final['source_refs']:
        refs.append(information_labels.annotate_source(source_ref, directory))
    for claim_ref in final['observation_refs']:
        claim = read(claim_ref)
        source_ref = claim['source_ref']
        label = information_labels.classify(read(source_ref), source_ref, claim_ref=claim_ref)
        label.update(topics=claim['observation']['topics'], epistemic_status=claim['observation']['epistemic_status'])
        label['annotation'].update(method='model', status='provisional', review_ref=None)
        label['limitations'].append('Literal quote checked against issued read; epistemic/topic interpretation remains provisional.')
        refs.append(information_labels.annotate_source(source_ref, directory, label=label))
    return refs


def run_query(*, source_manifest_ref, roster_ref, cutoff, output_directory, model_callback=None,
              observer=None, execution_id=None, probe_pins=()):
    """Run one configured recipe; inject callback for tests, reuse adapter live.

    ``probe_pins`` is host-only acceptance input. Rejected future/unknown/corrupt
    probes never become model/action inputs. No schedule, email, registry, provider
    acquisition or forecast writes occur here.
    """
    directory = private_path(output_directory, create=True)
    execution_id = execution_id or str(uuid.uuid4())
    query = _Query(directory, execution_id)
    pipeline = None
    status, reason = 'blocked', None
    try:
        request = query.prepare(source_manifest_ref, roster_ref, cutoff, probe_pins)
        config = json.loads(CONFIG_PATH.read_text())
        require(config['phases'][1]['output_schema'] == OUTPUT_SCHEMA, 'DATASOURCE_QUERY_CONFIG_SCHEMA_DRIFT')
        require(len(config['phases']) == 2 and config['budget']['max_actions'] == 1 and
                config['budget']['max_model_turns'] == 1 and
                config['phases'][0]['id'] == 'read' and config['phases'][0]['mode'] == 'action' and
                config['phases'][0]['action'] == 'evidence.read@1.1.1' and
                config['phases'][0]['arguments'] == {'source_ref': {'$bind': 'request.source_ref'},
                    'start': {'$bind': 'request.read_start'}, 'max_chars': {'$bind': 'request.read_max_chars'}} and
                config['phases'][1]['id'] == 'catalog' and config['phases'][1]['mode'] == 'agent' and
                config['phases'][1]['permitted_actions'] == [], 'DATASOURCE_QUERY_RECIPE_BOUNDARY')
        if model_callback is None:
            model_callback, query.model_execution_refs = contribution_run.model_callback(directory)
        pipeline = run(config, request, output_directory=directory, model_callback=query.callback(model_callback),
            critical_guard=query.critical_guard, finalizer=query.finalizer, execution_id=execution_id)
        status, reason = pipeline['status'], pipeline.get('reason')
    except (SourceError, PhaseError, ValueError, TypeError, OSError, KeyError, IndexError, AttributeError) as exc:
        reason = _safe_code(exc)
    if hasattr(query, 'original_broker'):
        query._save_temporal()
    authoritative = {'schema_version': 1, 'kind': 'datasource_query_report', 'version': VERSION,
        'execution_id': execution_id, 'status': status, 'reason': reason,
        'source_manifest_ref': source_manifest_ref, 'roster_ref': roster_ref, 'cutoff': cutoff,
        'pipeline_report_ref': pipeline['report_ref'] if pipeline else None,
        'final_ref': pipeline.get('final_ref') if pipeline else None,
        'source_refs': [query.source_ref] if query.source_ref else [],
        'original_capture_ref': query.original_ref, 'catalog_ref': query.catalog_ref,
        'catalog_context_ref': query.catalog_context_ref, 'catalog_diagnostic_ref': query.catalog_diagnostic_ref,
        'temporal_diagnostic_ref': query.temporal_ref, 'model_execution_refs': list(query.model_execution_refs),
        'completion_scope': 'source_bound_question_catalog_and_literal_observations',
        'auto_commit_research': False}
    report_ref = save(directory, authoritative)
    label_refs = []
    def observe(saved):
        refs = observer(saved) if observer is not None else _observe(saved, directory / 'labels')
        label_refs.extend(refs)
        return refs
    observed = information_labels.best_effort_observe(report_ref, observer=observe)
    return {**authoritative, 'report_ref': report_ref, 'label_refs': label_refs,
        'observability': observed,
        'observation_warnings': [observed['code']] if observed['status'] != 'recorded' else []}
