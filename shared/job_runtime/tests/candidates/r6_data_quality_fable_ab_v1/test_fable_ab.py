from __future__ import annotations
import ast, copy, hashlib, json, math, os, tempfile, unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.bundle import BundleError, RawDecisionStore, read_bundle
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import (CELL_ORDER, DQ_CHECKS, FROZEN_INPUTS, LIMITS, MODEL_ID, ContractError, canonical_bytes, sha256_bytes, sha256_json, strict_json_loads, validate_bundle, validate_result)
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.runner import default_run, run_pair
try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None
ROOT=Path(__file__).resolve().parents[5]; PKG=ROOT/'shared/job_runtime/candidates/r6_data_quality_fable_ab_v1'

def checks(status='PASS'):
    return [{"name":n,"status":status,"code":"CHECK_"+status} for n in DQ_CHECKS]

def factory(terminal='PASS', mutate=None):
    def make(plan):
        value={"plan_echo":copy.deepcopy(plan),"attempt_id":"attempt-"+plan["cell_id"],"terminal_state":terminal,
               "attempt_count":0 if terminal=='STOP' else 1,"raw":('raw-'+plan["cell_id"]+'-'+terminal).encode('ascii'),
               "dq_checks":checks() if plan["dq_enabled"] else None}
        if mutate: mutate(value,plan)
        return value
    return make

class FableABTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
    def test_default_is_effect_free_deny(self):
        x=default_run(); self.assertFalse(x['countable']); self.assertTrue(all(v==0 for v in x['effects'].values()))
    def test_exact_same_model_symmetric_off_on(self):
        r=run_pair(factory(),self.root); validate_result(r); self.assertEqual([c['plan']['model'] for c in r['cells']],[MODEL_ID,MODEL_ID])
        a,b=r['cells']; self.assertFalse(a['plan']['dq_enabled']); self.assertTrue(b['plan']['dq_enabled'])
        for key in ('model','inputs','limits'): self.assertEqual(a['plan'][key],b['plan'][key])
        self.assertEqual(a['dq_checks'][0]['status'],'NOT_RUN_TREATMENT_DISABLED'); self.assertEqual(b['dq_checks'][0]['status'],'PASS')
    def test_all_terminal_dispositions_retain_denominator_and_never_publish(self):
        for terminal in ('PASS','FAIL','STOP','MALFORMED','MISSING','UNKNOWN'):
            root=self.root/terminal; r=run_pair(factory(terminal),root); self.assertEqual(r['denominator_count'],2); self.assertEqual(r['publication_attempts'],0)
            for c in r['cells']:
                self.assertTrue(c['denominator_included']); self.assertIn(terminal,c['disposition']); self.assertEqual(c['publication']['attempts'],0)
                self.assertEqual(c['publication']['unknown_fenced'],terminal=='UNKNOWN')
    def test_zero_retry_replay_status_tool_web_subagent_fallback(self):
        r=run_pair(factory(),self.root)
        for c in r['cells']:
            self.assertEqual([c[k] for k in ('retry_count','replay_count','status_query_count','tool_count','web_count','subagent_count','fallback_count')],[0]*7)
            self.assertEqual(c['plan']['limits'],LIMITS)
    def test_drift_rejected_into_retained_invalid_cell(self):
        def mutate(v,p): v['plan_echo']['inputs']['prompt_sha256']='0'*64
        r=run_pair(factory(mutate=mutate),self.root); self.assertTrue(all('PLAN_ECHO_DRIFT' in c['validity_errors'] for c in r['cells']))
    def test_duplicate_nonfinite_and_implicit_types_rejected(self):
        with self.assertRaisesRegex(ContractError,'DUP'): strict_json_loads('{"x":1,"x":2}','DUP')
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ContractError): canonical_bytes({'x':bad})
        r=run_pair(factory(),self.root); bad=copy.deepcopy(r); bad['denominator_count']=True
        with self.assertRaises(ContractError): validate_result(bad)
    def test_unknown_dq_check_is_retained_and_invalid(self):
        def mutate(v,p):
            if p['dq_enabled']: v['dq_checks']=checks('UNKNOWN')
        r=run_pair(factory(mutate=mutate),self.root); self.assertEqual(r['cells'][1]['validity_errors'],['DQ_NOT_ALL_PASS']); self.assertTrue(r['cells'][1]['denominator_included'])
    def test_raw_is_committed_before_decision_and_restart_recovers(self):
        plan={"version":1,"cell_id":CELL_ORDER[0],"order_index":0,"model":MODEL_ID,"dq_enabled":False,"inputs":copy.deepcopy(FROZEN_INPUTS),"limits":copy.deepcopy(LIMITS)}
        outcome=factory()(plan); raw=outcome['raw']; root=self.root/'crash'
        with self.assertRaisesRegex(BundleError,'CRASH_AFTER_RAW'):
            # Build through normal runner to leave exactly the raw commit.
            run_pair(factory(),self.root/'pair',fault_cell=CELL_ORDER[0])
        crashdir=self.root/'pair'/CELL_ORDER[0]; self.assertTrue((crashdir/(CELL_ORDER[0]+'.raw')).exists()); self.assertFalse((crashdir/(CELL_ORDER[0]+'.bundle.json')).exists())
        r=run_pair(factory(),self.root/'pair'); self.assertEqual(r['denominator_count'],2); self.assertTrue((crashdir/(CELL_ORDER[0]+'.bundle.json')).exists())
    def test_no_replace_duplicate_and_partial_decision(self):
        run_pair(factory(),self.root); before={p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        run_pair(factory(),self.root)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_second_cell_raw_crash_preserves_first_and_restart_completes_pair(self):
        with self.assertRaisesRegex(BundleError,'CRASH_AFTER_RAW'):
            run_pair(factory(),self.root,fault_cell=CELL_ORDER[1])
        first_raw=self.root/CELL_ORDER[0]/(CELL_ORDER[0]+'.raw'); first_bundle=self.root/CELL_ORDER[0]/(CELL_ORDER[0]+'.bundle.json')
        second_raw=self.root/CELL_ORDER[1]/(CELL_ORDER[1]+'.raw'); second_bundle=self.root/CELL_ORDER[1]/(CELL_ORDER[1]+'.bundle.json')
        first_before=(first_raw.read_bytes(),first_bundle.read_bytes()); self.assertTrue(second_raw.exists()); self.assertFalse(second_bundle.exists())
        result=run_pair(factory(),self.root); self.assertEqual(result['denominator_count'],2)
        self.assertEqual(first_before,(first_raw.read_bytes(),first_bundle.read_bytes())); self.assertTrue(second_bundle.exists())

    def test_completed_and_raw_only_conflicts_reject_without_replacement(self):
        run_pair(factory(),self.root/'complete'); bundle=self.root/'complete'/CELL_ORDER[0]/(CELL_ORDER[0]+'.bundle.json'); before=bundle.read_bytes()
        bundle.write_bytes(before+b' ')
        with self.assertRaisesRegex(BundleError,'COMPLETED_BUNDLE_CONFLICT'):
            run_pair(factory(),self.root/'complete')
        self.assertEqual(bundle.read_bytes(),before+b' ')
        rawroot=self.root/'raw-conflict'
        with self.assertRaisesRegex(BundleError,'CRASH_AFTER_RAW'):
            run_pair(factory(),rawroot,fault_cell=CELL_ORDER[0])
        raw=rawroot/CELL_ORDER[0]/(CELL_ORDER[0]+'.raw'); raw_before=raw.read_bytes(); raw.write_bytes(b'conflict')
        with self.assertRaisesRegex(BundleError,'NO_REPLACE'):
            run_pair(factory(),rawroot)
        self.assertEqual(raw.read_bytes(),b'conflict'); self.assertNotEqual(raw.read_bytes(),raw_before)
    def test_path_swap_symlink_rejected(self):
        target=self.root/'target'; target.write_text('x'); cellroot=self.root/'swap'/CELL_ORDER[0]; cellroot.mkdir(parents=True); os.symlink(target,cellroot/(CELL_ORDER[0]+'.raw'))
        with self.assertRaises(BundleError): run_pair(factory(),self.root/'swap')
        self.assertEqual(target.read_text(),'x')
    def test_bundle_tamper_rejected(self):
        run_pair(factory(),self.root); path=self.root/CELL_ORDER[0]/(CELL_ORDER[0]+'.bundle.json'); raw=path.read_bytes(); value=json.loads(raw); value['cell']['publication']['attempts']=1
        with self.assertRaises(ContractError): validate_bundle(value)
        with self.assertRaises(BundleError): read_bundle(path,'0'*64)
    def test_secret_and_path_never_enter_result_or_bundle(self):
        secret='SYNTHETIC_API_KEY_DO_NOT_LEAK'; path='/private/synthetic/path'
        def mutate(v,p): v['secret']=secret; v['path']=path
        r=run_pair(factory(mutate=mutate),self.root); encoded=canonical_bytes(r)
        self.assertNotIn(secret.encode(),encoded); self.assertNotIn(path.encode(),encoded)
        for file in self.root.rglob('*.json'):
            self.assertNotIn(secret.encode(),file.read_bytes()); self.assertNotIn(path.encode(),file.read_bytes())
    def test_closed_schemas(self):
        if Draft202012Validator is None: self.skipTest('jsonschema unavailable')
        r=run_pair(factory(),self.root); bundle=json.loads((self.root/CELL_ORDER[0]/(CELL_ORDER[0]+'.bundle.json')).read_text())
        instances={'plan-v1.schema.json':r['cells'][0]['plan'],'cell-v1.schema.json':r['cells'][0],'bundle-v1.schema.json':bundle,'result-v1.schema.json':r}
        for name,value in instances.items():
            schema=json.loads((PKG/name).read_text()); Draft202012Validator.check_schema(schema); self.assertFalse(schema['additionalProperties']); Draft202012Validator(schema).validate(value)
    def test_python_schema_adversarial_parity(self):
        if Draft202012Validator is None: self.skipTest('jsonschema unavailable')
        result=run_pair(factory(),self.root); bundle=json.loads((self.root/CELL_ORDER[0]/(CELL_ORDER[0]+'.bundle.json')).read_text())
        schemas={name:Draft202012Validator(json.loads((PKG/name).read_text())) for name in ('plan-v1.schema.json','cell-v1.schema.json','bundle-v1.schema.json','result-v1.schema.json')}
        good=[('plan-v1.schema.json',result['cells'][0]),('cell-v1.schema.json',result['cells'][0]),('bundle-v1.schema.json',bundle),('result-v1.schema.json',result)]
        schemas['plan-v1.schema.json'].validate(result['cells'][0]['plan'])
        for name,value in good[1:]: schemas[name].validate(value)
        variants=[]
        x=copy.deepcopy(result['cells'][0]['plan']); x['dq_enabled']=True; variants.append(('plan-v1.schema.json',x,lambda: None))
        x=copy.deepcopy(result['cells'][0]); x['dq_checks'][0]={'name':DQ_CHECKS[0],'status':'PASS','code':'CHECK_PASS'}; variants.append(('cell-v1.schema.json',x,lambda: None))
        x=copy.deepcopy(result['cells'][1]); x['terminal_state']='UNKNOWN'; x['disposition']='RETAIN_UNKNOWN_NO_PUBLICATION'; x['publication']['unknown_fenced']=False; x['validity_errors']=['DQ_NOT_ALL_PASS']; variants.append(('cell-v1.schema.json',x,lambda: None))
        x=copy.deepcopy(result); x['cells'][0],x['cells'][1]=x['cells'][1],x['cells'][0]; variants.append(('result-v1.schema.json',x,lambda: validate_result(x)))
        x=copy.deepcopy(bundle); x['cell']['publication']['attempts']=1; variants.append(('bundle-v1.schema.json',x,lambda: validate_bundle(x)))
        for name,value,python_check in variants:
            self.assertFalse(schemas[name].is_valid(value),(name,value));
            if name in ('bundle-v1.schema.json','result-v1.schema.json'):
                with self.assertRaises(Exception): python_check()

    def test_provider_free_source_and_frozen_predecessor_hashes(self):
        forbidden={'anthropic','socket','subprocess','smtplib','urllib','requests','httpx'}
        for path in PKG.glob('*.py'):
            imports=set(); tree=ast.parse(path.read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.Import): imports.update(a.name.split('.')[0] for a in n.names)
                elif isinstance(n,ast.ImportFrom) and n.module: imports.add(n.module.split('.')[0])
            self.assertTrue(imports.isdisjoint(forbidden),(path,imports&forbidden))
        expected={'__init__.py':'d76f2244cbdea8423270b9121e44a83e0e182b8b6f638a31bcd1b7751fa25cd4','adapters.py':'0c091a12b43deae4ea6cc4f339c7fa1c23c2a29182acf1090741aea63f5ff185','bundle.py':'aa998b6062e7e39c4b64f8dea04c7c7cf143be546eb8dd9a0f3e542bdec20346','contracts.py':'d18a87daee088524ab26f23ea5e8238aa5b33c5e6c2fdc4e1ef3f920c4877d17','pipeline.py':'c6c4dd06af2f2caf9649689a20901c84118a8386999ce4e7af3f1d29ed0d99c3'}
        old=ROOT/'shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1'
        for name,digest in expected.items(): self.assertEqual(hashlib.sha256((old/name).read_bytes()).hexdigest(),digest)

if __name__=='__main__': unittest.main()
