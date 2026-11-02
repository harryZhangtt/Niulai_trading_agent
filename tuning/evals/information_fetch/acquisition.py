"""Acquisition-specific deterministic gate for the existing sealed attempt ledger.

Receipt linkage is checked, not cryptographically authenticated host identity.
Call this grader in the host finish path; interpretation-only runs cannot pass.
"""
from shared.research_sources.artifacts import digest, read, require, save
from shared.research_sources.store import instant
from tuning.evals.evidence_runtime import contracts

ECONOMIC_KEY = {'entity', 'product', 'metric', 'period', 'cohort', 'unit', 'currency', 'epistemic_status', 'value_or_condition'}
METRICS = ['search_items', 'open_items', 'cache_attempts', 'provider_items', 'eligible_sources',
    'proposed_units', 'judged_units', 'unjudged_units', 'pool_unjudged_units', 'supported_unit_precision', 'unique_new_units',
    'supported_reference_coverage', 'facet_coverage', 'redundancy', 'original_lineages',
    'detection_lag_seconds', 'wall_seconds', 'tokens', 'cost', 'confirmation_units', 'known_units']


def attach_units(run_ref, unit_refs, directory):
    """Bind common pooled extraction to immutable acquisition; never rewrite it."""
    original = read(run_ref)
    require(original.get('kind') == 'acquisition_eval_run' and not original.get('unit_refs')
            and 'origin_run_ref' not in original, 'ACQ_COLLECTION_DERIVATION_INVALID')
    require(isinstance(unit_refs, list) and len(unit_refs) <= 128, 'ACQ_UNIT_ROSTER')
    opened = {sha for ref in original['open_receipt_refs'] for sha in read(ref).get('source_sha256s', [])}
    for ref in unit_refs:
        unit = read(ref)
        require(unit.get('source_ref', {}).get('sha256') in opened, 'ACQ_UNIT_NOT_OPENED')
        source, body = _source(unit['source_ref'], original['cutoff'])
        require(isinstance(unit.get('quote'), str) and bool(unit['quote']) and unit['quote'] in body,
                'ACQ_UNIT_QUOTE_INVALID')
    return save(directory, {**original, 'unit_refs': unit_refs, 'origin_run_ref': run_ref})


def canonical_id(key):
    require(isinstance(key, dict) and set(key) == ECONOMIC_KEY and
            all(isinstance(value, str) and 0 < len(value) <= 800 for value in key.values()), 'ACQ_ECONOMIC_KEY_INVALID')
    return digest(key)


def _source(ref, cutoff):
    source = read(ref); read(source['raw'], json_value=False)
    body = read(source['text'], json_value=False).decode('utf-8')
    bounds = [instant(source['retrieved_at']), instant(source['available_at'])]
    # Metadata may declare only a calendar date. This is a coarse bound, never
    # an authenticated intraday release time; the exact capture/availability
    # timestamps above remain mandatory and prevent historical backdating.
    bounds.extend(instant(source[key] + 'T00:00:00Z' if isinstance(source[key], str) and len(source[key]) == 10 else source[key])
        for key in ('published_at', 'modified_at', 'updated_at', 'version_available_at') if source.get(key) is not None)
    require(max(bounds) <= instant(cutoff), 'ACQ_FUTURE_OR_UNVERIFIED_VERSION')
    return source, body


def _operations(run, operation, exposed):
    refs = run.get(operation + '_receipt_refs')
    require(isinstance(refs, list) and 0 < len(refs) <= 32, 'ACQ_' + operation.upper() + '_RECEIPTS_REQUIRED')
    count = 0; dispatched = 0; returned = set()
    for ref in refs:
        receipt = read(ref)
        require(receipt.get('kind') == 'acquisition_operation_receipt' and receipt.get('operation') == operation and
                receipt.get('execution_id') == run['execution_id'] and receipt.get('backend') == run['backend'], 'ACQ_OPERATION_BINDING')
        request = read(receipt['request_ref']); response = read(receipt['response_ref'], json_value=False)
        require(bool(response) and isinstance(request, dict) and isinstance(request.get('items'), list)
                and 0 < len(request['items']) <= 12, 'ACQ_OPERATION_BYTES_REQUIRED')
        require(instant(run['started_at']) <= instant(receipt['started_at']) <= instant(receipt['finished_at'])
                <= instant(run['finished_at']), 'ACQ_OPERATION_TIME_BINDING')
        hashes = receipt.get('source_sha256s', [])
        require(isinstance(hashes, list) and set(hashes) <= exposed and (operation != 'open' or bool(hashes)
                or receipt.get('status') in {'failed', 'unknown'}), 'ACQ_UNSCREENED_OPERATION_RESULT')
        returned.update(hashes)
        count += len(request['items'])
        physical = receipt.get('provider_items', len(request['items']))
        require(type(physical) is int and 0 <= physical <= len(request['items']), 'ACQ_PROVIDER_ACCOUNTING')
        require(physical != 0 or receipt.get('status') == 'cache_hit', 'ACQ_UNVERIFIED_ZERO_DISPATCH')
        dispatched += physical
    return count, returned, dispatched


