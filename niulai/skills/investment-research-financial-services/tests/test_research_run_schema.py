"""Domain-record regression tests using the maintained jsonschema validator.

Synthetic records test structure only; they are not research or proof of facts.
Install schemas/requirements.txt or provide it through the runtime environment.
"""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/'schemas/research-run.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
TOPICS = ['scope_prior_thesis','business_economics','industry_technology',
          'operating_cash_quality','expectations_valuation','scenarios_decision',
          'edge_falsification','review_publication','profit_scalability_value_capture']
HASH = 'a'*64
STAMP = '2026-10-18T12:00:00Z'


def fixture():
    d=json.loads((ROOT/'schemas/research-run.template.json').read_text())
    # A genuinely earlier fixture protects compatibility with archived v2 runs.
    d['schema_version']='2026-10-18-research-run-2'
    d.pop('rationale_evidence',None);d.pop('entry_policy_evidence',None)
    d.update(run_id='synthetic-schema-test',request='Research synthetic fixture',status='complete',
       skill_revision='synthetic-test-revision',
       policy_versions={'growth_aware':'2026-10-15-growth-aware-1',
                        'modeling':'2026-10-15-modeling-1','leveraged_funds':'2026-10-18-leveraged-funds-2'})
    d['subject']={'ticker':'FIXTURE','security_type':'company','identity_claim_ids':['c1'],
        'cutoff':STAMP,'quote_timestamp':STAMP,'fiscal_periods':['synthetic'],
        'units':'USD, synthetic','economics_classification':'growth'}
    for s in d['stages']: d['stages'][s]={'status':'complete','evidence_refs':['report']}
    d['stages']['persistence']={'status':'pending'}
    d['sources']=[{'id':'s1','url':'https://example.invalid/fixture','title':'Synthetic source',
        'source_type':'primary','published_at':None,'retrieved_at':STAMP,
        'reporting_period':'synthetic','snapshot_artifact_id':'source','passages':[
            {'id':'p1','locator':'synthetic fixture only','text':'Not a real company fact.'}]}]
    d['claims']=[{'id':'c1','kind':'reported_fact','statement':'Synthetic claim, not research.',
        'evidence_refs':[{'source_id':'s1','passage_id':'p1','relationship':'supports'}],
        'artifact_refs':['source']}]
    ids={'source':'source_snapshot','code':'model_code','inputs':'model_inputs',
         'outputs':'model_outputs','checks':'model_checks','cmd':'command_receipt',
         'review':'review','report':'report'}
    d['artifacts']=[{'id':i,'path':'synthetic/'+i,'sha256':HASH,'kind':k,'depends_on':[]}
                    for i,k in ids.items()]
    t={'status':'evidenced','finding':'Synthetic coverage only.','claim_ids':['c1'],
       'artifact_refs':['report'],'report_anchor':'synthetic'}
    d['coverage']={x:copy.deepcopy(t) for x in TOPICS}
    d['profit_scalability']={
        'economic_unit':'Synthetic completed workflow',
        'usage_to_revenue_mechanism':'Synthetic paid volume times effective price',
        'variable_and_fixed_costs':'Synthetic variable and fixed cost bridge',
        'value_capture_and_outside_options':'Synthetic supplier and customer alternatives',
        'seat_or_legacy_cannibalization':'Synthetic legacy revenue offset',
        'reinvestment_and_sbc':'Synthetic after-SBC owner cash bridge',
        'measurement_status':'modelled_sensitivity','assessment':'mixed',
        'claim_ids':['c1'],'artifact_refs':['outputs'],'sensitivity_artifact_ids':['outputs'],
        'limitations':['Synthetic fixture; not observed unit economics.']}
    check={'id':'n1','definition':'Synthetic arithmetic','case':'base','period':'synthetic',
        'units':'USD','actual':2,'expected':2,'tolerance':0,'input_artifact_ids':['inputs'],
        'output_artifact_id':'checks','status':'passed'}
    d['model']={'framework':'FCFF_WACC','scope_label':'selected_linked_schedules',
        'code_artifact_ids':['code'],'input_artifact_ids':['inputs'],'output_artifact_ids':['outputs'],
        'command_artifact_ids':['cmd'],'sensitivity_artifact_ids':['outputs'],
        'horizon':'synthetic','distribution_policy':'synthetic distribution',
        'probability_basis':'analyst_judgment','scenarios':[
            {'name':n,'weight':w,'input_artifact_ids':['inputs'],'output_artifact_ids':['outputs']}
             for n,w in [('bear',.3),('base',.5),('bull',.2)]],
        'checks':[check],'limitations':['Synthetic fixture proves no economic conclusion.'],
        'sbc_treatment':'economic_expense','sbc_bridge_artifact_id':'checks',
        'capital_schedule_artifact_ids':['outputs'],'reverse_expectations_artifact_ids':['outputs'],
        'market_case_artifact_id':'report'}
    d['audit']={'author_id':'author','factual_samples':[{'claim_id':'c1','source_id':'s1',
        'passage_id':'p1','reported':2,'verified':2,'units':'USD','period':'synthetic','status':'matched'}],
        'numerical_checks':[check],'command_artifact_ids':['cmd'],'independent_review':{
            'reviewer_id':'reviewer','review_artifact_id':'review','reviewed_artifact_ids':['report','outputs'],
            'source_review':'complete','reasoning_review':'complete'},
        'findings':[],'warnings_reviewed_artifact_id':'review'}
    d['result']={'label':'full_research','recommendation':'conditional_investment_conclusion',
        'publication_status':'draft','report_artifact_id':'report'}
    return d


