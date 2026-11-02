"""Review-gated preparation and gold-free adapters for one development screen.

This module performs no network/model call and never promotes a label policy.
The host registers both arms before dispatch and owns the single live-call path.
"""
import hashlib
import json
import math
from pathlib import Path
import time

from shared.research_sources.artifacts import ROOT, read, require, save
from investment.research.information_labels import classify
from . import grade as evaluator

VERSION = 'source-label-screen-1.0.0'
CLASSIFIER_SOURCES = [
    'tuning/evals/label_accuracy/screen.py',
    'investment/research/information_labels.py',
    'investment/research/source_labeler.py',
    'investment/research/information-labels.schema.json',
    'investment/research/information-taxonomy.json',
    # Evaluator's default closure already pins typed_judge/contracts.py.
    'shared/typed_judge/client.py',
    'shared/typed_judge/_worker.py',
]


def _local(path):
    path = Path(path); path = path if path.is_absolute() else ROOT / path
    require(path.is_relative_to(ROOT) and path.resolve().is_relative_to(ROOT), 'LABEL_REVIEW_PATH_INVALID')
    for parent in (path, *path.parents):
        if parent == ROOT:
            break
        require(not parent.is_symlink(), 'LABEL_REVIEW_PATH_INVALID')
    require(path.is_file() and path.stat().st_size <= 1024 * 1024, 'LABEL_REVIEW_FILE_INVALID')
    return path


def prepare(manifest_path, review_path, directory):
    """Materialize exact chunks only after a separate hash-bound gold review.

    This returns a spec, not a sealed contract or a dispatched evaluation. Root
    pins settled classifier/configuration bytes and calls evaluator.seal next.
    """
    manifest_raw = _local(manifest_path).read_bytes(); manifest = json.loads(manifest_raw)
    review_raw = _local(review_path).read_bytes(); review = json.loads(review_raw)
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    require(review.get('manifest_sha256') == manifest_sha and review.get('decision') == 'approved'
            and isinstance(review.get('reviewer_id'), str) and bool(review['reviewer_id'])
            and review.get('review_kind') == 'coordinator_ai_development_review_not_human_gold',
            'LABEL_GOLD_REVIEW_REQUIRED')
    require(manifest.get('schema_version') == 1 and len(manifest.get('cases', [])) == 8,
            'LABEL_EIGHT_CASE_ROSTER_REQUIRED')
    policy = manifest.get('candidate_policy')
    require(isinstance(policy, dict) and policy.get('min_probability') == .6 and policy.get('min_margin') == .1,
            'LABEL_PROVISIONAL_POLICY_CHANGED')
    taxonomy_raw = _local(manifest['taxonomy_path']).read_bytes()
    schema_raw = _local(manifest['label_schema_path']).read_bytes()
    taxonomy = json.loads(taxonomy_raw); schema = json.loads(schema_raw)
    taxonomy_ref = save(Path(directory) / 'inputs', taxonomy_raw)
    options = schema['properties']['document_type']['enum']; topics = list(taxonomy['topics'])
    cases = []; seen = set(); groups = set()
    for item in manifest['cases']:
        require(item['id'] not in seen, 'LABEL_DUPLICATE_CASE'); seen.add(item['id'])
        source = read(item['source_ref']); text = read(source['text'], json_value=False).decode('utf-8')
        start, end = item['start_character'], item['end_character']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(text), 'LABEL_CHUNK_BOUNDS')
        chunk = text[start:end].encode('utf-8')
        require(hashlib.sha256(chunk).hexdigest() == item['chunk_sha256'] and len(text[start:end]) <= 12000,
                'LABEL_REVIEWED_CHUNK_CHANGED')
        inputs = {'source_ref': item['source_ref'], 'chunk_ref': save(Path(directory) / 'inputs', chunk, suffix='txt'),
            'taxonomy_ref': taxonomy_ref, 'source_group': item['source_group'], 'cutoff': manifest['cutoff'],
            'allowed_document_types': options, 'allowed_topics': topics}
        evaluator._input(inputs); evaluator._gold(item['gold'], inputs); groups.add(item['source_group'])
        cases.append({'id': item['id'], 'input': inputs, 'expected': item['gold'], 'critical': item['critical']})
    require(len(groups) == 8, 'LABEL_SOURCE_GROUP_ROSTER_CHANGED')
    spec = {'id': manifest['id'], 'version': manifest['version'], 'split': 'development',
        'blindness': 'answers_withheld', 'cases': cases, 'metrics': evaluator.METRICS,
        'budget': manifest['proposed_equal_per_arm_budget']}
    spec_ref = save(Path(directory) / 'host', spec)
    return {'version': VERSION, 'spec_ref': spec_ref,
        'manifest_ref': save(Path(directory) / 'host', manifest_raw),
        'review_ref': save(Path(directory) / 'host', review_raw),
        'taxonomy_ref': taxonomy_ref, 'schema_sha256': hashlib.sha256(schema_raw).hexdigest(),
        'candidate_policy': policy, 'required_cases': 8, 'distinct_source_groups': len(groups),
        'blindness_enforcement': 'packet_separation_only_no_os_isolation',
        'scope': 'reviewed_development_screen_not_generalization_or_default_promotion'}


