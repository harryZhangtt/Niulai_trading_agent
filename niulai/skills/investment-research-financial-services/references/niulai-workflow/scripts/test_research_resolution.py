import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from research_resolution import calculate, decode


def example_packet(root):
    (root/'evidence.txt').write_text('Synthetic test source; not investment evidence.')
    h=hashlib.sha256((root/'evidence.txt').read_bytes()).hexdigest()
    return {'version':1,'as_of':'2026-10-24T00:00:00Z','author_id':'author','subject':'SYNTHETIC','proposed_action':'wait','remaining_minutes':10,
      'expected_question_ids':['paid_capacity'],
      'artifacts':[{'id':'src','path':'evidence.txt','sha256':h,'available_at':'2026-10-23T00:00:00Z'}],
      'questions':[{'id':'paid_capacity','question':'Is new capacity paid?','owner':'researcher',
        'decision_link':'Paid versus unused capacity switches entry preference.','reopening_condition':'New quarterly paid-utilization disclosure',
        'baseline_artifact_ids':['src'],'hypotheses':[
          {'id':'scarcity','mechanism':'Paid capacity earns return above capital cost.','falsifier':'Unused qualified capacity','source_artifact_ids':['src']},
          {'id':'commoditization','mechanism':'Supply and substitution erase rents.','falsifier':'Renewals sustain net pricing','source_artifact_ids':['src']}],
        'decision_matrix':{'states':['scarce','surplus'],'actions':{'buy':[40,-30],'wait':[0,0]},
          'utility_unit':'USD','horizon':'2027-04-16','budget_basis':'same hypothetical1100USD',
          'probabilities':[0.5,0.5],'probability_basis':'explicit_test_assumption','probability_source_ref':'synthetic',
          'source_artifact_ids':['src']},
        'required_for_actions':['buy','add'],'status':'open','attempt_budget':2,'attempts':[],
        'next_experiment':{'minutes':5,'target_source':'issuer primary release','discriminating_observation':'Paid utilization and effective net price',
          'expected_action_change':'Low paid use favors wait','stop_condition':'Find sourced utilization or sensitivity proves wait dominates'}}]}


