import json
from pathlib import Path
import tempfile
import unittest
from shared.research_sources.artifacts import ROOT, SourceError, save
from tuning.evals.browser_cooperation.grade import baseline_callback, candidate_callback
from tuning.evals.browser_cooperation.experiment import prepare


class BrowserGradeTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.research-sources/web-access-test-tmp';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)
        self.input={'url':'https://arxiv.org/abs/2106.09685','stratum':'paper_abstract'}
        self.expected={'patterns':['Low.Rank Adaptation']}

    def output(self):
        body=save(self.out,b'Low-Rank Adaptation',suffix='txt')
        observation=save(self.out,{'kind':'native_source_observation','status':'observed',
            'observed_url':self.input['url'],'body_ref':body,'truncated':False})
        telemetry=save(self.out,{'case_id':'case','observation_ref':observation,
            'elapsed_seconds':1,'provider_items':1,'approval_events':None,'reauth_events':None,'tokens':None,'cost':None})
        return {'case_id':'case','status':'observed','observation_ref':observation,'telemetry_ref':telemetry}

    def test_native_content_cannot_masquerade_as_ego_arm(self):
        output=self.output()
        self.assertTrue(baseline_callback('case',self.input,self.expected,output)['passed'])
        with self.assertRaisesRegex(SourceError,'BROWSER_WRONG_ARM_READER'):
            candidate_callback('case',self.input,self.expected,output)

    def test_pdf_is_explicit_same_reader_control(self):
        inputs={**self.input,'stratum':'pdf_negative_treatment_control'}
        self.assertTrue(candidate_callback('case',inputs,self.expected,self.output())['passed'])

    def test_unavailable_does_not_become_zero_cost_quality_pass(self):
        result=candidate_callback('case',self.input,self.expected,{'case_id':'case','status':'blocked'})
        self.assertFalse(result['passed']);self.assertIsNone(result['metrics']['cost'])
        self.assertIsNone(result['metrics']['anchor_hits'])

    def test_sealed_preflight_preserves_roster_and_inconclusive_verdict(self):
        result=prepare(self.out/'evaluation')
        self.assertEqual(result['comparison_status'],'blocked')
        self.assertEqual(result['live_paired_cases'],0)
        self.assertEqual(result['quality_verdict'],'inconclusive')
        from shared.research_sources.artifacts import read
        self.assertEqual(len(read(result['contract_ref'])['cases']),4)


if __name__=='__main__':unittest.main()
