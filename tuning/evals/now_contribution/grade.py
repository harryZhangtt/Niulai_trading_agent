"""Frozen host gate over actual pipeline receipts and anonymous semantic review."""
from shared.research_sources.artifacts import read,require

DIMENSIONS=('fact_support','baseline_novelty','mechanism_calibration','unproved_links','counterevidence','forecast_discipline')


def grade(case_id,inputs,expected,output):
    result=read(output['case_result_ref']);review=read(output['review_ref'])
    require(result['case_id']==case_id==review['case_id'],'NOW_CASE_BINDING')
    require(result['packet_ref']==inputs['packet_ref'],'NOW_PACKET_BINDING')
    # Anonymous review packets deliberately copy bytes into a neutral directory.
    # Bind content identity, and validate both references, rather than their path.
    require(review['proposal_ref']['sha256']==result['proposal_ref']['sha256'] and
            read(review['proposal_ref'])==read(result['proposal_ref']),'NOW_REVIEW_BINDING')
    require(review['reviewer_role']=='arm_label_blinded_source_review','NOW_REVIEW_ROLE')
    scores=review['scores'];require(set(scores)==set(DIMENSIONS),'NOW_REVIEW_DIMENSIONS')
    require(all(v is None or type(v)is int and 0<=v<=2 for v in scores.values()),'NOW_REVIEW_SCORE')
    proposal=read(result['proposal_ref'])
    require((review['source_checks'] or not proposal['observed_facts']) and review['rationale'],
            'NOW_SOURCE_REVIEW_REQUIRED')
    checked={r['fact_index']:r for r in review['source_checks']}
    require(set(checked)==set(range(len(proposal['observed_facts']))) and
            len(checked)==len(review['source_checks']),'NOW_FACT_REVIEW_INCOMPLETE')
    require(all(checked[i]['evidence_id']==f['evidence_id'] for i,f in enumerate(proposal['observed_facts'])),
            'NOW_FACT_REVIEW_BINDING')
    supported=sum(checked[i]['support']=='supported' for i in range(len(proposal['observed_facts'])))
    require(type(review['critical_error_count'])is int and review['critical_error_count']==len(review['critical_errors']),'NOW_CRITICAL_BINDING')
    receipts=[read(ref) for ref in result['model_execution_refs']]
    transport_ok=bool(receipts) and all(r['status']=='succeeded' and r['receipt'].get('turn_completed') for r in receipts)
    tokens=[r['receipt'].get('usage') for r in receipts]
    token_total=None
    if all(isinstance(u,dict) and all(type(u.get(k))is int for k in ['input_tokens','output_tokens']) for u in tokens):
        token_total=sum(u['input_tokens']+u['output_tokens'] for u in tokens)
    metrics={**scores,'critical_error_count':review['critical_error_count'],
        'unsupported_inferences':review['unsupported_inferences'],'false_novelty':review['false_novelty'],
        'unsupported_forecast_revision':review['unsupported_forecast_revision'],
        'supported_facts':supported,'total_facts':len(proposal['observed_facts']),
        'model_turns':len(receipts),'tokens':token_total,'cost':None}
    passed=transport_ok and review['critical_error_count']==0
    return {'passed':passed,'metrics':metrics,'reasons':review['critical_errors']+([] if transport_ok else ['NOW_MODEL_TRANSPORT_UNVERIFIED'])}
