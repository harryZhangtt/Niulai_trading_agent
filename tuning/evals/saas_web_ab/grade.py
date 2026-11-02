"""Host gate over label-blind, source-grounded A/B assessments.

Scores are observations, not agent-provided pass labels. This small development
comparison cannot establish model superiority, alpha or an isolated retry effect.
"""
from shared.research_sources.artifacts import read, require

DIMENSIONS = ('recent_material_coverage', 'factual_accuracy', 'source_claim_support',
              'metric_definition_fidelity', 'economic_reasoning', 'uncertainty_handling')


def callback(case_id, inputs, expected, output):
    answer = read(output['answer_ref']); assessment = read(output['assessment_ref'])
    require(answer['company'] == inputs['company'] == assessment['company'], 'SAAS_COMPANY_BINDING')
    require(assessment['answer_ref'] == output['answer_ref'] and assessment['reference_sha256'] == output['reference_sha256'], 'SAAS_REVIEW_BINDING')
    require(assessment['reviewer_role'] == 'arm_label_blinded_source_review', 'SAAS_REVIEW_ROLE')
    scores = assessment['scores']
    require(set(scores) == set(DIMENSIONS) and all(type(v) is int and 0 <= v <= 2 for v in scores.values()), 'SAAS_SCORE_SCHEMA')
    require(type(assessment['critical_error_count']) is int and assessment['critical_error_count'] >= 0, 'SAAS_CRITICAL_ERROR_SCHEMA')
    require(type(assessment['supported_requirements']) is int and 0 <= assessment['supported_requirements'] <= 2, 'SAAS_COVERAGE_SCHEMA')
    require(assessment['source_checks'] and assessment['rationale'], 'SAAS_SOURCE_REVIEW_REQUIRED')
    metrics = {**scores, 'critical_error_count': assessment['critical_error_count'],
               'supported_requirements': assessment['supported_requirements'],
               'provider_items': output['provider_items'], 'elapsed_seconds': output['elapsed_seconds'],
               'tokens': None, 'cost': None}
    return {'passed': assessment['critical_error_count'] == 0, 'metrics': metrics,
            'reasons': assessment['critical_errors']}
