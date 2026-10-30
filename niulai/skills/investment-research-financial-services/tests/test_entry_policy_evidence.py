import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'references/niulai-workflow/scripts/entry_policy_evidence.py'
spec=importlib.util.spec_from_file_location('entry_policy_evidence',P);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

class EntryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.rec={'scope':'company_full','status':'complete','subject':{'ticker':'AAA'},'policy_versions':{'entry_policy':M.VERSION},'artifacts':[],'audit':{'author_id':'author'}}
        self.add('baseline',{'cashflows':[1,2,3]});self.add('source',{'actual_evidence':'test fixture'})
        self.decision={'change':'unchanged','selected_policy':'wait','rationale':'Wait 120 vs now 110 under explicit judgment weights; lower loss.'}
        inp={'ticker':'AAA','basis':'company_bound','probability_basis':'judgment','common_horizon_years':5,'initial_budget':100,'baseline_artifact_hashes':{i:self.art(i)['sha256'] for i in ['baseline','source']}}
        self.add('input',inp)
        out={k:inp[k] for k in ['ticker','basis','probability_basis','common_horizon_years','initial_budget']};out.update(input_sha256=self.art('input')['sha256'],policies={k:{'expected_terminal_wealth':w,'loss_probability':.2,'nonfill_probability':.1} for k,w in [('now',110),('staged',115),('wait',120)]},decision=self.decision,sensitivity=[{'cash_rate':.03,'selected_policy':'wait'}]);self.add('output',out)
        review={'ticker':'AAA','reviewer_id':'reviewer','status':'approved_company_entry','artifact_hashes':{i:self.art(i)['sha256'] for i in ['baseline','source','input','output']},'numerical_check_count':3};self.add('review',review)
        self.rec['entry_policy_evidence']={'version':M.VERSION,'status':'compared','basis':'company_bound','probability_basis':'judgment','common_horizon_years':5,'initial_budget':100,'information_cutoff':'2026-10-23','limitations':'Judgmental not calibrated','baseline_artifact_ids':['baseline'],'source_evidence_artifact_ids':['source'],'input_artifact_id':'input','output_artifact_id':'output','review_artifact_id':'review','decision':self.decision}
    def tearDown(self):self.tmp.cleanup()
    def art(self,i):return next(a for a in self.rec['artifacts'] if a['id']==i)
    def add(self,i,d):
        p=self.root/(i+'.json');p.write_text(json.dumps(d));a={'id':i,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        if any(x['id']==i for x in self.rec['artifacts']):self.art(i).update(a)
        else:self.rec['artifacts'].append(a)
    def test_company_bound_unchanged_accepts(self):self.assertEqual(M.validate(self.rec)['status'],'company_entry_evidence_verified')
    def test_crypto_binding_accepts_and_company_binding_rejected(self):
        self.rec['scope']='crypto_full'
        with self.assertRaises(ValueError):M.validate(self.rec)
        self.rec['entry_policy_evidence']['basis']='crypto_bound'
        inp=json.loads(Path(self.art('input')['path']).read_text());inp['basis']='crypto_bound';self.add('input',inp)
        out=json.loads(Path(self.art('output')['path']).read_text());out.update(basis='crypto_bound',input_sha256=self.art('input')['sha256']);self.add('output',out)
        rev=json.loads(Path(self.art('review')['path']).read_text());rev.update(status='approved_crypto_entry',artifact_hashes={i:self.art(i)['sha256'] for i in ['baseline','source','input','output']});self.add('review',rev)
        self.assertEqual(M.validate(self.rec)['status'],'crypto_entry_evidence_verified')
    def test_legacy_unchanged(self):self.rec['policy_versions'].pop('entry_policy');self.rec.pop('entry_policy_evidence');self.assertEqual(M.validate(self.rec)['status'],'not_applicable_or_legacy')
    def test_price_only_not_forced(self):self.rec['scope']='narrow';self.rec.pop('entry_policy_evidence');self.assertEqual(M.validate(self.rec)['status'],'not_applicable_or_legacy')
    def test_missing_company_baseline_rejected(self):
        self.rec['entry_policy_evidence']['baseline_artifact_ids']=[]
        with self.assertRaisesRegex(ValueError,'baseline'):M.validate(self.rec)
    def test_synthetic_only_rejected(self):
        self.rec['entry_policy_evidence']['basis']='synthetic'
        with self.assertRaisesRegex(ValueError,'company-bound'):M.validate(self.rec)
    def test_stale_hash_rejected(self):
        Path(self.art('baseline')['path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale hash'):M.validate(self.rec)
    def test_unchanged_without_numbers_rejected(self):
        out=json.loads(Path(self.art('output')['path']).read_text());out['policies']['wait'].pop('expected_terminal_wealth');self.add('output',out)
        with self.assertRaisesRegex(ValueError,'finite numeric'):M.validate(self.rec)
    def test_missing_block_rejected(self):
        self.rec.pop('entry_policy_evidence')
        with self.assertRaisesRegex(ValueError,'missing'):M.validate(self.rec)
    def test_limited_only_as_incomplete(self):
        self.rec['entry_policy_evidence']['status']='limited'
        with self.assertRaisesRegex(ValueError,'limited'):M.validate(self.rec)
        self.rec['status']='partial';self.assertEqual(M.validate(self.rec)['status'],'incomplete_not_certified')
    def test_stale_review_rejected(self):
        r=json.loads(Path(self.art('review')['path']).read_text());r['artifact_hashes']['output']='0'*64;self.add('review',r)
        with self.assertRaisesRegex(ValueError,'review stale'):M.validate(self.rec)
    def test_false_calibration_rejected(self):
        self.rec['entry_policy_evidence']['probability_basis']='calibrated'
        with self.assertRaisesRegex(ValueError,'calibration artifacts'):M.validate(self.rec)
    def test_schema_requires_block_only_for_opted_in_record(self):
        full=json.loads((ROOT/'schemas/research-run.schema.json').read_text()); sub={'type':'object','allOf':[rule for rule in full['allOf'] if 'entry_policy' in rule.get('if',{}).get('properties',{}).get('policy_versions',{}).get('required',[])]}
        r={'scope':'company_full','status':'complete','policy_versions':{'entry_policy':M.VERSION}}
        self.assertTrue(list(Draft202012Validator(sub).iter_errors(r)));r['policy_versions']={};self.assertFalse(list(Draft202012Validator(sub).iter_errors(r)))

if __name__=='__main__':unittest.main()
