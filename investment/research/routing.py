"""Select helpful source capabilities without changing frozen evidence needs."""
import json
from shared.research_sources.artifacts import ROOT
from shared.research_sources.fetch import HOSTS
from .requirements import load


def compatibility(rule, provider):
    """Static compatibility is not a connectivity or coverage observation."""
    operation = any(op['name'] == 'read' and op['output_access'] == rule['minimum_access']
                    for op in provider['operations'])
    hosts = ({'arxiv.org'} if provider['id'] in ('arxiv', 'arxiv_mcp_candidate') else
             HOSTS - {'arxiv.org', 'export.arxiv.org', 'api.openalex.org'}
             if provider['id'] == 'official_document' else set())
    requested = set(rule['allowed_hosts'])
    supported = sorted(requested & hosts)
    reasons = []
    if not operation:
        reasons.append('DISCOVERY_ONLY')
    elif not supported:
        reasons.append('NO_SUPPORTED_HOST')
    if rule.get('document_format', 'html') != 'html' and operation:
        reasons.append('UNSUPPORTED_FORMAT')
    if provider['id'] == 'arxiv_mcp_candidate':
        reasons.append('OPTIONAL_CANDIDATE_NOT_DEFAULT')
    return {'read_access_available': operation, 'eligible': not reasons,
            'supported_hosts': supported, 'excluded_hosts': sorted(requested - hosts),
            'exclusion_reasons': reasons, 'readiness': 'not_checked',
            'coverage_is_not_fetch_success': True}


def routes(contract):
    snapshot = load(contract)
    catalog = json.loads((ROOT / 'shared/research_sources/catalog.json').read_text())
    return [{'requirement_id': r['id'], 'question': r['investment_question'],
             'evidence_question': r['question'], 'required_access': r['minimum_access'],
             'allowed_hosts': r['allowed_hosts'],
             'candidates': [{'provider': p['id'], 'operations': p['operations'],
                             **compatibility(r, p)}
                            for p in catalog['providers'] if r['family'] in p['families']]}
            for r in snapshot['requirements']]
