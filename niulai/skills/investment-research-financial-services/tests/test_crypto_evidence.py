"""Synthetic admission tests, never investment evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'references/niulai-workflow/scripts'))
import crypto_evidence as gate

class CryptoGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.a={'version':gate.VERSION,'ticker':'SYNTHETIC','stablecoin_or_l2_exposure':True,
            'topics':{k:{'status':'evidenced','finding':'Synthetic evidence','source_ids':['s'],
                        'artifact_refs':['source']} for k in gate.TOPICS},
            'accounting':{k:'Synthetic explicit treatment' for k in ['fee_beneficiaries','issuance_treatment','burn_treatment','monetary_premium_overlap']},
            'comparators':[{'id':i,'kind':k,'job':'Synthetic job','capture':'Synthetic capture',
                'tradeoff':'Synthetic tradeoff','source_ids':['s']} for i,k in [('TOKEN','crypto'),('BANK','noncrypto'),('COIN','equity'),('CRCL','equity')]],
            'supply_reconciliation':{'status':'reconciled','opening':100,'issuance':3,'burn':2,
                'other_net_change':0,'closing':101,'tolerance':1e-9,'tolerance_basis':'Synthetic floating precision','unit':'tokens','period':'synthetic','source_ids':['s']}}
    def tearDown(self):self.tmp.cleanup()
    def record(self):
        arts=[]
        for name,doc in [('source',{'synthetic':True}),('assessment',self.a)]:
            p=self.root/(name+'.json');p.write_text(json.dumps(doc));arts.append({'id':name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        review={'ticker':'SYNTHETIC','reviewer_id':'independent','status':'approved_crypto_evidence',
            'source_review':'complete','accounting_review':'complete','substitution_review':'complete',
            'artifact_hashes':{a['id']:a['sha256'] for a in arts}}
        p=self.root/'review.json';p.write_text(json.dumps(review));arts.append({'id':'review','path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        return {'scope':'crypto_full','status':'complete','subject':{'ticker':'SYNTHETIC','security_type':'cryptoasset'},
                'policy_versions':{'crypto':gate.VERSION},'crypto_evidence':{'version':gate.VERSION,'status':'reviewed',
                'assessment_artifact_id':'assessment','review_artifact_id':'review'},'artifacts':arts,'sources':[{'id':'s'}],'audit':{'author_id':'author'}}
    def test_valid(self):self.assertEqual(gate.validate(self.record())['status'],'crypto_evidence_verified')
    def test_supply_double_count_or_error(self):
        self.a['supply_reconciliation']['closing']=103
        with self.assertRaisesRegex(ValueError,'roll-forward'):gate.validate(self.record())
    def test_large_tolerance_cannot_hide_supply_error(self):
        self.a['supply_reconciliation'].update(closing=104,tolerance=100)
        with self.assertRaisesRegex(ValueError,'precision cap'):gate.validate(self.record())
    def test_missing_circle(self):
        self.a['comparators']=[x for x in self.a['comparators'] if x['id']!='CRCL']
        with self.assertRaisesRegex(ValueError,'COIN and CRCL'):gate.validate(self.record())
    def test_missing_noncrypto(self):
        self.a['comparators']=[x for x in self.a['comparators'] if x['kind']!='noncrypto']
        with self.assertRaisesRegex(ValueError,'noncrypto'):gate.validate(self.record())
    def test_unknown_is_not_evidenced(self):
        self.a['topics']['rates_liquidity']['source_ids']=[]
        with self.assertRaisesRegex(ValueError,'requires sources'):gate.validate(self.record())
    def test_explicit_limited_allowed(self):
        self.a['topics']['technical_market_structure']={'status':'limited','finding':'No reliable orderbook',
            'source_ids':[],'artifact_refs':['source'],'limitations':'Provider inaccessible',
            'decision_impact':'No claim of technical confirmation; scenario decision only'}
        gate.validate(self.record())
    def test_unavailable_supply_requires_impact(self):
        self.a['supply_reconciliation']={'status':'unavailable','reason':'No matched period'}
        with self.assertRaisesRegex(ValueError,'decision impact'):gate.validate(self.record())
    def test_stale_assessment_rejected(self):
        r=self.record();(self.root/'assessment.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'stale'):gate.validate(r)
    def test_same_author_rejected(self):
        r=self.record();r['audit']['author_id']='independent'
        with self.assertRaisesRegex(ValueError,'equals author'):gate.validate(r)
    def test_unresolved_source(self):
        r=self.record();r['sources']=[]
        with self.assertRaisesRegex(ValueError,'unresolved sources'):gate.validate(r)
    def test_noncrypto_unchanged(self):self.assertEqual(gate.validate({'scope':'company_full'})['status'],'not_applicable')
    def test_incomplete_not_certified(self):
        r=self.record();r['status']='in_progress';r['crypto_evidence']['status']='pending'
        self.assertEqual(gate.validate(r)['status'],'incomplete_not_certified')

class CryptoSchemaTests(unittest.TestCase):
    def fixture(self):
        from test_research_run_schema import fixture
        r=fixture();r['scope']='crypto_full';r['subject']['security_type']='cryptoasset'
        r['policy_versions'].update(crypto=gate.VERSION,entry_policy='2026-10-23-entry-policy-2')
        r['crypto_evidence']={'version':gate.VERSION,'status':'reviewed','assessment_artifact_id':'inputs','review_artifact_id':'review'}
        r['model'].update(framework='crypto_hybrid',scope_label='token_economics')
        r['entry_policy_evidence']={'version':'2026-10-23-entry-policy-2','status':'compared','basis':'crypto_bound',
            'probability_basis':'judgment','common_horizon_years':5,'initial_budget':10000,
            'information_cutoff':'synthetic','limitations':'Synthetic fixture only','baseline_artifact_ids':['inputs'],
            'source_evidence_artifact_ids':['source'],'input_artifact_id':'inputs','output_artifact_id':'outputs',
            'review_artifact_id':'review','decision':{'change':'unchanged','selected_policy':'wait','rationale':'Synthetic'}}
        return r
    def errors(self,r):
        from jsonschema import Draft202012Validator,FormatChecker
        return list(Draft202012Validator(json.loads((ROOT/'schemas/research-run.schema.json').read_text()),format_checker=FormatChecker()).iter_errors(r))
    def test_crypto_profile_accepts(self):self.assertEqual(self.errors(self.fixture()),[])
    def test_crypto_missing_policy_rejected(self):
        r=self.fixture();del r['policy_versions']['crypto'];self.assertTrue(self.errors(r))
    def test_crypto_missing_evidence_rejected(self):
        r=self.fixture();del r['crypto_evidence'];self.assertTrue(self.errors(r))
    def test_crypto_company_model_rejected(self):
        r=self.fixture();r['model']['framework']='FCFF_WACC';self.assertTrue(self.errors(r))
    def test_crypto_company_entry_binding_rejected(self):
        r=self.fixture();r['entry_policy_evidence']['basis']='company_bound';self.assertTrue(self.errors(r))
if __name__=='__main__':unittest.main()
