"""Host-side retrieval conformance, not semantic truth or browser superiority."""
import math
import re
from urllib.parse import urlsplit
from shared.research_sources.artifacts import read, require

METRICS = ('anchor_hits', 'anchor_total', 'source_bound', 'elapsed_seconds', 'provider_items',
           'approval_events', 'reauth_events', 'tokens', 'cost')


def canonical(url):
    value = urlsplit(url)
    return value.scheme.lower(), value.netloc.lower(), value.path.rstrip('/'), value.query


def _callback(arm, case_id, inputs, expected, output):
    require(output.get('case_id') == case_id, 'BROWSER_CASE_BINDING')
    metrics = {key: None for key in METRICS}
    metrics['anchor_total'] = len(expected['patterns'])
    if output.get('status') == 'blocked':
        return {'passed': False, 'metrics': metrics, 'reasons': ['Reader unavailable: retrieval quality remains unverified.']}
    require(output.get('status') == 'observed', 'BROWSER_STATUS_INVALID')
    observation = read(output['observation_ref'])
    require(observation.get('status') == 'observed', 'BROWSER_OBSERVATION_REQUIRED')
    require(observation.get('kind') in ('browser_read_observation', 'native_source_observation'), 'BROWSER_OBSERVATION_KIND')
    pdf = inputs['stratum'] == 'pdf_negative_treatment_control'
    reader = 'native_source_observation' if arm == 'baseline' or pdf else 'browser_read_observation'
    require(observation['kind'] == reader, 'BROWSER_WRONG_ARM_READER')
    if reader == 'browser_read_observation':
        require(observation.get('provider') == 'egolite' and observation.get('cleanup_verified') is True
                and observation.get('intent_ref') is not None, 'BROWSER_CANDIDATE_RECEIPT_REQUIRED')
        intent = read(observation['intent_ref'])
        require(intent['operation_id'] == observation['operation_id'] and
                intent['requested_url'] == observation['requested_url'], 'BROWSER_INTENT_BINDING')
    ref = observation.get('snapshot_ref') or observation.get('body_ref')
    text = read(ref, json_value=False).decode('utf-8')
    bound = canonical(observation['observed_url']) == canonical(inputs['url'])
    hits = sum(bool(re.search(pattern, text, re.I | re.S)) for pattern in expected['patterns'])
    telemetry = read(output['telemetry_ref'])
    require(telemetry['case_id'] == case_id and telemetry['observation_ref'] == output['observation_ref'], 'BROWSER_TELEMETRY_BINDING')
    for key in ('elapsed_seconds', 'provider_items', 'approval_events', 'reauth_events', 'tokens', 'cost'):
        value = telemetry.get(key)
        require(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0, 'BROWSER_TELEMETRY_INVALID')
        metrics[key] = value
    require(metrics['elapsed_seconds'] is not None and metrics['provider_items'] is not None, 'BROWSER_REQUIRED_TELEMETRY')
    metrics.update(anchor_hits=hits, source_bound=bound)
    passed = bound and hits == len(expected['patterns']) and not observation.get('truncated', False)
    return {'passed': passed, 'metrics': metrics,
            'reasons': [] if passed else ['Source identity, required anchors or extraction completeness did not pass.']}


def baseline_callback(case_id, inputs, expected, output):
    return _callback('baseline', case_id, inputs, expected, output)


def candidate_callback(case_id, inputs, expected, output):
    return _callback('candidate', case_id, inputs, expected, output)
