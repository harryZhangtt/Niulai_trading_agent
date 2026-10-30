import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from research_eval_promotion import evaluate, decode, hashjson


def fixture(root):
    def artifact(aid,content):
        p=root/(aid+'.json');p.write_text(json.dumps(content));return {'id':aid,'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    artifacts=[artifact('baseline',{'parser':'loose'}),artifact('candidate',{'parser':'strict'}),artifact('source',{'scope':'synthetic functional fixtures only'})]
    bs,cs,ss=[a['sha256']for a in artifacts]
    m={'version':1,'domain':'functional','protocol_id':'synthetic_eval','frozen_at':'2026-10-01T00:00:00Z',
       'candidate_selected_at':'2026-10-04T00:00:00Z','independent_owner':'critic','metric_definition':'Expected verifier outcome, full case coverage, no critical failures',
       'holdout_exposures':1,'max_trials':1,'baseline_artifact_id':'baseline','candidate_artifact_id':'candidate','artifacts':artifacts,'cases':[]}
    rows=[]
    for j,split in enumerate(['train','dev','holdout']):
        cid=split+'1';origin=f'2026-10-{j+1:02d}T01:00:00Z'
        m['cases'].append({'id':cid,'split':split,'origin':origin,'target_end':origin,'source_available_at':'2026-09-01T00:00:00Z','source_artifact_id':'source','expected_verifier':'unit-test'})
        for role,h in [('baseline',bs),('candidate',cs)]:
            aid=cid+'_'+role
            artifacts.append(artifact(aid,{'case_id':cid,'variant_sha256':h,'source_sha256':ss,'verifier_id':'unit-test','method':'deterministic','trial_id':'frozen-comparison','evaluated_at':'2026-10-05T00:00:00Z','passed':role=='candidate','complete':True,'critical_errors':[],'cost_usd':0,'elapsed_seconds':1}))
            rows.append({'trial_id':'frozen-comparison','case_id':cid,'role':role,'evaluated_at':'2026-10-05T00:00:00Z','variant_sha256':h,'source_sha256':ss,'verifier_artifact_id':aid,'cost_usd':0,'elapsed_seconds':1})
    return m,rows


class TestPromotion(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.m,self.rows=fixture(self.root)
    def tearDown(self):self.t.cleanup()
    def runeval(self):return evaluate(self.m,self.rows,base_dir=self.root,expected_manifest_sha256=hashjson(self.m))
    def editverifier(self,aid,key,value):
        a=next(x for x in self.m['artifacts']if x['id']==aid);p=self.root/a['path'];d=json.loads(p.read_text());d[key]=value;p.write_text(json.dumps(d));a['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    def test_paired_gain_not_auto_promotion(self):
        r=self.runeval();self.assertEqual(r['candidate_status'],'eligible_for_independent_offline_review');self.assertFalse(r['auto_promoted']);self.assertEqual(r['summary']['holdout']['candidate']['passed'],1)
    def test_critical_failure_veto_despite_pass(self):
        self.editverifier('holdout1_candidate','critical_errors',['wrong strike']);r=self.runeval();self.assertEqual(r['candidate_status'],'reject');self.assertIn('holdout:critical_error_veto',r['reasons'])
    def test_incomplete_veto(self):
        self.editverifier('train1_candidate','complete',False);self.assertEqual(self.runeval()['candidate_status'],'reject')
    def test_missing_case(self):
        self.rows.pop()
        with self.assertRaises(ValueError):self.runeval()
    def test_duplicate_case_metric(self):
        self.rows.append(self.rows[-1])
        with self.assertRaises(ValueError):self.runeval()
    def test_tamper_verifier(self):
        (self.root/'holdout1_candidate.json').write_text('{}')
        with self.assertRaises(ValueError):self.runeval()
    def test_wrong_source(self):
        self.rows[0]['source_sha256']='0'*64
        with self.assertRaises(ValueError):self.runeval()
    def test_lookahead_source(self):
        self.m['cases'][0]['source_available_at']='2026-10-10T00:00:00Z'
        with self.assertRaises(ValueError):self.runeval()
    def test_overlapping_splits(self):
        self.m['cases'][0]['target_end']='2026-10-02T01:00:00Z'
        with self.assertRaises(ValueError):self.runeval()
    def test_holdout_exposed_twice(self):
        self.m['holdout_exposures']=2
        with self.assertRaises(ValueError):self.runeval()
    def test_postholdout_selection(self):
        self.m['candidate_selected_at']='2026-10-06T00:00:00Z'
        with self.assertRaises(ValueError):self.runeval()
    def test_trial_budget(self):
        self.rows[-1]['trial_id']='second'
        with self.assertRaises(ValueError):self.runeval()
    def test_llm_judge_alone(self):
        self.editverifier('holdout1_candidate','method','candidate_llm_judge')
        with self.assertRaises(ValueError):self.runeval()
    def test_paired_regression_veto(self):
        self.editverifier('dev1_baseline','passed',True);self.editverifier('dev1_candidate','passed',False);self.assertEqual(self.runeval()['candidate_status'],'reject')
    def test_no_gain_reject(self):
        self.editverifier('holdout1_baseline','passed',True);self.assertEqual(self.runeval()['candidate_status'],'reject')
    def test_equal_quality_less_cost(self):
        self.editverifier('holdout1_baseline','passed',True);self.rows[-2]['cost_usd']=1;self.editverifier('holdout1_baseline','cost_usd',1);self.assertEqual(self.runeval()['candidate_status'],'eligible_for_independent_offline_review')
    def test_cost_tamper_rejected(self):
        self.rows[-2]['cost_usd']=1
        with self.assertRaises(ValueError):self.runeval()
    def test_external_frozen_hash_mismatch(self):
        h=hashjson(self.m);self.m['metric_definition']='edited after inspecting results'
        with self.assertRaises(ValueError):evaluate(self.m,self.rows,base_dir=self.root,expected_manifest_sha256=h)
    def test_metric_underflow(self):
        self.rows[0]['cost_usd']='1e-999'
        with self.assertRaises(ValueError):self.runeval()
    def test_trial_row_tamper(self):
        for row in self.rows:row['trial_id']='forged-one-trial'
        with self.assertRaises(ValueError):self.runeval()
    def test_timestamp_row_tamper(self):
        self.rows[-1]['evaluated_at']='2026-10-05T01:00:00Z'
        with self.assertRaises(ValueError):self.runeval()
    def test_nan(self):
        self.rows[0]['cost_usd']='NaN'
        with self.assertRaises(ValueError):self.runeval()
    def test_duplicate_json(self):
        with self.assertRaises(ValueError):decode('{"a":1,"a":2}')

if __name__=='__main__':unittest.main()
