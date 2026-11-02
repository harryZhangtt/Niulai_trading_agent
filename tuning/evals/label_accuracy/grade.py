"""Small deterministic label evaluator around the existing sealed attempt ledger."""
import json
import math
import re
from pathlib import Path

from shared.research_sources.artifacts import ROOT, SourceError, read, require, save
from shared.research_sources.store import instant
from shared.typed_judge.contracts import PROBABILITY_SUM_TOLERANCE
from tuning.evals.evidence_runtime import contracts

METRICS = ['document_accuracy', 'topic_tp', 'topic_fp', 'topic_fn', 'topic_precision', 'topic_recall', 'topic_f1',
    'topic_exact_set', 'topic_decision_count', 'decision_count', 'classified_count', 'incorrect_count', 'abstained_count',
    'document_brier', 'document_log_loss', 'topic_brier', 'topic_log_loss', 'latency_ms', 'cost']
INPUT_KEYS = {'source_ref', 'chunk_ref', 'taxonomy_ref', 'source_group', 'cutoff', 'allowed_document_types', 'allowed_topics'}


def _input(inputs):
    require(isinstance(inputs, dict) and set(inputs) == INPUT_KEYS, 'LABEL_INPUT_SCHEMA')
    source = read(inputs['source_ref']); read(source['raw'], json_value=False)
    body = read(source['text'], json_value=False); chunk = read(inputs['chunk_ref'], json_value=False)
    require(bool(chunk) and len(chunk) <= 24000 and chunk in body, 'LABEL_CHUNK_SOURCE_MISMATCH')
    chunk.decode('utf-8'); read(inputs['taxonomy_ref'])
    bounds = [instant(source['retrieved_at']), instant(source['available_at'])]
    bounds.extend(instant(source[key]) for key in ('modified_at', 'updated_at', 'version_available_at') if source.get(key) is not None)
    require(max(bounds) <= instant(inputs['cutoff']), 'LABEL_FUTURE_INPUT')
    require(isinstance(inputs['source_group'], str) and 0 < len(inputs['source_group']) <= 96, 'LABEL_SOURCE_GROUP')
    for key in ('allowed_document_types', 'allowed_topics'):
        values = inputs[key]
        require(isinstance(values, list) and 0 < len(values) <= 64 and len(set(values)) == len(values)
                and all(isinstance(value, str) and 0 < len(value) <= 96 for value in values), 'LABEL_TAXONOMY_SCHEMA')
    return source


def _gold(expected, inputs):
    require(isinstance(expected, dict), 'LABEL_GOLD_SCHEMA')
    documents = expected.get('document_types', [expected.get('document_type')])
    topics = expected.get('topic_sets', [expected.get('topics')])
    require(isinstance(documents, list) and bool(documents) and set(documents) <= set(inputs['allowed_document_types']), 'LABEL_GOLD_DOCUMENT')
    require(isinstance(topics, list) and bool(topics) and all(isinstance(values, list) and len(set(values)) == len(values)
            and set(values) <= set(inputs['allowed_topics']) for values in topics), 'LABEL_GOLD_TOPICS')
    require(type(expected.get('abstention_allowed', False)) is bool, 'LABEL_GOLD_ABSTENTION')
    return documents, [set(values) for values in topics]


def _probabilities(value, labels, *, categorical):
    if value is None: return None
    require(isinstance(value, dict) and set(value) == set(labels) and all(type(p) in (int, float) and
            math.isfinite(p) and 0 <= p <= 1 for p in value.values()), 'LABEL_PROBABILITIES_INVALID')
    require(not categorical or abs(math.fsum(value.values()) - 1) <= PROBABILITY_SUM_TOLERANCE + 1e-12,
            'LABEL_PROBABILITIES_NOT_NORMALIZED')
    return value


def _prf(tp, fp, fn):
    return (tp / (tp + fp) if tp + fp else float(not fn), tp / (tp + fn) if tp + fn else 1.,
            2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.)


