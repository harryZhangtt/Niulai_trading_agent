from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import SOURCE_STATE, read, save
from tuning.evals.atomic_actions.workload import specification, _hints, _packets, validate_citations, HERE
from tuning.evals.atomic_actions.grade import mechanical, callback


class AtomicWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.spec = specification()
        self.expected = {row['id']: row['expected'] for row in self.spec['cases']}
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_neutral_schema_and_separate_expected_roster(self):
        schema = json.loads((HERE / 'cases.json').read_text())['terminal_schema']
        def visit(value):
            if isinstance(value, dict):
                self.assertNotIn('const', value); self.assertNotIn('enum', value)
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(schema)
        self.assertEqual(len(self.spec['cases']), 4)
        self.assertTrue(all('expected' not in row['input'] for row in self.spec['cases']))

    def test_public_section_navigation_avoids_toc(self):
        text = 'Abstract\nTOC\nSystem and libraries\n' + 'Intro ' * 60 + '\nAbstract\nMethods\nLimitations, Conclusion\nLimits\nSystem and libraries\nActual setup'
        ref = save(self.out, {'text': save(self.out, text.encode(), suffix='txt')})
        ranges = _hints(ref, {'provider': 'arxiv'})
        self.assertGreater(ranges[-1]['start'], text.find('System and libraries'))
        self.assertTrue(all(row['max_chars'] <= 12000 for row in ranges))

    def test_adjacent_period_unknown_start_is_preserved(self):
        base = {'observations': [{'value': '26000'}, {'value': '26044'}]}
        class Pilot:
            request = {'packet_ref': save(self.out, base), 'requirement_ref': save(self.out, {'explicit': 'synthetic'})}
        with patch('tuning.evals.atomic_actions.workload.prepare', return_value=Pilot()):
            packets, provenance = _packets({}, self.out)
        adjacent = read(packets['adjacent_period_contrast'])
        self.assertIsNone(adjacent['observations'][1]['period']['start'])
        self.assertIn('unknown', provenance['adjacent_period'])

    def test_eps_swapped_labels_and_missing_latest_gap_fail(self):
        def claim(value, basis): return {'value': value, 'basis': basis, 'period': 'FY2025Q1'}
        answer = {'answer': 'Historical before the stock split.', 'claims': [claim('5.98', 'GAAP'), claim('6.12', 'non-GAAP')], 'limitations': [], 'unresolved': []}
        inspected = {'answer': answer}
        self.assertEqual(mechanical('nvda_eps_basis_q1fy25', self.expected['nvda_eps_basis_q1fy25'], inspected), [])
        answer['claims'][0]['basis'] = 'non-GAAP'
        self.assertTrue(mechanical('nvda_eps_basis_q1fy25', self.expected['nvda_eps_basis_q1fy25'], inspected))
        historical = {'answer': '2024 FY2025Q1 reported26044 outlook28.0', 'claims': [claim('26044','reported')], 'limitations': [], 'unresolved': []}
        self.assertIn('LATEST_GAP_NOT_PRESERVED', mechanical('nvda_historical_vs_latest_period', self.expected['nvda_historical_vs_latest_period'], {'answer': historical}))

    def test_source_review_cannot_be_replaced_by_mechanical_pass(self):
        case_id='nvda_eps_basis_q1fy25'; answer_ref=save(self.out, {});source_ref=save(self.out, {'public':True})
        review=save(self.out, {'case_id':case_id,'answer_ref':answer_ref,'source_ref':source_ref,'oracle_sha256':'a'*64,
            'reviewer':'orchestrator_source_grounded','status':'failed','criteria':{row['id']:False for row in self.expected[case_id]['critical_criteria']}})
        observation={'case':{'case_id':case_id,'answer_ref':answer_ref,'source_ref':source_ref,'elapsed_seconds':1,'status':'completed'},'not_before':'2026-10-31T00:00:00Z','review_ref':review,'oracle_sha256':'a'*64}
        case_input=next(row['input'] for row in self.spec['cases'] if row['id']==case_id)
        inspected={'answer':{},'inputs':{'question':case_input['input_question'],'source_identity':case_input['public_sources'][0]},'counts':{'actions':2,'model_turns':2,'read_calls':1},'tokens':None}
        with patch('tuning.evals.atomic_actions.grade.inspect_case',return_value=inspected),patch('tuning.evals.atomic_actions.grade.mechanical',return_value=[]):
            result=callback()(case_id,case_input,self.expected[case_id],observation)
        self.assertFalse(result['passed']);self.assertIsNone(result['metrics']['cost'])


    def test_equivalent_period_notation_and_precision_do_not_false_fail(self):
        for period in ('Q1 FY25', 'FY25 Q1', 'first quarter fiscal 2025', 'FY2025Q1'):
            answer={'answer':'Historical EPS before split.','limitations':[],'unresolved':[],
                'claims':[{'value':'$5.980','basis':'GAAP','period':period},
                          {'value':'6.120','basis':'adjusted','period':period}]}
            self.assertEqual(mechanical('nvda_eps_basis_q1fy25',self.expected['nvda_eps_basis_q1fy25'],{'answer':answer}),[],period)
        answer['claims'][0]['period']='FY2024Q1'
        self.assertTrue(mechanical('nvda_eps_basis_q1fy25',self.expected['nvda_eps_basis_q1fy25'],{'answer':answer}))

    def test_blocked_case_remains_a_failed_full_roster_submission(self):
        case_id='flashattention3_h100_scope'
        result=callback()(case_id,{'id':case_id},self.expected[case_id],
            {'case':{'case_id':case_id,'status':'blocked','reason':'SOURCE_NETWORK_FAILED','elapsed_seconds':1}})
        self.assertFalse(result['passed']);self.assertIn('SOURCE_NETWORK_FAILED',result['reasons'])
        self.assertIsNone(result['metrics']['action_calls'])

    def test_acceptance_adapter_import_and_source_closure(self):
        from tuning.evals.atomic_actions import acceptance
        files=acceptance.fingerprint()['files']
        self.assertIn('tuning/evals/atomic_actions/grade.py',files)
        self.assertIn('tuning/evals/atomic_actions/oracle.json',files)
        self.assertIn('shared/actions/runtime.py',files)

    def test_blocked_suite_finishes_once_with_complete_roster(self):
        from tuning.evals.atomic_actions import acceptance
        cases=[{'case_id':row['id'],'status':'blocked','reason':'SOURCE_NETWORK_FAILED','elapsed_seconds':1} for row in self.spec['cases']]
        contract={'cases':[{'id':row['id'],'input_ref':save(self.out,row['input'])}for row in self.spec['cases']], 'budget':self.spec['budget']}
        record={'candidate':acceptance.fingerprint(),'contract_ref':save(self.out,{}),'ledger_directory':str(self.out),
            'output_directory':str(self.out),'execution':{'result_ref':save(self.out,{'cases':cases,'elapsed_seconds':4}),
                'context':{'scheduled_at':'2026-10-31T00:00:00Z','attempt_id':'test'}}}
        path=self.out/'record.json';path.write_text(json.dumps(record))
        failed=save(self.out,{'status':'failed'})
        with patch('tuning.evals.atomic_actions.acceptance.contracts.validate',return_value=contract), \
             patch('tuning.evals.atomic_actions.acceptance.contracts.finish',return_value=failed) as finish, \
             patch('tuning.evals.atomic_actions.grade.inspect_case',side_effect=AssertionError('blocked evidence must not be treated as complete')):
            result=acceptance.finalize(path,{})
        self.assertEqual(result['status'],'failed');self.assertEqual(finish.call_count,1)
        self.assertEqual(len(finish.call_args.kwargs['submissions']),4)
        self.assertEqual(finish.call_args.kwargs['usage']['max_case_actions'],6)


    def test_grouped_labelled_values_and_verbose_periods_are_semantic_equivalents(self):
        for value in ('GAAP: $5.98; non-GAAP: $6.12', '$5.980 (GAAP); $6.120 (non-GAAP)', 'GAAP diluted EPS was $5.98; adjusted EPS was $6.12'):
            answer={'answer':'Different accounting measurements before the split.','limitations':[],'unresolved':[],
                'claims':[{'value':value,'basis':'As reported; historical pre-split share basis.','period':'Q1 FY2025, quarter ended April 28, 2024'}]}
            self.assertEqual(mechanical('nvda_eps_basis_q1fy25',self.expected['nvda_eps_basis_q1fy25'],{'answer':answer}),[],value)
        for value in ('GAAP: $6.12; non-GAAP: $5.98', '$6.12 (GAAP); $5.98 (non-GAAP)'):
            answer['claims'][0]['value']=value
            self.assertTrue(mechanical('nvda_eps_basis_q1fy25',self.expected['nvda_eps_basis_q1fy25'],{'answer':answer}),value)
        answer['claims'][0]['value']='GAAP: $5.98; non-GAAP: $6.12'
        answer['claims'][0]['period']='Q1 FY2024, quarter ended April 30, 2023'
        self.assertTrue(mechanical('nvda_eps_basis_q1fy25',self.expected['nvda_eps_basis_q1fy25'],{'answer':answer}))


    def test_citations_use_issued_locator_not_model_invented_offsets(self):
        source={'path':'source','sha256':'a'*64}
        passages=[{'locator':'normalized-text:0:6500','start':0,'end':6500}]
        claim={'source_ref':source,'passage_locator':'normalized-text:0:6500'}
        self.assertEqual(validate_citations([claim],source,passages),{'normalized-text:0:6500':{'start':0,'end':6500}})
        from shared.research_sources.artifacts import SourceError
        claim['passage_locator']='normalized-text:5000:6500'
        with self.assertRaisesRegex(SourceError,'ATOMIC_CITATION_NOT_ISSUED'):validate_citations([claim],source,passages)
        claim['passage_locator']='normalized-text:0:6500';claim['source_ref']={'path':'foreign','sha256':'b'*64}
        with self.assertRaisesRegex(SourceError,'ATOMIC_CITATION_IDENTITY'):validate_citations([claim],source,passages)



if __name__=='__main__':unittest.main()
