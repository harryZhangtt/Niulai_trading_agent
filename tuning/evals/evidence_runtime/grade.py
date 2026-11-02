"""Host-side deterministic conformance grader; no model-provided pass labels.

This is a development specification, visible to developers. It does not measure
blind reasoning quality, model alpha, or broad provider reliability.
"""
from decimal import Decimal

from shared.research_sources.artifacts import read, require
from shared.research_sources.runtime_validation import verify as verify_workload


def grade(spec, *, source_result_ref, pipeline_result, paused_result, not_before):
    """Return one outcome per frozen case after independent public-API checks."""
    from investment.research.pilot_acceptance import verify as verify_pilot, verify_resume
    verify_pilot(pipeline_result, {'scheduled_at': not_before})
    resume_verdict = verify_resume(paused_result, pipeline_result)
    verdict = verify_workload(source_result_ref, not_before=not_before)
    combined = read(source_result_ref)
    source = read(combined['source']['report_ref'])
    cache = read(combined['cache']['report_ref'])
    report = read(pipeline_result['report_ref']); request = read(pipeline_result['request_ref'])
    packet = read(request['packet_ref']); final = read(report['final_ref'])
    requirement = read(request['requirement_ref']); original_source = read(request['source_ref'])
    paused_report = read(paused_result['report_ref'])
    paused_checkpoint = read(paused_result['checkpoint_ref']); resumed_checkpoint = read(pipeline_result['checkpoint_ref'])
    expected = {case['id']: case['expected'] for case in spec['cases']}
    inputs = {case['id']: case['input'] for case in spec['cases']}
    results = {}
    def outcome(case, condition, details):
        results[case] = {'status': 'pass' if condition else 'fail', 'details': details}
    values = [Decimal(str(observation['value'])) for observation in packet['observations']]
    e = expected['earnings_fact']
    outcome('earnings_fact', values == [Decimal(e['headline_usd_millions']), Decimal(e['table_usd_millions'])]
        and abs(values[0] - values[1]) == Decimal(e['absolute_difference'])
        and Decimal(packet['absolute_tolerance']) == Decimal(e['absolute_tolerance'])
        and final['independent_sources'] is e['independent_sources']
        and all(requirement[field] == inputs['earnings_fact'][field] for field in ('entity', 'period', 'unit', 'basis'))
        and requirement['interval']['end'] == inputs['earnings_fact']['period_end']
        and original_source['source_url'] == inputs['earnings_fact']['source_url'], {'values': [str(x) for x in values], 'independent_sources': final['independent_sources']})
    outcome('phase_resume', resume_verdict.get('verified') is True and resume_verdict['comparison_runs'] == expected['phase_resume']['comparison_runs']
        and (paused_report['run_id'] == report['run_id'] == resume_verdict['execution_id']) == expected['phase_resume']['same_id']
        and (paused_checkpoint['deadline_at'] == resumed_checkpoint['deadline_at']) == expected['phase_resume']['same_deadline']
        and resume_verdict['same_frozen_releases'] == expected['phase_resume']['same_releases'], resume_verdict)
    roster = [route['case_id'] for route in source['routes']]
    outcome('source_roster', len(roster) == len(set(roster)) and set(roster) == set(inputs['source_roster']['cases'])
        and len(set(inputs['source_roster']['cases']) - set(roster)) == expected['source_roster']['omitted_cases']
        and (verdict.get('source_coverage_status') == source['status']) == expected['source_roster']['coverage_reported_separately']
        and expected['source_roster']['mcp_fresh_remote_http'] == 'unknown', {'roster': roster, 'coverage_status': source['status'],
        'distinct_usable_cases': verdict['distinct_usable_cases'], 'mcp_fresh_remote_http': None})
    v = verdict['cache']; valid_cache = v.get('verified') is True
    outcome('cache_cold_warm', valid_cache and v['live_provider_acquisitions'] == expected['cache_cold_warm']['cold_acquisitions']
        and v['additional_warm_provider_calls'] == expected['cache_cold_warm']['additional_warm_calls']
        and (cache['live']['cold']['outcome']['source_ref'] == cache['live']['warm']['outcome']['source_ref']) == expected['cache_cold_warm']['same_source_ref'], {'live_acquisitions': v.get('live_provider_acquisitions'), 'extra_warm_calls': v.get('additional_warm_provider_calls')})
    outcome('cache_singleflight', valid_cache and v['five_process_callbacks'] == expected['cache_singleflight']['provider_callbacks'] and v['five_process_cache_hits'] == expected['cache_singleflight']['cache_hits'],
            {key: v.get(key) for key in ('five_process_callbacks', 'five_process_cache_hits')})
    outcome('cache_hundred_warm', valid_cache and v['hundred_warm_hits'] == expected['cache_hundred_warm']['cache_hits'], {'warm_hits': v.get('hundred_warm_hits')})
    negatives = cache['negatives']
    wrong = negatives['wrong_key']['outcome']
    outcome('cache_bad_identity', wrong['status'] == expected['cache_bad_identity']['status']
            and expected['cache_bad_identity']['reason'] in wrong['reasons'], {'status': wrong['status']})
    expired = negatives['expiry_without_policy']['outcome']; stale = negatives['expiry_explicit_fixed_fact_fallback']['outcome']
    outcome('cache_stale_policy', expired['status'] == expected['cache_stale_policy']['without_policy'] and stale['route'] == expected['cache_stale_policy']['explicit_fixed_fact_policy']
        and (read(stale['source_ref'])['retrieved_at'] == negatives['original_retrieved_at']) == expected['cache_stale_policy']['original_time_preserved'], {'expired_status': expired['status'], 'fallback_route': stale['route']})
    corrupt = negatives['corrupt']['outcome']
    outcome('cache_corruption', valid_cache and corrupt['status'] == expected['cache_corruption']['status']
        and expected['cache_corruption']['reason'] in corrupt['reasons']
        and expected['cache_corruption']['quarantined'] is True, {'status': corrupt['status']})
    from shared.research_sources.artifacts import SourceError
    from shared.research_sources.fetch import passages
    eligibility = []; ineligible_count = 0; metadata_rejections = 0
    for replay in cache['replays']:
        supported = replay['claim_coverage']['status'] == 'pass'
        actual = replay['decision_eligible_warm']['outcome']
        ineligible_count += not supported
        if read(replay['source_ref'])['access_level'] == 'metadata':
            try: passages(replay['source_ref'])
            except SourceError as error:
                require(str(error) == 'DOCUMENT_READ_REQUIRED', 'EVAL_METADATA_DIAGNOSTIC')
                metadata_rejections += 1
            else: eligibility.append(False)
        eligibility.append(supported and actual['route'] == 'cache_hit' or
                           not supported and actual['route'] == 'unresolved' and actual['source_ref'] is None)
    outcome('cache_claim_eligibility', bool(eligibility) and all(eligibility)
        and expected['cache_claim_eligibility']['ineligible_source_cannot_be_used'] is True
        and expected['cache_claim_eligibility']['metadata_is_not_document'] is True
        and ineligible_count >= expected['cache_claim_eligibility']['min_ineligible_cases']
        and metadata_rejections >= expected['cache_claim_eligibility']['min_metadata_rejections'], {'replays_checked': len(eligibility), 'ineligible_cases': ineligible_count, 'metadata_rejections': metadata_rejections, 'method': 'metamorphic consistency; not a semantic truth oracle'})
    require(set(results) == set(expected), 'EVAL_GRADE_ROSTER_MISMATCH')
    return results