def grade(case_id, inputs, expected, output):
    _input(inputs); documents, gold_sets = _gold(expected, inputs)
    require(isinstance(output, dict) and all(output.get(key + '_sha256') == inputs[key + '_ref']['sha256']
            for key in ('source', 'chunk', 'taxonomy')), 'LABEL_OUTPUT_SOURCE_MISMATCH')
    usage = {key: output.get(key) for key in ('latency_ms', 'cost')}
    for value in usage.values():
        require(value is None or type(value) in (int, float) and math.isfinite(value) and value >= 0, 'LABEL_USAGE_INVALID')
    if output.get('transport_status') not in {'ok', 'partial', 'abstained'}:
        # A failed call can have measured latency without any semantic output.
        return {'passed': False, 'metrics': {**{key: None for key in METRICS}, **usage},
                'reasons': ['LABEL_TRANSPORT_UNVERIFIED']}
    document = output.get('document_type'); positives = output.get('topics'); abstentions = output.get('topic_abstentions', [])
    require(document is None or document in inputs['allowed_document_types'], 'LABEL_OUTPUT_DOCUMENT')
    require(isinstance(positives, list) and len(set(positives)) == len(positives) and set(positives) <= set(inputs['allowed_topics'])
            and isinstance(abstentions, list) and len(set(abstentions)) == len(abstentions)
            and set(abstentions) <= set(inputs['allowed_topics']) and not set(abstentions) & set(positives), 'LABEL_OUTPUT_TOPICS')
    predicted = set(positives); known = set(inputs['allowed_topics']) - set(abstentions)
    # Ambiguous gold is explicit. Topic metrics use the best allowed annotation;
    # probabilistic metrics require one unique gold and remain unknown otherwise.
    gold = max(gold_sets, key=lambda values: _prf(len(predicted & values), len(predicted - values), len(values - predicted))[2])
    tp, fp, fn = len(predicted & gold), len(predicted - gold), len((gold - predicted) & known)
    precision, recall, f1 = _prf(tp, fp, fn)
    correct_document = document in documents if document is not None else None
    classified = int(document is not None) + len(known); total = 1 + len(inputs['allowed_topics'])
    wrong = int(correct_document is False) + len((predicted ^ gold) & known)
    metrics = {'document_accuracy': float(correct_document) if correct_document is not None else None,
        'topic_tp': tp, 'topic_fp': fp, 'topic_fn': fn, 'topic_precision': precision if known else None, 'topic_recall': recall if known else None,
        'topic_f1': f1 if known else None, 'topic_exact_set': float(predicted in gold_sets) if not abstentions else None,
        'topic_decision_count': len(known), 'decision_count': total, 'classified_count': classified, 'incorrect_count': wrong, 'abstained_count': total - classified,
        'document_brier': None, 'document_log_loss': None, 'topic_brier': None, 'topic_log_loss': None,
        **usage}
    dp = _probabilities(output.get('document_probabilities'), inputs['allowed_document_types'], categorical=True)
    if dp is not None and document is not None:
        require(abs(dp[document] - max(dp.values())) <= 1e-6, 'LABEL_DOCUMENT_NOT_ARGMAX')
    probabilities = _probabilities(output.get('topic_probabilities'), inputs['allowed_topics'], categorical=False)
    if dp is not None and len(documents) == 1:
        metrics.update(document_brier=sum((p - int(label == documents[0])) ** 2 for label, p in dp.items()),
                       document_log_loss=-math.log(max(dp[documents[0]], 1e-15)))
    if probabilities is not None and len(gold_sets) == 1:
        metrics['topic_brier'] = sum((p - int(label in gold)) ** 2 for label, p in probabilities.items()) / len(probabilities)
        metrics['topic_log_loss'] = -sum(math.log(max(p if label in gold else 1 - p, 1e-15)) for label, p in probabilities.items()) / len(probabilities)
    abstained_correctly = expected.get('abstention_allowed', False) and document is None and not known
    passed = abstained_correctly or correct_document is True and not abstentions and predicted in gold_sets
    return {'passed': bool(passed), 'metrics': metrics, 'reasons': [] if passed else ['LABEL_NOT_WITHIN_FROZEN_ALLOWED_GOLD']}


def validate(contract_ref):
    contract = contracts.validate(contract_ref)
    require(contract['metrics'] == METRICS, 'LABEL_METRIC_CONTRACT')
    for case in contract['cases']:
        inputs = read(case['input_ref']); _input(inputs); _gold(read(case['expected_ref']), inputs)
    return contract


def seal(spec_path, candidate_fingerprints, directory, *, extra_grader_paths=()):
    spec = json.loads(Path(spec_path).read_bytes()); require(spec['metrics'] == METRICS, 'LABEL_METRIC_CONTRACT')
    for case in spec['cases']: _input(case['input']); _gold(case['expected'], case['input'])
    closure = [str(Path(__file__).relative_to(ROOT)), 'tuning/evals/evidence_runtime/contracts.py',
               'shared/research_sources/artifacts.py', 'shared/research_sources/store.py',
               'shared/typed_judge/contracts.py', *extra_grader_paths]
    return contracts.seal(spec_path, closure, candidate_fingerprints, directory)