class TestResolution(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=example_packet(self.root)
    def tearDown(self):self.tmp.cleanup()
    def runpacket(self):return calculate(self.p,base_dir=self.root)
    def question(self):return self.p['questions'][0]
    def attempt(self,outcome='evidence_obtained'):
        self.question()['attempts']=[{'at':'2026-10-23T23:00:00Z','method':'read primary','target':'issuer results','outcome':outcome,'finding':'Saved result supports bounded model.','result_artifact_ids':['src']}]
    def review(self):self.question()['review']={'reviewer_id':'critic','finding':'Inspected source and utility bounds.','artifact_ids':['src']}
    def test_evpi_exact(self):
        m=self.runpacket()['questions'][0]['decision_metrics']
        self.assertEqual(m['expected_utility'],{'buy':5,'wait':0});self.assertEqual(m['expected_value_perfect_information_upper_bound'],15)
        self.assertEqual(m['minimax_regret'],30);self.assertFalse(m['robust_actions'])
    def test_no_probabilities_no_fake_evsi(self):
        del self.question()['decision_matrix']['probabilities'];m=self.runpacket()['questions'][0]['decision_metrics'];self.assertIsNone(m['expected_utility']);self.assertIsNone(m['expected_value_perfect_information_upper_bound'])
    def test_robust_wait(self):
        q=self.question();q['decision_matrix']['actions']['buy']=[-10,-30];q.update(status='assumption_bound',assumption_limits='Declared two-state sensitivity only');self.attempt('negative_result');self.review()
        self.assertEqual(self.runpacket()['questions'][0]['decision_metrics']['robust_actions'],['wait'])
    def test_robust_not_probability_weighted_only(self):
        self.attempt();self.review();self.question().update(status='assumption_bound',assumption_limits='test')
        with self.assertRaises(ValueError):self.runpacket()
    def test_resolved_needs_artifact_and_obtained(self):
        self.review();self.question().update(status='resolved',resolution_artifact_ids=['src']);self.attempt('negative_result')
        with self.assertRaises(ValueError):self.runpacket()
        self.attempt();self.assertEqual(self.runpacket()['questions'][0]['status'],'resolved')
    def test_blocked_needs_attempt_or_hard_evidence(self):
        q=self.question();q.update(status='external_blocker',blocker='Missing entitlement',recovery_action='Secure provider connection');self.review()
        with self.assertRaises(ValueError):self.runpacket()
        q['hard_access_blocker_artifact_ids']=['src'];self.assertEqual(self.runpacket()['unresolved_ids'],['paid_capacity'])
    def test_identical_attempt_rejected(self):
        self.attempt('transient_error');self.question()['attempts']*=2
        with self.assertRaises(ValueError):self.runpacket()
    def test_changed_attempt_allowed(self):
        self.attempt('negative_result');a=copy.deepcopy(self.question()['attempts'][0]);a['target']='second primary release';self.question()['attempts'].append(a);self.runpacket()
    def test_budget_exhaustion_not_completion(self):
        self.p['remaining_minutes']=0;r=self.runpacket();self.assertFalse(r['questions'][0]['can_fit_time_budget']);self.assertEqual(r['unresolved_ids'],['paid_capacity'])
    def test_attempt_limit(self):
        self.attempt();self.question()['attempt_budget']=0
        with self.assertRaises(ValueError):self.runpacket()
    def test_reviewer_independence(self):
        self.attempt();self.review();self.question().update(status='resolved',resolution_artifact_ids=['src']);self.question()['review']['reviewer_id']='/other/author'
        with self.assertRaises(ValueError):self.runpacket()
    def test_stale_hash(self):
        (self.root/'evidence.txt').write_text('changed')
        with self.assertRaises(ValueError):self.runpacket()
    def test_future_artifact(self):
        self.p['artifacts'][0]['available_at']='2026-10-25T00:00:00Z'
        with self.assertRaises(ValueError):self.runpacket()
    def test_future_attempt(self):
        self.attempt();self.question()['attempts'][0]['at']='2026-10-25T00:00:00Z'
        with self.assertRaises(ValueError):self.runpacket()
    def test_missing_scope(self):
        self.p['expected_question_ids'].append('financing')
        with self.assertRaises(ValueError):self.runpacket()
    def test_hypothesis_requires_rival(self):
        self.question()['hypotheses'].pop()
        with self.assertRaises(ValueError):self.runpacket()
    def test_probability_invalid(self):
        self.question()['decision_matrix']['probabilities']=[0.6,0.6]
        with self.assertRaises(ValueError):self.runpacket()
    def test_nan_bool_invalid(self):
        for v in ['NaN',True,'1e999','1e-999']:
            self.question()['decision_matrix']['actions']['buy'][0]=v
            with self.assertRaises(ValueError):self.runpacket()
    def test_near_one_probability_not_silently_accepted(self):
        self.question()['decision_matrix']['probabilities']=['0.5','0.500000000000000000000000000000000000001']
        with self.assertRaises(ValueError):self.runpacket()
    def test_derived_underflow_rejected(self):
        q=self.question();q['decision_matrix']['actions']['buy']=['1e-300','-1e-300'];q['next_experiment']['minutes']='1e300'
        with self.assertRaises(ValueError):self.runpacket()
    def test_derived_overflow_rejected(self):
        self.question()['decision_matrix']['actions']['buy']=['1e308','-1e308']
        self.question()['decision_matrix']['actions']['wait']=['-1e308','1e308']
        with self.assertRaises(ValueError):self.runpacket()
    def test_robust_wait_cannot_certify_buy(self):
        self.p['proposed_action']='buy';q=self.question();q['decision_matrix']['actions']['buy']=[-10,-30]
        q.update(status='assumption_bound',assumption_limits='Bounded test');self.attempt('negative_result');self.review()
        with self.assertRaises(ValueError):self.runpacket()
    def test_missing_proposed_action_rejected(self):
        self.p['proposed_action']='hold'
        with self.assertRaises(ValueError):self.runpacket()
    def test_missing_artifact(self):
        self.question()['baseline_artifact_ids']=['missing']
        with self.assertRaises(ValueError):self.runpacket()
    def test_duplicate_json(self):
        with self.assertRaises(ValueError):decode('{"a":1,"a":2}')
    def test_mixed_units_groups_not_pooled(self):
        q=copy.deepcopy(self.question());q['id']='other';q['decision_matrix']['utility_unit']='EUR';self.p['questions'].append(q);self.p['expected_question_ids'].append('other');self.assertEqual(len(self.runpacket()['questions']),2)
    def test_wait_requires_robust(self):
        self.question().update(status='research_wait',wait_reason='No decision value');self.attempt('negative_result');self.review()
        with self.assertRaises(ValueError):self.runpacket()

if __name__=='__main__':unittest.main()