def callback(spec):
    """A pinned host callback. Submitted artifacts contain evidence, not grades."""
    from datetime import datetime
    from shared.research_sources.artifacts import digest
    memo = {}
    def evaluate(case_id, case_input, expected, observation):
        sealed_case = next(case for case in spec['cases'] if case['id'] == case_id)
        require(case_input == sealed_case['input'] and expected == sealed_case['expected'], 'EVAL_CALLBACK_SPEC_MISMATCH')
        key = digest(observation)
        if key not in memo:
            graded = grade(spec, source_result_ref=observation['source_result_ref'],
                           pipeline_result=observation['pipeline_result'],
                           paused_result=observation['paused_result'], not_before=observation['not_before'])
            workload = read(observation['source_result_ref'])
            sources = read(workload['source']['report_ref']); cache = read(workload['cache']['report_ref'])
            report = read(observation['pipeline_result']['report_ref'])
            usage = list(report.get('model_usage_observed', [])) + [observation.get('source_agent_usage')]
            tokens = (sum(item.get('input_tokens', 0) + item.get('output_tokens', 0) for item in usage)
                      if usage and all(isinstance(item, dict) and 'input_tokens' in item and 'output_tokens' in item for item in usage) else None)
            usable = [item for item in sources['attempts'] if item['status'] == 'returned']
            warm = [cache['live']['warm']['outcome']] + [row['integrity_warm']['outcome'] for row in cache['replays']]
            metrics = {'source_capabilities_returned': len({row['case_id'] for row in usable}),
                'source_attempts_total': len(sources['attempts']), 'source_attempts_usable': len(usable),
                'cache_warm_hit_count': sum(row['cache_hit'] for row in warm), 'cache_warm_read_count': len(warm),
                'provider_calls_observed_excluding_mcp': sources['observability']['observed_direct_http_calls'] + 1,
                'latency_seconds': (datetime.fromisoformat(observation['completed_at']) - datetime.fromisoformat(observation['not_before'])).total_seconds(),
                'observed_tokens': tokens, 'observed_cost': None}
            memo[key] = graded, metrics
        graded, metrics = memo[key]
        row = graded[case_id]
        return {'passed': row['status'] == 'pass', 'metrics': {'case_correctness': row['status'] == 'pass', **metrics},
                'reasons': [] if row['status'] == 'pass' else ['HOST_POSTCONDITION_FAILED']}
    return evaluate