def worker_packet(contract_ref):
    validate(contract_ref); return contracts.worker_packet(contract_ref)


def begin(contract_ref, directory, attempt_id, *, arm, budget, fingerprint):
    validate(contract_ref)
    return contracts.begin(contract_ref, directory, attempt_id, arm=arm, budget=budget, fingerprint=fingerprint)


def finish(contract_ref, directory, attempt_id, *, submissions, usage):
    # The original finish method records failures even for omitted cases/changed
    # source closure, and revalidates its pinned callback before and after grading.
    return contracts.finish(contract_ref, directory, attempt_id, submissions=submissions, usage=usage, grade=grade)


def record_unknown(claim_ref, directory, reason='WORKER_OUTCOME_UNKNOWN'):
    claim = read(claim_ref); require(claim.get('kind') == 'evaluation_attempt_claim', 'LABEL_CLAIM_INVALID')
    require(isinstance(reason, str) and re.fullmatch('[A-Z][A-Z_0-9]{0,95}', reason), 'LABEL_UNKNOWN_REASON')
    return save(directory, {'kind': 'label_evaluation_unknown', 'status': 'unknown', 'claim_ref': claim_ref,
        'attempt_id': claim['attempt_id'], 'contract_ref': claim['contract_ref'], 'reason': reason,
        'replay_allowed': False, 'scope': 'unknown_attempt_not_a_failed_quality_score'})


