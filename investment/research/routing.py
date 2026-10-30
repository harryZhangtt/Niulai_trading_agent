"""Select helpful source capabilities without changing frozen evidence needs."""
import json
from shared.research_sources.artifacts import ROOT
from .requirements import load


def routes(contract):
    snapshot = load(contract)
    catalog = json.loads((ROOT / 'shared/research_sources/catalog.json').read_text())
    return [{'requirement_id': r['id'], 'question': r['investment_question'],
             'evidence_question': r['question'], 'required_access': r['minimum_access'],
             'allowed_hosts': r['allowed_hosts'],
             'candidates': [{'provider': p['id'], 'operations': p['operations'],
                             'read_access_available': any(op['name'] == 'read' and op['output_access'] == r['minimum_access'] for op in p['operations']),
                             'coverage_is_not_fetch_success': True}
                            for p in catalog['providers'] if r['family'] in p['families']]}
            for r in snapshot['requirements']]
