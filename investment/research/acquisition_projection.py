"""Bounded projection of registered controlled acquisition comparisons.

Only immutable allowlisted fields cross the UI boundary. This reads captured
closed results; it neither reruns a grader nor claims historical availability.
"""
from shared.research_sources.artifacts import digest, require

UNIT_PREVIEW_LIMIT = 8


def project(reader, report_ref, subject, *, text, identifier, timestamp, sha, source_dto, numeric_metrics, aggregate):
    report = reader.ref(report_ref)
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