def summarize(contract_ref, result_ref):
    contract = validate(contract_ref); result = read(result_ref)
    require(result.get('contract_ref') == contract_ref, 'LABEL_RESULT_CONTRACT_MISMATCH')
    cases = {case['id']: case for case in contract['cases']}
    require(len({row['id'] for row in result['cases']}) == len(result['cases']) and
            all(row['id'] in cases for row in result['cases']), 'LABEL_RESULT_CASES_INVALID')
    inputs_by_id = {key: read(case['input_ref']) for key, case in cases.items()}
    gold_by_id = {key: _gold(read(case['expected_ref']), inputs_by_id[key]) for key, case in cases.items()}
    groups = {inputs['source_group'] for inputs in inputs_by_id.values()}
    required_decisions = sum(1 + len(inputs['allowed_topics']) for inputs in inputs_by_id.values())
    required_topic_decisions = required_decisions - len(cases)
    confusion = {}; ambiguous = sum(len(documents) != 1 for documents, _ in gold_by_id.values())
    transport_failures = 0; verified_cases = 0; document_completed = 0; document_correct = 0
    unique_topic_cases = sum(len(gold_sets) == 1 for _, gold_sets in gold_by_id.values())
    unique_gold_positives = sum(len(gold_sets[0]) for _, gold_sets in gold_by_id.values() if len(gold_sets) == 1)
    emitted_tp = 0; emitted_fp = 0; emitted_exact = 0; positive_set_matches = 0
    probability_sum_deviations = []
    totals = {key: 0 for key in ('topic_tp', 'topic_fp', 'topic_fn', 'topic_decision_count', 'decision_count',
                                 'classified_count', 'incorrect_count', 'abstained_count')}
    probability_metrics = {key: [] for key in ('document_accuracy', 'topic_exact_set', 'document_brier',
        'document_log_loss', 'topic_brier', 'topic_log_loss', 'latency_ms', 'cost')}
    for row in result['cases']:
        inputs = inputs_by_id[row['id']]; output = read(row['output_ref'])
        documents, gold_sets = gold_by_id[row['id']]
        for key in ('latency_ms', 'cost'):
            if row['metrics'][key] is not None: probability_metrics[key].append(row['metrics'][key])
        if 'LABEL_TRANSPORT_UNVERIFIED' in row['reasons']:
            transport_failures += 1
            continue
        verified_cases += 1
        document = output.get('document_type')
        document_completed += int(document is not None)
        document_correct += int(document is not None and document in documents)
        if len(documents) == 1:
            target = confusion.setdefault(documents[0], {}); prediction = document or '__abstain__'
            target[prediction] = target.get(prediction, 0) + 1
        predicted = set(output['topics'])
        positive_set_matches += int(predicted in gold_sets)
        if len(gold_sets) == 1:
            emitted_tp += len(predicted & gold_sets[0]); emitted_fp += len(predicted - gold_sets[0])
            emitted_exact += int(predicted == gold_sets[0])
        if output.get('document_probabilities') is not None:
            probability_sum_deviations.append(abs(math.fsum(output['document_probabilities'].values()) - 1))
        for key in totals: totals[key] += row['metrics'][key]
        for key in probability_metrics:
            if key not in ('latency_ms', 'cost') and row['metrics'][key] is not None:
                probability_metrics[key].append(row['metrics'][key])
    labels = set(confusion) | {pred for counts in confusion.values() for pred in counts if pred != '__abstain__'}; f1s = []
    for label in labels:
        tp = confusion.get(label, {}).get(label, 0)
        fp = sum(counts.get(label, 0) for truth, counts in confusion.items() if truth != label)
        fn = sum(n for pred, n in confusion.get(label, {}).items() if pred != label)
        if 2 * tp + fp + fn: f1s.append(2 * tp / (2 * tp + fp + fn))
    precision, recall, f1 = _prf(totals['topic_tp'], totals['topic_fp'], totals['topic_fn'])
    document_selective = (sum(probability_metrics['document_accuracy']) / len(probability_metrics['document_accuracy'])
                          if probability_metrics['document_accuracy'] else None)
    emitted_fn = unique_gold_positives - emitted_tp
    return {'status': result['status'], 'integrity_errors': result.get('errors', []),
        'cases': len(result['cases']), 'required_cases': len(cases), 'source_groups': len(groups),
        'missing_case_ids': sorted(set(cases) - {row['id'] for row in result['cases']}),
        'document_confusion': confusion, 'document_macro_f1': sum(f1s) / len(f1s) if f1s else None,
        'document_macro_f1_classes': len(f1s), 'ambiguous_document_gold_cases': ambiguous,
        'transport_failures': transport_failures, 'transport_verified_cases': verified_cases,
        'document_accuracy': document_selective, 'document_selective_accuracy': document_selective,
        'document_classified_cases': document_completed, 'document_correct_within_allowed_gold': document_correct,
        'document_completion_rate': document_completed / len(cases),
        'document_end_to_end_accuracy': document_correct / len(cases),
        'document_end_to_end_denominator': len(cases),
        'topic_micro_precision': precision if totals['topic_decision_count'] else None,
        'topic_micro_recall': recall if totals['topic_decision_count'] else None,
        'topic_micro_f1': f1 if totals['topic_decision_count'] else None,
        'topic_selective_metric_scope': 'known binary decisions only; use emitted_tag metrics for full positive-set capture',
        'emitted_tag_unique_gold_cases': unique_topic_cases,
        'emitted_tag_precision': emitted_tp / (emitted_tp + emitted_fp) if emitted_tp + emitted_fp else None,
        'emitted_tag_recall': emitted_tp / unique_gold_positives if unique_gold_positives else None,
        'emitted_tag_f1': 2 * emitted_tp / (2 * emitted_tp + emitted_fp + emitted_fn)
                          if 2 * emitted_tp + emitted_fp + emitted_fn else None,
        'emitted_tag_counts': {'tp': emitted_tp, 'fp': emitted_fp, 'missed_gold_positives': emitted_fn},
        'emitted_tag_exact_set_rate': emitted_exact / unique_topic_cases if unique_topic_cases else None,
        'positive_tag_set_match_with_allowed_ambiguity': positive_set_matches / len(cases),
        'required_decisions': required_decisions, 'classified_decisions': totals['classified_count'],
        'semantic_abstentions': totals['abstained_count'],
        'unavailable_decisions': required_decisions - totals['decision_count'],
        'coverage': totals['classified_count'] / required_decisions,
        'coverage_given_valid_transport': totals['classified_count'] / totals['decision_count'] if totals['decision_count'] else None,
        'topic_decision_completion_rate': totals['topic_decision_count'] / required_topic_decisions,
        'selective_error': totals['incorrect_count'] / totals['classified_count'] if totals['classified_count'] else None,
        'document_probability_sum_deviation': {'known': len(probability_sum_deviations),
            'max': max(probability_sum_deviations) if probability_sum_deviations else None,
            'allowed_tolerance': PROBABILITY_SUM_TOLERANCE, 'renormalized': False},
        'probabilistic_and_usage': {key: {'mean': sum(values) / len(values) if values else None,
            'known': len(values), 'unknown': len(cases) - len(values)} for key, values in probability_metrics.items()},
        'superiority_established': False, 'scope': 'grouped_development_evidence_not_calibration_or_generalization'}
