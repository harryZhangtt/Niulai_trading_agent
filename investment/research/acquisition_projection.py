"""Bounded projection of registered controlled acquisition comparisons.

Only immutable allowlisted fields cross the UI boundary. This reads captured
closed results; it neither reruns a grader nor claims historical availability.
"""
import ipaddress
from urllib.parse import urlsplit, urlunsplit

from shared.research_sources.artifacts import digest, require
from investment.research.acquisition_trace import check_acquisition_trace

UNIT_PREVIEW_LIMIT = 8
TRACE_OPERATION_LIMIT = 8
TRACE_TEXT_LIMIT = 16


def _public_source_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in {'https', 'http'} or not host or parsed.username or parsed.password \
                or host in {'localhost', '127.0.0.1', '::1'} or host.endswith(('.local', '.internal')):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError:
        return None


def _safe_arguments(arguments, *, text, identifier, source_url):
    require(isinstance(arguments, dict), 'ACQ_TRACE_ARGUMENTS_INVALID')
    permitted = {'search_query', 'open', 'find', 'response_length'}
    require(set(arguments) <= permitted, 'ACQ_TRACE_ARGUMENTS_INVALID')
    result = {}
    for key in ('search_query', 'open', 'find'):
        if key not in arguments:
            continue
        rows = arguments[key]
        require(isinstance(rows, list) and 0 < len(rows) <= 4, 'ACQ_TRACE_ARGUMENTS_INVALID')
        clean = []
        for row in rows:
            require(isinstance(row, dict) and len(row) <= 4, 'ACQ_TRACE_ARGUMENTS_INVALID')
            item = {}
            for field in ('q', 'query', 'pattern'):
                if field in row:
                    item[field] = text(row[field], 1200)
            if 'ref_id' in row:
                item['ref_id'] = source_url(row['ref_id'])
            require(item and all(value is not None for value in item.values()), 'ACQ_TRACE_ARGUMENTS_UNSAFE')
            clean.append(item)
        result[key] = clean
    if 'response_length' in arguments:
        result['response_length'] = identifier(arguments['response_length'], None)
        require(result['response_length'] is not None, 'ACQ_TRACE_ARGUMENTS_INVALID')
    require(any(key in result for key in ('search_query', 'open', 'find')), 'ACQ_TRACE_ARGUMENTS_INVALID')
    return result