class ResearchRecordTests(unittest.TestCase):
    def valid(self,d): self.assertEqual([],list(VALIDATOR.iter_errors(d)))
    def invalid(self,d): self.assertTrue(list(VALIDATOR.iter_errors(d)))
    def test_schema_and_blank_progress(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.valid(json.loads((ROOT/'schemas/research-run.template.json').read_text()))
    def test_complete_fixture_and_saved_receipts(self):
        d=fixture();self.valid(d)
        d['result']['publication_status']='saved'
        d['persistence']={'status':'saved','receipts':[{'artifact_id':'report','file_id':'synthetic',
            'version':'0','confirmed_at':STAMP,'sha256':HASH}]}
        d['stages']['persistence']={'status':'complete','evidence_refs':['synthetic-receipt']}
        self.valid(d)
    def test_company_full_equity_options_partial_structure(self):
        d=fixture();d['subject']['security_type']='equity_options';d['instrument_profile']='equity_options'
        d['status']='partial';d['result'].update(label='partial_research',recommendation='none',missing_stages=['sources'],missing_topics=['options_quote_corroboration'])
        d['options_evidence']={'version':'2026-10-24-options-evidence-1','status':'research_only','blockers':['Synthetic quote unavailable']}
        self.valid(d)
        d['status']='complete';self.invalid(d)
    def test_company_full_equity_options_complete_structure_needs_runtime_gate(self):
        # Schema admits the route; options_evidence.validate checks actual artifacts.
        d=fixture();d['subject']['security_type']='equity_options';d['instrument_profile']='equity_options'
        d['options_evidence']={'version':'2026-10-24-options-evidence-1','status':'actionable'}
        self.valid(d)
        del d['instrument_profile'];self.invalid(d)
        d['instrument_profile']='unrelated';self.invalid(d)
        d['instrument_profile']='equity_options';del d['options_evidence'];self.invalid(d)
    def test_equity_options_security_type_requires_company_full_route(self):
        d=fixture();d['subject']['security_type']='equity_options';d['instrument_profile']='equity_options'
        d['options_evidence']={'version':'2026-10-24-options-evidence-1','status':'actionable'}
        d['scope']='narrow';self.invalid(d)
    def test_empty_completion_rejected(self):
        d=json.loads((ROOT/'schemas/research-run.template.json').read_text());d['status']='complete'
        self.invalid(d)
    def test_new_schema_cannot_omit_rationale_or_entry_policy(self):
        d=fixture();d['schema_version']='2026-10-23-research-run-3';self.invalid(d)
    def test_new_schema_pending_rationale_cannot_be_complete(self):
        d=json.loads((ROOT/'schemas/research-run.template.json').read_text());d['status']='complete';self.invalid(d)
    def test_every_required_topic_must_be_present(self):
        for t in TOPICS:
            with self.subTest(topic=t):
                d=fixture();del d['coverage'][t];self.invalid(d)
    def test_checked_box_without_coverage_evidence_rejected(self):
        d=fixture();d['coverage']['business_economics']={'status':'evidenced'};self.invalid(d)
    def test_missing_or_unverified_factual_samples_rejected(self):
        for value in [[],[{'claim_id':'c1','source_id':'s1','passage_id':'p1','reported':2,
                          'verified':None,'units':'USD','period':'synthetic','status':'unverified'}]]:
            d=fixture();d['audit']['factual_samples']=value;self.invalid(d)
    def test_empty_numeric_checks_rejected_for_full_research(self):
        d=fixture();d['audit']['numerical_checks']=[];self.invalid(d)
        d=fixture();d['model']['checks']=[];self.invalid(d)
    def test_unresolved_findings_and_failed_checks_rejected(self):
        d=fixture();d['audit']['findings']=[{'id':'f','description':'Unresolved mismatch',
            'disposition':'unresolved','rationale':'not fixed','evidence_artifact_ids':['review']}]
        self.invalid(d)
        d=fixture();d['model']['checks'][0]['status']='failed';self.invalid(d)
    def test_missing_code_reverse_case_and_sbc_rejected(self):
        for key in ['code_artifact_ids','reverse_expectations_artifact_ids','sbc_bridge_artifact_id']:
            with self.subTest(field=key):
                d=fixture();del d['model'][key];self.invalid(d)
    def test_no_fake_saved_status_without_receipts(self):
        d=fixture();d['result']['publication_status']='saved';self.invalid(d)
    def test_quote_and_date_format_required(self):
        for value in [None,'not-a-date']:
            d=fixture();d['subject']['quote_timestamp']=value;self.invalid(d)
    def test_truthful_date_only_source_retrieval(self):
        d=fixture();source=d['sources'][0];source.update(retrieved_at=None,
            retrieval_date='2026-10-18',retrieval_precision='date_only');self.valid(d)
        for field in ['retrieval_date','retrieval_precision']:
            bad=copy.deepcopy(d);del bad['sources'][0][field];self.invalid(bad)
        bad=copy.deepcopy(d);bad['sources'][0]['retrieval_date']='not-a-date';self.invalid(bad)
        bad=copy.deepcopy(d);bad['sources'][0]['retrieval_precision']='timestamp';self.invalid(bad)
        bad=copy.deepcopy(d);bad['sources'][0]['retrieved_at']=STAMP;self.invalid(bad)
        self.valid(fixture())
    def test_partial_recommendation_rejected(self):
        d=fixture();d['status']='partial';d['result'].update(label='partial_research',
            missing_stages=['model'],missing_topics=[]);self.invalid(d)
        d['result']['recommendation']='none';self.valid(d)
    def test_narrow_definition_uses_text_not_invented_numbers(self):
        d=fixture();d.update(scope='narrow',bounded_request='Define the product only.')
        d['result'].update(label='bounded_answer',recommendation='none')
        d['coverage']={'bounded_question':d['coverage']['business_economics']}
        d['audit']['factual_samples'][0].update(reported='Product definition',verified='Product definition')
        d['audit']['numerical_checks']=[];d.pop('model');d['stages']['model']={'status':'not_applicable'}
        self.valid(d)
    def test_financial_or_holding_company_method_has_scope_notes(self):
        d=fixture();d['model'].update(framework='NAV',scope_label='lookthrough_nav_schedules')
        self.invalid(d);d['model']['scope_notes']='Synthetic holding-company scope';self.valid(d)
    def test_fund_route_requires_payoff_cost_path_and_overlap(self):
        d=fixture();d['scope']='fund_full';self.invalid(d)
        d['subject']['security_type']='fund'
        for t in ['payoff_reset_benchmark','cost_financing_collateral','path_probability_tails','holdings_portfolio_overlap']:
            d['coverage'][t]=copy.deepcopy(d['coverage']['business_economics'])
        d['model'].update(framework='nav_total_return',payoff_source_claim_ids=['c1'],
            calibration_artifact_ids=['inputs'],outcome_artifact_ids=['outputs'])
        self.valid(d)
        del d['coverage']['path_probability_tails'];self.invalid(d)
    def test_profit_scalability_required_without_optimism_veto(self):
        d=fixture();del d['profit_scalability'];self.invalid(d)
        d=fixture();d['profit_scalability'].update(measurement_status='not_publicly_identifiable',
            assessment='not_established',limitations=[]);self.invalid(d)
        d['profit_scalability']['limitations']=['Paid unit price not disclosed; sensitivity only.'];self.valid(d)
        d['profit_scalability']['assessment']='negative';self.valid(d)


if __name__=='__main__': unittest.main(verbosity=2)
