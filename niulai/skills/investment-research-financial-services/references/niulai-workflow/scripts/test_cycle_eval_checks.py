import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
import cycle_eval_checks as c
import cycle_vintage_checks as v


def example_packet():
    def fold(cid,month,member,actual,category='success'):
        # Independent members avoid pretending overlapping horizons are independent.
        origin=f'2024-{month:02}-28T20:00:00Z'
        expected=[{'series_id':'sales','unit':'USD_millions','period':{'start':f'2024-{m:02}-01','end':f'2024-{m:02}-20'}} for m in range(1,month+1)]
        observations=[{**x,'value':str(i+10),'available_at':f'2024-{i+1:02}-25T10:00:00Z','vintage_id':'first','source_ref':'synthetic test only'} for i,x in enumerate(expected)]
        training={'version':v.VERSION,'subject':member,'as_of':origin,'expected':expected,'observations':observations}
        e={'id':cid,'member_id':member,'origin':origin,'target_period':{'start':f'2024-{month+1:02}-01','end':f'2024-{month+1:02}-20'}}
        f={'id':cid,'training':training,'candidate':{'method_id':'hypothesis1','prediction':str(month+10),'issued_at':origin,'fit_cutoff':origin,'training_view_sha256':v.calculate(training)['selected_view_sha256']},'abstention_reason':None,'resolve_after':f'2024-{month+1:02}-21T00:00:00Z','outcome':{'value':str(actual),'available_at':f'2024-{month+1:02}-25T10:00:00Z','source_ref':'synthetic outcome','category':category},'candidate_cost_usd':'0.05','baseline_cost_usd':'0.01'}
        return e,f
    ef=[fold('a',2,'successful',12),fold('b',3,'niche',13,'niche'),fold('c',4,'failed',2,'failure')]
    return {'version':c.VERSION,'cohort_id':'synthetic_all_attempts','declared_at':'2024-01-01T00:00:00Z','as_of':'2024-08-01T00:00:00Z','series_id':'sales','unit':'USD_millions','functional':'mean','minimum_training_periods':2,'minimum_paired_cases':3,'methods':[{'id':'hypothesis1','specification_sha256':'a'*64,'declared_at':'2023-12-01T00:00:00Z'}],'expected_cases':[x[0] for x in ef],'cases':[x[1] for x in ef]}


class EvaluationTests(unittest.TestCase):
    def test_exact_small_regression_and_failures_retained(self):
        r=c.calculate(example_packet());self.assertEqual(r['status'],'descriptive_only')
        self.assertEqual(r['coverage']['expected'],3);self.assertEqual(r['coverage']['outcome_categories']['failure'],1)
        self.assertEqual(r['comparison']['candidate_mean_loss'],48)
        self.assertEqual(r['comparison']['naive_mean_loss'],41)
        self.assertFalse(r['comparison']['candidate_better_on_paired_sample']);self.assertFalse(r['automatic_promotion'])
    def test_median_uses_existing_absolute_loss(self):
        p=example_packet();p['functional']='median';r=c.calculate(p)
        self.assertEqual(r['comparison']['candidate_mean_loss'],4);self.assertAlmostEqual(r['comparison']['naive_mean_loss'],13/3)
    def test_abstain_kept_in_denominator(self):
        p=example_packet();p['cases'][2].update(candidate=None,abstention_reason='Cannot identify regime')
        r=c.calculate(p);self.assertEqual(r['coverage']['abstained'],1);self.assertEqual(r['coverage']['expected'],3)
        self.assertEqual(r['status'],'insufficient_history');self.assertTrue(r['comparison']['candidate_better_on_paired_sample'])
        self.assertFalse(r['predictive_skill_certified'])
    def test_missing_failure_not_dropped(self):
        p=example_packet();p['cases'][2]['outcome']=None;r=c.calculate(p)
        self.assertEqual(r['coverage']['missing_outcome'],1);self.assertEqual(r['coverage']['outcome_categories']['unknown'],1)
    def test_pending(self):
        p=example_packet();p['as_of']='2024-05-01T00:00:00Z';p['cases'][2]['outcome']=None
        self.assertEqual(c.calculate(p)['coverage']['pending'],1)
    def test_insufficient_training(self):
        p=example_packet();p['minimum_training_periods']=4;r=c.calculate(p)
        self.assertEqual(r['coverage']['insufficient_training'],2)
    def test_costs_separate(self):
        r=c.calculate(example_packet());self.assertEqual(r['comparison']['costs_usd_all_cases']['candidate_cost_usd'],'0.15')
        self.assertTrue(r['comparison']['costs_are_computation_not_trading_returns'])
    def test_future_tail_does_not_change_frozen_decision(self):
        p=example_packet();before=c.calculate(p)
        row=copy.deepcopy(p['cases'][0]['training']['observations'][0]);row.update(value='9999',available_at='2024-07-01T00:00:00Z',vintage_id='future_revision')
        p['cases'][0]['training']['observations'].append(row)
        after=c.calculate(p);self.assertEqual(before['items'],after['items']);self.assertNotEqual(before['input_sha256'],after['input_sha256'])
    def test_fit_leaks(self):
        p=example_packet();p['cases'][0]['candidate']['fit_cutoff']='2024-07-01T00:00:00Z'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_fit_before_last_release(self):
        p=example_packet();p['cases'][0]['candidate']['fit_cutoff']='2024-02-21T00:00:00Z'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_stale_view(self):
        p=example_packet();p['cases'][0]['candidate']['training_view_sha256']='b'*64
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_drop_case(self):
        p=example_packet();p['cases'].pop()
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_late_declaration(self):
        p=example_packet();p['declared_at']='2024-06-01T00:00:00Z'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_missing_abstention_reason(self):
        p=example_packet();p['cases'][0]['candidate']=None
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_wrong_training_member(self):
        p=example_packet();p['cases'][0]['training']['subject']='other'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_wrong_unit(self):
        p=example_packet();p['unit']='shares'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_premature_outcome(self):
        p=example_packet();p['cases'][0]['outcome']['available_at']='2024-02-27T00:00:00Z'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_future_outcome(self):
        p=example_packet();p['cases'][0]['outcome']['available_at']='2025-02-27T00:00:00Z'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_overlap_same_member(self):
        p=example_packet();p['expected_cases'][1]['member_id']='successful';p['cases'][0]['resolve_after']='2024-04-01T00:00:00Z';p['cases'][0]['outcome']=None
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_no_mixed_candidate_variants(self):
        p=example_packet();p['methods'].append({'id':'h2','specification_sha256':'b'*64,'declared_at':'2023-12-01T00:00:00Z'});p['cases'][2]['candidate']['method_id']='h2'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_invalid_json_and_nonfinite(self):
        with self.assertRaises(ValueError):c.decode_packet(b'{"a":1,"a":2}')
        for value in ('NaN','Infinity',True,1):
            p=example_packet();p['cases'][0]['candidate']['prediction']=value
            with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_negative_cost(self):
        p=example_packet();p['cases'][0]['candidate_cost_usd']='-0.1'
        with self.assertRaises(c.EvaluationError):c.calculate(p)
    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'i.json';out=Path(d)/'o.json';src.write_text(json.dumps(example_packet()))
            p=subprocess.run([sys.executable,str(Path(c.__file__)),'--input',str(src),'--output',str(out)],capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(out.read_text())['coverage']['expected'],3)

if __name__=='__main__':unittest.main()