def project_driver_trace(reader, envelope_ref, subject, *, text, identifier, timestamp, sha, source_dto, source_url):
    envelope = reader.ref(envelope_ref)
    require(envelope.get('kind') == 'acquisition_driver_projection' and envelope.get('schema_version') == 1
            and envelope.get('subject') == subject, 'ACQ_TRACE_ENVELOPE_INVALID')
    driver_ref = envelope.get('driver_ref'); driver = reader.ref(driver_ref)
    require(driver.get('kind') == 'acquisition_driver_run', 'ACQ_TRACE_DRIVER_INVALID')
    identities = {key: identifier(driver.get(key), None) for key in ('experiment_id', 'execution_id', 'trace_id')}
    require(all(identities.values()), 'ACQ_TRACE_IDENTITY_INVALID')
    verdict = envelope.get('checker_verdict')
    require(isinstance(verdict, dict) and verdict.get('kind') == 'acquisition_trace_verdict'
            and verdict.get('status') == 'pass' and verdict.get('complete_chains') == verdict.get('credited_units') == 1
            and all(verdict.get(key) == value for key, value in identities.items()), 'ACQ_TRACE_CHECKER_REJECTED')
    gates = verdict.get('gates')
    require(isinstance(gates, list) and 0 < len(gates) <= 32
            and all(isinstance(row, dict) and row.get('passed') is True
                    and identifier(row.get('gate'), None) is not None
                    and isinstance(row.get('reasons'), list) and 0 < len(row['reasons']) <= 4 for row in gates),
            'ACQ_TRACE_CHECKER_REJECTED')
    expected_verdict_hash = digest([
        identities, 'pass', 1, 1, gates, verdict.get('trust_policy'),
        verdict.get('host_session_id'), verdict.get('host_adapter'),
        verdict.get('live_acceptance_eligible')])
    require(verdict.get('verdict_sha256') == expected_verdict_hash, 'ACQ_TRACE_CHECKER_HASH_INVALID')
    expected_dispatches = envelope.get('expected_dispatches')
    require(type(expected_dispatches) is int and 0 <= expected_dispatches <= TRACE_OPERATION_LIMIT,
            'ACQ_TRACE_EXPECTED_DISPATCHES_INVALID')
    recomputed = check_acquisition_trace(driver_ref=driver_ref, dispatch_refs=envelope.get('dispatch_refs', []),
        host_invocation_refs=envelope.get('host_invocation_refs', []),
        review_refs=envelope.get('review_refs', []), proposal_refs=envelope.get('proposal_refs', []),
        expected_dispatches=expected_dispatches, reconciliation_ref=envelope.get('reconciliation_ref'),
        host_profile_ref=envelope.get('host_profile_ref'),
        credential_readiness_ref=envelope.get('credential_readiness_ref'),
        trust_policy=envelope.get('trust_policy'), host_session_id=envelope.get('host_session_id'),
        host_adapter=envelope.get('host_adapter'))
    require(recomputed == verdict, 'ACQ_TRACE_CHECKER_MISMATCH')

    controller = reader.ref(driver['controller_summary_ref']); manifest = reader.ref(controller['manifest_ref'])
    host = reader.ref(driver['host_run_ref'])
    questions = manifest.get('questions')
    require(isinstance(questions, list) and 0 < len(questions) <= 8, 'ACQ_TRACE_QUESTIONS_INVALID')
    question_by_id = {row.get('id'): row for row in questions if isinstance(row, dict)}
    require(len(question_by_id) == len(questions), 'ACQ_TRACE_QUESTIONS_INVALID')
    proposals = [reader.ref(ref) for ref in envelope.get('proposal_refs', [])]
    dispatches = [reader.ref(ref) for ref in envelope.get('dispatch_refs', [])]
    reviews = [reader.ref(ref) for ref in envelope.get('review_refs', [])]
    receipt_refs = host.get('search_receipt_refs', []) + host.get('open_receipt_refs', [])
    require(all(isinstance(rows, list) and len(rows) <= TRACE_OPERATION_LIMIT for rows in
                (envelope.get('proposal_refs', []), envelope.get('dispatch_refs', []), envelope.get('review_refs', []), receipt_refs)),
            'ACQ_TRACE_OPERATION_LIMIT')
    receipts = [reader.ref(ref) for ref in receipt_refs]
    operation_ids = set(driver.get('operation_states', {}))
    require(operation_ids and len(operation_ids) <= TRACE_OPERATION_LIMIT, 'ACQ_TRACE_OPERATION_LIMIT')
    by_proposal = {row.get('operation_id'): row for row in proposals}
    by_dispatch = {row.get('operation_id'): row for row in dispatches}
    by_receipt = {row.get('operation_id'): row for row in receipts}
    require(set(by_proposal) == operation_ids and set(by_receipt) == operation_ids
            and set(by_dispatch) <= operation_ids, 'ACQ_TRACE_OPERATION_BINDING_INVALID')

    operations = []
    for operation_id in sorted(operation_ids):
        proposal = by_proposal[operation_id]; receipt = by_receipt[operation_id]; dispatch = by_dispatch.get(operation_id)
        request = reader.ref(receipt['request_ref']); arguments = request.get('arguments')
        require(proposal.get('arguments') == arguments, 'ACQ_TRACE_ARGUMENTS_MISMATCH')
        history = driver['operation_states'][operation_id]
        require(isinstance(history, list) and 0 < len(history) <= 32 and history[-1].get('state') == 'finalized',
                'ACQ_TRACE_STATE_INVALID')
        question_ids = proposal.get('question_ids')
        require(isinstance(question_ids, list) and 0 < len(question_ids) <= 8
                and set(question_ids) <= set(question_by_id), 'ACQ_TRACE_QUESTIONS_INVALID')
        operations.append({'operation_id': identifier(operation_id),
            'question_ids': [identifier(value) for value in question_ids],
            'proposal_sha256': digest(proposal), 'arguments_sha256': digest(arguments),
            'arguments': _safe_arguments(arguments, text=text, identifier=identifier, source_url=source_url),
            'attempt_id': identifier(dispatch.get('attempt_id'), None) if dispatch else None,
            'dispatch_id': identifier(dispatch.get('dispatch_id'), None) if dispatch else None,
            'states': [identifier(row.get('state')) for row in history],
            'provider_route': identifier(receipt.get('route') or host.get('backend'), None),
            'cache_hit': receipt.get('cache_hit') if type(receipt.get('cache_hit')) is bool else None,
            'fetch_executed': receipt.get('fetch_executed') if type(receipt.get('fetch_executed')) is bool else None,
            'status': identifier((dispatch or receipt).get('status')),
            'failure_code': identifier(receipt.get('code'), None),
            'started_at': timestamp((dispatch or {}).get('started_at') or receipt.get('started_at')),
            'finished_at': timestamp((dispatch or {}).get('finished_at') or receipt.get('finished_at')),
            'receipt_sha256': next(ref['sha256'] for ref in receipt_refs if reader.ref(ref).get('operation_id') == operation_id)})

    units = []
    source_rows = {}
    for review_ref, review in zip(envelope.get('review_refs', []), reviews):
        require(review.get('kind') == 'acquisition_reviewer_decision'
                and all(review.get(key) == value for key, value in identities.items()), 'ACQ_TRACE_REVIEW_INVALID')
        binding = review.get('binding'); require(isinstance(binding, dict), 'ACQ_TRACE_REVIEW_INVALID')
        assessment = reader.ref(binding['assessment_ref']); unit = reader.ref(binding['unit_ref']); source_ref = binding['source_ref']
        source = reader.ref(source_ref); body = reader.ref(source['text'], json_value=False).decode('utf-8')
        quote = assessment.get('quote')
        require(unit.get('assessment_ref') == binding['assessment_ref'] and isinstance(quote, str)
                and 0 < len(quote) <= 8000 and quote in body, 'ACQ_TRACE_QUOTE_INVALID')
        public_source = source_dto(source, source_ref, subject); source_rows[public_source['id']] = public_source
        units.append({'unit_id': identifier(unit.get('unit_id')), 'question_id': identifier(unit.get('question_id')),
            'operation_id': identifier(assessment.get('operation_id')), 'assessment_sha256': binding['assessment_ref']['sha256'],
            'unit_sha256': binding['unit_ref']['sha256'], 'source_id': public_source['id'],
            'source_sha256': source_ref['sha256'], 'raw_sha256': sha(binding.get('raw_sha256')),
            'text_sha256': sha(binding.get('text_sha256')), 'source_version': sha(binding.get('source_version')),
            'quote': text(quote, 1200), 'quote_truncated': len(quote) > 1200,
            'review_id': identifier(review.get('review_id')), 'review_sha256': review_ref['sha256'],
            'reviewer_id': identifier(review.get('reviewer_id')), 'review_disposition': identifier(review.get('disposition')),
            'review_checks': {key: value for key, value in review.get('checks', {}).items()
                              if key in {'question_relevance', 'literal_support', 'canonical_lineage'} and type(value) is bool},
            'review_reason': text(review.get('reason'), 800),
            'lineage': {'canonical_disclosure_id': identifier(source.get('canonical_disclosure_id'), None),
                'representation_kind': identifier(source.get('representation_kind'), None),
                'representation_relationship': identifier(source.get('representation_relationship'), None)},
            'times': {'published_at': timestamp(source.get('published_at')),
                'modified_at': timestamp(source.get('modified_at')), 'available_at': timestamp(source.get('available_at')),
                'first_observed_at': timestamp(source.get('first_observed_at')),
                'retrieved_at': timestamp(source.get('retrieved_at')), 'screened_at': timestamp(assessment.get('screened_at')),
                'exposed_at': timestamp(assessment.get('exposed_at'))}})
    require(len(units) == 1 and units[0]['review_disposition'] == 'approve', 'ACQ_TRACE_REVIEW_INVALID')
    accounting = {'logical_operations': len(operation_ids),
        'reserved_provider_items': controller.get('usage', {}).get('provider_items') if type(controller.get('usage', {}).get('provider_items')) is int else None,
        'actual_dispatches': sum(row.get('provider_items', 1) for row in dispatches if row.get('invocation_started') is True),
        'cache_hits': sum(row.get('cache_hit') is True for row in receipts),
        'fallbacks': sum(row.get('route') == 'fallback' for row in receipts),
        'complete_chains': 1, 'credited_units': 1}
    limitations = ['Checker-approved structural trace; this does not establish provider quality, acquisition improvement, investment quality or alpha.',
        'Unavailable values are shown as unavailable and are never inferred by the UI.']
    trace = {'id': identities['trace_id'], **identities, 'driver_sha256': driver_ref['sha256'],
        'checker_verdict': 'pass', 'checker_verdict_sha256': verdict['verdict_sha256'],
        'trust_policy': identifier(verdict.get('trust_policy'), None),
        'host_adapter': identifier(verdict.get('host_adapter'), None),
        'live_acceptance_eligible': verdict.get('live_acceptance_eligible') is True,
        'cryptographic_remote_attestation': False,
        'operational_evidence_limit': 'does_not_resist_malicious_same_user_file_forgery',
        'checker_gates': [{'id': identifier(row['gate']), 'status': 'pass',
                           'reasons': [text(reason, 500) for reason in row['reasons'][:4]]} for row in gates],
        'case_id': identifier(envelope.get('case_id'), None),
        'questions': [{'id': identifier(row.get('id')), 'question': text(row.get('question'), 1200)} for row in questions],
        'operations': operations, 'accounting': accounting, 'units': units, 'missing_links': [],
        'limitations': limitations, 'scope': 'checker_approved_structural_trace_not_quality_evidence'}
    comparison = {'id': 'trace_' + identities['trace_id'], 'title': subject + ' acquisition driver trace',
        'scope': trace['scope'], 'status': 'qualified', 'arms': [], 'rows': [], 'superiority_established': False,
        'limitations': limitations, 'driver_trace': trace}
    return comparison, list(source_rows.values())