def validate_run(run_ref, frozen):
    run = read(run_ref)
    if run.get('origin_run_ref'):
        original = read(run['origin_run_ref'])
        require(original.get('kind') == 'acquisition_eval_run' and not original.get('unit_refs')
                and 'origin_run_ref' not in original and
                {k: v for k, v in run.items() if k not in {'unit_refs', 'origin_run_ref'}} ==
                {k: v for k, v in original.items() if k != 'unit_refs'}, 'ACQ_COLLECTION_DERIVATION_INVALID')
    require(run.get('kind') == 'acquisition_eval_run' and run.get('cohort') == frozen['cohort'], 'ACQ_RUN_KIND_OR_COHORT')
    for key in ('question_sha256', 'baseline_sha256', 'cutoff', 'model_sha256', 'backend'):
        require(run.get(key) == frozen[key], 'ACQ_CONTROL_MISMATCH')
    require(run.get('config_sha256') == frozen['arm_config_sha256'].get(run.get('arm')), 'ACQ_CONFIG_MISMATCH')
    guard = read(run['exposure_ref'])
    require(guard.get('kind') == 'acquisition_worker_exposure' and guard.get('execution_id') == run['execution_id'] and
            guard.get('cutoff') == run['cutoff'],
            'ACQ_BEFORE_WORKER_GUARD_REQUIRED')
    refs = guard.get('exposed_source_refs')
    require(isinstance(refs, list) and 0 < len(refs) <= 64, 'ACQ_EXPOSED_SOURCE_ROSTER')
    exposed = {ref['sha256'] for ref in refs}
    require(instant(run['started_at']) <= instant(run['first_worker_at']) <= instant(run['finished_at']), 'ACQ_WORKER_TIME_BINDING')
    if guard.get('exposure_mode') == 'per_operation_host_screened':
        events = guard.get('event_refs')
        require(isinstance(events, list) and 0 < len(events) <= 64, 'ACQ_EXPOSURE_EVENT_ROSTER')
        screened = set(); operation_ids = set(); event_sources = {}
        for event_ref in events:
            event = read(event_ref)
            require(event.get('kind') == 'acquisition_operation_exposure' and event.get('execution_id') == run['execution_id']
                    and event.get('cutoff') == run['cutoff'] and event.get('operation_id') not in operation_ids,
                    'ACQ_EXPOSURE_EVENT_BINDING')
            operation_ids.add(event['operation_id'])
            event_sources[event['operation_id']] = {ref['sha256'] for ref in event['exposed_source_refs']}
            require(instant(run['started_at']) <= instant(event['screened_at']) <= instant(event['exposed_at'])
                    <= instant(run['finished_at']) <= instant(run['cutoff']), 'ACQ_EXPOSURE_EVENT_TIME')
            for ref in event['exposed_source_refs']:
                require(ref['sha256'] in exposed, 'ACQ_UNSCREENED_OPERATION_RESULT')
                source, _ = _source(ref, run['cutoff'])
                require(instant(source['retrieved_at']) <= instant(event['screened_at']), 'ACQ_GUARD_PRECEDES_CAPTURE')
                screened.add(ref['sha256'])
        require(screened == exposed, 'ACQ_EXPOSURE_SOURCE_ROSTER')
        for key in ('search_receipt_refs', 'open_receipt_refs'):
            for ref in run.get(key, []):
                operation = read(ref)
                require(not operation.get('source_sha256s') or operation.get('operation_id') in operation_ids,
                        'ACQ_OPERATION_EXPOSURE_MISSING')
                if operation.get('source_sha256s'):
                    require(set(operation['source_sha256s']) == event_sources[operation['operation_id']],
                            'ACQ_OPERATION_EXPOSURE_SOURCE_MISMATCH')
    else:
        require(instant(guard['screened_at']) <= instant(run['first_worker_at']), 'ACQ_BEFORE_WORKER_GUARD_REQUIRED')
        for ref in refs:
            source, _ = _source(ref, run['cutoff'])
            require(instant(source['retrieved_at']) <= instant(guard['screened_at']), 'ACQ_GUARD_PRECEDES_CAPTURE')
    search, _, search_dispatches = _operations(run, 'search', exposed)
    opened, opened_sources, open_dispatches = _operations(run, 'open', exposed)
    cache_refs = run.get('cache_attempt_refs', [])
    require(isinstance(cache_refs, list) and len(cache_refs) <= 64, 'ACQ_CACHE_ROSTER')
    require(run['arm'] not in frozen.get('cache_required_arms', []) or bool(cache_refs), 'ACQ_CACHE_RECEIPTS_REQUIRED')
    for ref in cache_refs:
        attempt = read(ref)
        require(isinstance(attempt.get('fetch_key'), dict) and type(attempt.get('fetch_executed')) is bool and
                attempt.get('route') in {'fetch', 'cache_hit', 'cache_fallback', 'fetch_uncached', 'unresolved'}, 'ACQ_CACHE_ATTEMPT_INVALID')
        require(instant(run['started_at']) <= instant(attempt['occurred_at']) <= instant(run['finished_at']), 'ACQ_CACHE_TIME_BINDING')
        if attempt.get('source_ref'): require(attempt['source_ref']['sha256'] in exposed, 'ACQ_CACHE_SOURCE_MISMATCH')
    elapsed = (instant(run['finished_at']) - instant(run['started_at'])).total_seconds()
    usage = run['usage']; require(elapsed >= 0, 'ACQ_RUN_TIME_INVALID')
    observed = {**usage, 'search_items': search, 'open_items': opened, 'wall_seconds': elapsed}
    require(type(usage.get('provider_items')) is int and usage['provider_items'] >= search_dispatches + open_dispatches, 'ACQ_PROVIDER_ACCOUNTING')
    for key, maximum in frozen['resource_limits'].items():
        value = observed.get(key)
        require(maximum is None or type(value) in (int, float) and 0 <= value <= maximum, 'ACQ_BUDGET_OR_UNKNOWN_LIMIT')
    if frozen['cohort'] == 'cold':
        for ref in cache_refs:
            attempt = read(ref)
            if attempt.get('cache_hit'):
                require(attempt.get('source_ref') and instant(read(attempt['source_ref'])['retrieved_at']) >= instant(run['started_at']),
                        'ACQ_COLD_PRELOAD')
    return run, exposed, opened_sources, search, opened, elapsed