def _bindings(inputs):
    return {key + '_sha256': inputs[key + '_ref']['sha256'] for key in ('source', 'chunk', 'taxonomy')}


def normalize_rules(inputs):
    """Existing URL/origin rule hints; no invented negatives or probabilities."""
    source = evaluator._input(inputs)
    started = time.monotonic(); label = classify(source, inputs['source_ref'])
    document = label['document_type']
    if document == 'unknown':
        document = None
    require(document is None or document in inputs['allowed_document_types'], 'LABEL_RULE_DOCUMENT_OUTSIDE_TAXONOMY')
    positives = [topic for topic in label['topics'] if topic in inputs['allowed_topics']]
    abstentions = [topic for topic in inputs['allowed_topics'] if topic not in positives]
    return {**_bindings(inputs), 'transport_status': 'partial' if document is not None or positives else 'abstained',
        'document_type': document, 'topics': positives, 'topic_abstentions': abstentions,
        'document_probabilities': None, 'topic_probabilities': None,
        'latency_ms': (time.monotonic() - started) * 1000, 'cost': None,
        'normalization_policy': VERSION, 'information_used': 'existing_source_url_origin_hints_only'}


def normalize_labeler_report(inputs, report):
    """Do not turn a blocked/disabled/unknown model call into semantic abstention."""
    evaluator._input(inputs)
    require(report.get('source_ref') == inputs['source_ref']
            and report.get('taxonomy_sha256') == inputs['taxonomy_ref']['sha256'], 'LABEL_REPORT_BINDING_MISMATCH')
    output = report.get('evaluation_output')
    if output is not None:
        require(all(output.get(key) == value for key, value in _bindings(inputs).items()), 'LABEL_REPORT_BINDING_MISMATCH')
        require(output.get('transport_status') in {'ok', 'partial', 'abstained'}, 'LABEL_REPORT_STATUS_MISMATCH')
        return dict(output)
    require(report.get('status') not in {'ok', 'partial', 'abstained'}, 'LABEL_REPORT_OUTPUT_MISSING')
    latency = None
    if report.get('judge_outcome_ref') is not None:
        receipt = read(report['judge_outcome_ref']).get('receipt', {})
        value = receipt.get('elapsed_seconds')
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            latency = value * 1000
    return {**_bindings(inputs), 'transport_status': report.get('status') or 'error',
        'document_type': None, 'topics': [], 'topic_abstentions': list(inputs['allowed_topics']),
        'document_probabilities': None, 'topic_probabilities': None, 'latency_ms': latency, 'cost': None,
        'error_code': report.get('reason'), 'normalization_policy': VERSION}