def project(reader, report_ref, subject, *, text, identifier, timestamp, sha, source_dto, numeric_metrics, aggregate, source_url=_public_source_url):
    report = reader.ref(report_ref)
    if report.get('kind') == 'acquisition_driver_projection':
        return project_driver_trace(reader, report_ref, subject, text=text, identifier=identifier, timestamp=timestamp,
            sha=sha, source_dto=source_dto, source_url=source_url)
    require(report.get('kind') == 'controlled_acquisition_comparison' and report.get('schema_version') == 1,
            'ACQ_PROJECTION_KIND_INVALID')
    common = reader.ref(report['common_ref']); contract = reader.ref(report['contract_ref'])
    tasks = common.get('tasks', [])
    require(isinstance(tasks, list) and 0 < len(tasks) <= 6 and all(
        isinstance(task, dict) and task.get('id', '').startswith(subject + '_')
        and isinstance(task.get('required_answer_bearing_facets'), list) for task in tasks), 'ACQ_PROJECTION_SUBJECT_INVALID')
    require(len(contract.get('cases', [])) == 1 and set(report['result_refs']) == set(report['original_run_refs']) == {'A', 'B'}
            and set(report['review_refs']) == {'forward', 'reverse'}, 'ACQ_PROJECTION_ROSTER_INVALID')
    reviews = {order: reader.ref(ref) for order, ref in report['review_refs'].items()}
    checks = {}
    for order, review in reviews.items():
        rows = review.get('units')
        require(review.get('kind') == 'acquisition_pooled_review' and review.get('arm_labels_withheld') is True
                and isinstance(rows, list) and len(rows) <= 256 and len({row['unit_ref']['sha256'] for row in rows}) == len(rows)
                and len(review.get('pool_run_refs', [])) == 2, 'ACQ_PROJECTION_REVIEW_INVALID')
        checks[order] = {row['unit_ref']['sha256']: row for row in rows}
    require(checks['forward'].keys() == checks['reverse'].keys(), 'ACQ_PROJECTION_REVIEW_ROSTER_MISMATCH')
    sources = {}; collections = []; arms = []; derived_hashes = set(); all_units = set(); replicates = []; captures = []
    controls = None
    for arm in ['A', 'B']:
        result_ref = report['result_refs'][arm]; result = reader.ref(result_ref)
        require(result.get('arm') == {'A': 'candidate', 'B': 'baseline'}[arm] and result.get('contract_ref') == report['contract_ref']
                and len(result.get('cases', [])) == 1, 'ACQ_PROJECTION_RESULT_BINDING_INVALID')
        case = result['cases'][0]
        require(case['id'] == contract['cases'][0]['id'] and case.get('metrics') == report['primary_metrics'][arm],
                'ACQ_PROJECTION_METRIC_BINDING_INVALID')
        submission = reader.ref(case['output_ref']); derived_ref = submission['run_ref']; derived = reader.ref(derived_ref)
        original_ref = report['original_run_refs'][arm]; run = reader.ref(original_ref); config = reader.ref(run['config_ref'])
        require(run.get('kind') == 'acquisition_eval_run' and run.get('arm') == arm and run.get('unit_refs') == []
                and derived.get('origin_run_ref') == original_ref
                and {k: v for k, v in derived.items() if k not in {'unit_refs', 'origin_run_ref'}} == {k: v for k, v in run.items() if k != 'unit_refs'}
                and run.get('baseline_sha256') == report['common_ref']['sha256'] and config.get('baseline_ref') == report['common_ref']
                and run.get('config_sha256') == run['config_ref']['sha256'] and config.get('execution_id') == run.get('execution_id')
                and config.get('arm') == arm and config.get('backend') == run.get('backend')
                and submission.get('review_ref') == report['review_refs']['forward']
                and submission.get('replicate_review_ref') == report['review_refs']['reverse'], 'ACQ_PROJECTION_COLLECTION_BINDING_INVALID')
        matched = {key: run.get(key) for key in ['question_sha256', 'baseline_sha256', 'cutoff', 'model_sha256', 'backend', 'cohort']}
        require(controls is None or controls == matched, 'ACQ_PROJECTION_CONTROL_MISMATCH'); controls = matched
        derived_hashes.add(derived_ref['sha256']); replicates.append(submission.get('replicate_metrics_equal') is True)
        refs = run.get('source_refs', []); unit_refs = derived.get('unit_refs', []); cache_refs = run.get('cache_attempt_refs', [])
        require(isinstance(refs, list) and 0 < len(refs) <= 64 and isinstance(unit_refs, list) and 0 < len(unit_refs) <= 128
                and isinstance(cache_refs, list) and len(cache_refs) <= 64, 'ACQ_PROJECTION_PREVIEW_LIMIT')
        by_source = {ref['sha256']: ref for ref in refs}; all_units.update(ref['sha256'] for ref in unit_refs)
        cache = [reader.ref(ref) for ref in cache_refs]
        operation_refs = run.get('search_receipt_refs', []) + run.get('open_receipt_refs', [])
        require(0 < len(operation_refs) <= 64, 'ACQ_PROJECTION_OPERATION_LIMIT')
        for ref in operation_refs:
            operation = reader.ref(ref)
            require(operation.get('kind') == 'acquisition_operation_receipt' and operation.get('execution_id') == run['execution_id']
                    and operation.get('backend') == run['backend'], 'ACQ_PROJECTION_OPERATION_BINDING_INVALID')
        source_rows = []
        for ref in refs:
            capture = reader.ref(ref); captures.append(capture)
            source = source_dto(capture, ref, subject); sources[source['id']] = source; source_rows.append(source)
        previews = []
        for ref in unit_refs[:UNIT_PREVIEW_LIMIT]:
            unit = reader.ref(ref); check = checks['forward'].get(ref['sha256']); reverse = checks['reverse'].get(ref['sha256'])
            require(check is not None and reverse is not None and unit.get('source_ref', {}).get('sha256') in by_source
                    and by_source[unit['source_ref']['sha256']] == unit['source_ref'], 'ACQ_PROJECTION_UNIT_BINDING_INVALID')
            source = reader.ref(unit['source_ref']); body = reader.ref(source['text'], json_value=False).decode('utf-8')
            require(isinstance(unit.get('quote'), str) and 0 < len(unit['quote']) <= 8000 and unit['quote'] in body,
                    'ACQ_PROJECTION_QUOTE_INVALID')
            economic = check.get('economic_key', {})
            previews.append({'id': identifier(unit.get('id')), 'unit_sha256': ref['sha256'],
                'claim': text(unit.get('claim'), 900), 'quote': text(unit['quote'], 1000), 'quote_truncated': len(unit['quote']) > 1000,
                'source_id': 'src_' + unit['source_ref']['sha256'], 'source_sha256': unit['source_ref']['sha256'],
                'supported': check.get('supported') if type(check.get('supported')) is bool else None,
                'answer_bearing': check.get('answer_bearing') if type(check.get('answer_bearing')) is bool else None,
                'novelty_kind': identifier(check.get('novelty_kind')), 'tasks': [identifier(value) for value in check.get('facets', [])[:6]],
                'epistemic_status': text(economic.get('epistemic_status'), 160),
                'period': text(economic.get('period'), 180), 'unit': text(economic.get('unit'), 180),
                'lineage': text(check.get('original_lineage'), 180),
                'freshness': [identifier(check.get('freshness_class')), identifier(reverse.get('freshness_class'))],
                'first_verified_available_at': timestamp(check.get('first_verified_available_at')),
                'annotation_status': 'provisional', 'limitations': [text(value, 500) for value in check.get('limitations', [])[:6]]})
        metrics = numeric_metrics(case['metrics'])
        arms.append({'id': arm, 'status': identifier(result.get('status')), 'denominator': 1, 'denominator_scope': 'one_correlated_workload',
            'metrics': aggregate([metrics]), 'receipt_sha256': result_ref['sha256']})
        collections.append({'arm': arm, 'execution_id': identifier(run.get('execution_id')), 'status': identifier(run.get('status')),
            'review_status': identifier(result.get('status')), 'backend': identifier(run.get('backend')), 'cohort': identifier(run.get('cohort')),
            'cutoff': timestamp(run.get('cutoff')), 'started_at': timestamp(run.get('started_at')), 'finished_at': timestamp(run.get('finished_at')),
            'collection_sha256': original_ref['sha256'], 'config_sha256': run['config_ref']['sha256'],
            'baseline_sha256': report['common_ref']['sha256'], 'query': text(config.get('question'), 1200),
            'cache_enabled': config.get('cache_enabled') is True,
            'native_callbacks': len(operation_refs),
            'budget': {key: value if type(value) in (int, float) else None for key, value in config.get('budget', {}).items() if key in {'search_items', 'open_items', 'provider_items', 'wall_seconds'}},
            'metrics': metrics, 'cache_outcomes': {'misses': sum(row.get('status') == 'miss' for row in cache),
                'published_captures': sum(row.get('route') == 'fetch' and row.get('source_ref') is not None for row in cache),
                'hits': sum(row.get('cache_hit') is True for row in cache), 'fallbacks': sum(row.get('route') == 'cache_fallback' for row in cache)},
            'financial_context_period': next((text(checks['forward'][ref['sha256']].get('economic_key', {}).get('period'), 180)
                for ref in unit_refs if ref['sha256'] in checks['forward'] and checks['forward'][ref['sha256']].get('answer_bearing') is False
                and checks['forward'][ref['sha256']].get('economic_key', {}).get('epistemic_status') == 'issuer_reported_company_wide_actual'), None),
            'sources': source_rows, 'units': previews, 'units_total': len(unit_refs), 'units_truncated': len(unit_refs) - len(previews)})
    require(all_units == set(checks['forward']) and all(
        {ref['sha256'] for ref in review['pool_run_refs']} == derived_hashes for review in reviews.values()), 'ACQ_PROJECTION_POOL_BINDING_INVALID')
    sensitivity = report.get('exploratory_sensitivity', {})
    tasks_out = []
    for task in tasks:
        task_id = task['id']; counts = {arm: report.get('per_task_new_units', {}).get(arm, {}).get(task_id) for arm in ['A', 'B']}
        require(all(type(value) is int and 0 <= value <= 128 for value in counts.values()), 'ACQ_PROJECTION_TASK_COUNTS_INVALID')
        tasks_out.append({'id': identifier(task_id), 'question': text(task.get('question'), 1200), 'required_facets': len(task['required_answer_bearing_facets']), **counts})
    quality = {}
    for arm in ['A', 'B']:
        entry = sensitivity.get(arm, {})
        require(type(entry.get('excluding_explicitly_anonymous_reports')) is int and 0 <= entry['excluding_explicitly_anonymous_reports'] <= report['primary_metrics'][arm]['unique_new_units'], 'ACQ_PROJECTION_SENSITIVITY_INVALID')
        quality[arm] = entry['excluding_explicitly_anonymous_reports']
    forward, reverse = checks['forward'], checks['reverse']
    return {'id': identifier(report.get('id')), 'title': subject + ' native acquisition · current controlled pair',
        'scope': text(report.get('scope'), 500), 'status': 'qualified', 'arms': arms, 'rows': [], 'superiority_established': False,
        'limitations': [text(value, 700) for value in report.get('quality_limits', [])[:16]],
        'acquisition': {'report_sha256': report_ref['sha256'], 'baseline_sha256': report['common_ref']['sha256'],
            'contract_sha256': report['contract_ref']['sha256'], 'collections': collections, 'tasks': tasks_out,
            'capture_counts': {'instances': len(captures), 'search_metadata': sum(row.get('access_level') == 'metadata' for row in captures),
                'document_instances': sum(row.get('access_level') == 'document' for row in captures),
                'unique_document_bodies': len({row['text']['sha256'] for row in captures if row.get('access_level') == 'document'})},
            'sensitivity_excluding_anonymous': quality,
            'reviews': {'count': 2, 'replicate_metrics_equal': all(replicates), 'units_reviewed': len(forward),
                'unique_observations': len({row.get('id') for row in forward.values()}),
                'unique_documents': len({row.get('doc_id') for row in forward.values()}),
                'answer_bearing_pool': len({digest(row['economic_key']) for row in forward.values() if row.get('supported') is True
                    and row.get('answer_bearing') is True and row.get('novelty_kind') in {'new_fact', 'refinement', 'counterevidence'}}),
                'freshness_disagreements': sum(row.get('freshness_class') != reverse[key].get('freshness_class') for key, row in forward.items()),
                'unique_freshness_disagreements': len({row.get('id') for key, row in forward.items()
                    if row.get('freshness_class') != reverse[key].get('freshness_class')}),
                'unknown_first_availability': sum(row.get('first_verified_available_at') is None for row in forward.values()),
                'unique_unknown_first_availability': len({row.get('id') for row in forward.values() if row.get('first_verified_available_at') is None}),
                'receipt_sha256s': [ref['sha256'] for ref in report['review_refs'].values()]},
            'scope': 'one_native_pair_three_correlated_tasks_not_statistical_superiority'}}, list(sources.values())