def grade(case_id, frozen, expected, output):
    run, exposed, opened_sources, search, opened, elapsed = validate_run(output['run_ref'], frozen)
    review = read(output['review_ref']); pool = review.get('pool_run_refs')
    require(review.get('kind') == 'acquisition_pooled_review' and review.get('arm_labels_withheld') is True and
            isinstance(review.get('reviewer_id'), str) and bool(review['reviewer_id']) and review['reviewer_id'] not in frozen['worker_ids'] and isinstance(pool, list) and len(pool) == 2 and
            output['run_ref'] in pool and len({read(ref)['execution_id'] for ref in pool}) == 2, 'ACQ_INDEPENDENT_POOLED_REVIEW_REQUIRED')
    pooled = [read(ref) for ref in pool]
    require({row['arm'] for row in pooled} == set(frozen['arm_config_sha256']), 'ACQ_POOL_ARM_ROSTER')
    for ref in pool: validate_run(ref, frozen)
    unit_refs = run.get('unit_refs', []); require(isinstance(unit_refs, list) and len(unit_refs) <= 128, 'ACQ_UNIT_ROSTER')
    all_units = {ref['sha256'] for row in pooled for ref in row['unit_refs']}
    checks = review.get('units', [])
    require(isinstance(checks, list) and len(checks) == len(all_units) and
            {check['unit_ref']['sha256'] for check in checks} == all_units, 'ACQ_POOL_REVIEW_INCOMPLETE')
    by_hash = {check['unit_ref']['sha256']: check for check in checks}
    pool_unjudged = sum(check.get('status') == 'unjudged' for check in checks)
    accepted = set(); novel = set(); confirmations = set(); known = set()
    facets = set(); lineages = set(); lags = {}; supported = judged = unjudged = 0
    for ref in unit_refs:
        unit = read(ref); check = by_hash[ref['sha256']]
        require(unit['source_ref']['sha256'] in opened_sources, 'ACQ_UNIT_SOURCE_NOT_EXPOSED')
        source, body = _source(unit['source_ref'], run['cutoff'])
        require(not (str(source.get('provider', '')).startswith('native') and source.get('access_level') == 'metadata'),
                'ACQ_METADATA_UNIT_NOT_DOCUMENT')
        require(isinstance(unit.get('quote'), str) and bool(unit['quote']) and unit['quote'] in body, 'ACQ_UNIT_QUOTE_INVALID')
        require(check.get('status') in {'judged', 'unjudged'}, 'ACQ_REVIEW_STATUS')
        if check['status'] == 'unjudged': unjudged += 1; continue
        judged += 1; require(type(check.get('supported')) is bool, 'ACQ_SUPPORT_DECISION')
        if not check['supported']: continue
        identity = canonical_id(check['economic_key']); supported += 1
        if frozen.get('novelty_labels_required'):
            require(type(check.get('answer_bearing')) is bool and check.get('novelty_kind') in
                    {'new_fact', 'refinement', 'counterevidence', 'independent_confirmation', 'redundant', 'unresolved'},
                    'ACQ_NOVELTY_REVIEW_REQUIRED')
            matched = check.get('matched_old_ids')
            require(isinstance(matched, list) and set(matched) <= set(expected['baseline_known_ids']), 'ACQ_BASELINE_MATCH_INVALID')
            if check['novelty_kind'] in {'refinement', 'counterevidence'}:
                require(isinstance(check.get('delta_explanation'), str) and bool(check['delta_explanation'].strip()),
                        'ACQ_DELTA_EXPLANATION_REQUIRED')
            if not check['answer_bearing'] or check['novelty_kind'] == 'unresolved': continue
            if check['novelty_kind'] in {'new_fact', 'refinement', 'counterevidence'}: novel.add(identity)
            elif check['novelty_kind'] == 'independent_confirmation': confirmations.add(identity)
            else: known.add(identity)
        else:
            novel.add(identity)
        accepted.add(identity)
        require(set(check['facets']) <= set(frozen['facets']) and isinstance(check['original_lineage'], str)
                and bool(check['original_lineage']), 'ACQ_FACET_OR_LINEAGE_INVALID')
        facets.update(check['facets']); lineages.add(check['original_lineage'])
        if check.get('first_verified_available_at') is not None and check.get('availability_basis') in {'first_verified_observation', 'authenticated_archive'}:
            lag = (instant(source['retrieved_at']) - instant(check['first_verified_available_at'])).total_seconds()
            require(lag >= 0, 'ACQ_INVALID_DETECTION_LAG'); lags[identity] = min(lag, lags.get(identity, lag))
    reference = set(expected['reference_unit_ids']); prior = set(expected['prior_unit_ids'])
    if frozen.get('reference_mode') == 'adjudicated_pool':
        require(frozen.get('novelty_labels_required') is True, 'ACQ_POOL_NOVELTY_POLICY_REQUIRED')
        reference = {canonical_id(check['economic_key']) for check in checks
            if check.get('status') == 'judged' and check.get('supported') is True and check.get('answer_bearing') is True
            and check.get('novelty_kind') in {'new_fact', 'refinement', 'counterevidence'}}
    metrics = {'search_items': search, 'open_items': opened, 'cache_attempts': len(run['cache_attempt_refs']),
        'provider_items': run['usage']['provider_items'], 'eligible_sources': len(exposed), 'proposed_units': len(unit_refs),
        'judged_units': judged, 'unjudged_units': unjudged, 'pool_unjudged_units': pool_unjudged,
        'supported_unit_precision': supported / judged if judged else None,
        'unique_new_units': len(novel - prior) if not pool_unjudged else None,
        'supported_reference_coverage': len(accepted & reference) / len(reference) if reference else None,
        'facet_coverage': len(facets) / len(frozen['facets']) if frozen['facets'] else None,
        'redundancy': 1 - len(accepted) / supported if supported else None, 'original_lineages': len(lineages),
        'detection_lag_seconds': sum(lags.values()) / len(lags) if lags else None, 'wall_seconds': elapsed,
        'tokens': run['usage'].get('tokens'), 'cost': run['usage'].get('cost'),
        'confirmation_units': len(confirmations), 'known_units': len(known)}
    passed = not pool_unjudged and supported == judged and judged > 0
    return {'passed': passed, 'metrics': metrics,
        'reasons': ([] if not pool_unjudged else ['ACQ_UNJUDGED_NOT_IMPROVEMENT']) + ([] if supported == judged else ['ACQ_UNSUPPORTED_UNIT'])}


def finish(contract_ref, directory, attempt_id, *, submissions, usage):
    contract = read(contract_ref); require(contract['metrics'] == METRICS, 'ACQ_METRIC_CONTRACT')
    return contracts.finish(contract_ref, directory, attempt_id, submissions=submissions, usage=usage, grade=grade)
