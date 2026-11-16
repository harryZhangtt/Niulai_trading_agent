from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json,shutil,tempfile,unittest,uuid
from pathlib import Path
from investment.research.acquisition_eiy_checker import check_eiy_case_v3,audit_eiy_case_v3,current_semantic_source_closure,EiyCheckerError
from investment.research.acquisition_review import record_reviewer_decision
from investment.research.acquisition_runner import HostedAcquisitionRunner,HostedProviderResponse
from shared.research_sources.acquisition_contracts import AcquisitionIdentity,DispatchIdentity,ExactArguments,RunIdentity,CheckedEiyV3Request
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,save,digest
from tuning.evals.information_fetch.information_yield.contracts import canonical
from tuning.evals.information_fetch.information_yield.evaluator import evaluate_fresh_checked_facts,evaluate_now_diagnostics
H='a'*64;QUESTION='revenue.v1:issuer';QUOTE='reported revenue expanded'
class EiyV3Fixture:
 def __init__(self,testcase,*,mode='evaluation',subject='ACME',units=1,units_by_arm=None,disposition_by_arm=None,ambiguous=False,invented=False,closure_drift=False,case_index=1,issuer=None,all_case_ids=None,all_case_rows=None,arm_order=None,evidence_level=None,split=None):
  runtime=ROOT/'investment/runtime/eiy-v3-tests';runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
  artifacts=SOURCE_STATE/'tmp';artifacts.mkdir(parents=True,exist_ok=True,mode=0o700)
  self.inputs_tmp=tempfile.TemporaryDirectory(dir=runtime);self.artifacts_tmp=tempfile.TemporaryDirectory(dir=artifacts);testcase.addCleanup(self.inputs_tmp.cleanup);testcase.addCleanup(self.artifacts_tmp.cleanup)
  self.inputs=Path(self.inputs_tmp.name);self.artifacts=Path(self.artifacts_tmp.name);self.mode=mode;self.subject=subject;self.arm_order=arm_order or ['B0','F'];self.case_id=f'case-{case_index}';self.issuer=issuer or f'ISSUER-{case_index}';self.case_suffix=str(case_index);self.all_case_ids=all_case_ids or [self.case_id];self.all_case_rows=all_case_rows
  per_arm=units_by_arm or {'B0':units,'F':units};dispositions=disposition_by_arm or {'B0':'approve','F':'approve'}
  self.arms={arm:self.build_arm(arm,units=per_arm[arm],disposition=dispositions[arm],ambiguous=ambiguous,invented=invented and arm=='F') for arm in ('B0','F')}
  level=evidence_level or ('diagnostic' if subject=='NOW' else 'development');split=split or ('diagnostic' if subject=='NOW' else 'development')
  self.values={
   'metric_policy_ref':self.put('policy.json',json.loads((ROOT/'tuning/evals/information_fetch/information_yield/metric-policy-v4.json').read_text())),
   'case_contract_ref':self.put('case.json',{'schema_version':'information-yield-case-contract-3','evaluation_id':'eval-v3','case_id':self.case_id,'issuer_id':self.issuer,'subject':subject,'window_id':f'2026Q{self.case_suffix}','cutoff':'2026-01-01T00:00:00Z','evidence_level':level,'split':split,'arm_order':self.arm_order}),
   'case_roster_ref':self.put('case-roster.json',{'schema_version':'information-yield-case-roster-4','evaluation_id':'eval-v3','case_ids':self.all_case_ids,'cases':self.all_case_rows or [{'case_id':case_id,'issuer_id':('ISSUER-'+case_id.split('-')[-1]),'subject':'ACME','window_id':'2026Q'+case_id.split('-')[-1],'cutoff':'2026-01-01T00:00:00Z','evidence_level':'confirmation' if evidence_level=='confirmation' else 'development','split':'untouched' if split=='untouched' else 'development','arm_order':['B0','F']} for case_id in self.all_case_ids]}),
   'allocation_ref':self.put('allocation.json',{'schema_version':'information-yield-allocation-4','evaluation_id':'eval-v3','cases':{row['case_id']:row['arm_order'] for row in (self.all_case_rows or [{'case_id':case_id,'arm_order':['B0','F']} for case_id in self.all_case_ids])}}),
   'baseline_ref':self.put('baseline.json',{'schema_version':'information-yield-baseline-3','canonical_key_sha256s':[]}),
   'reference_set_ref':self.put('reference.json',{'schema_version':'information-yield-reference-set-3','canonical_key_sha256s':[]}),
   'required_fields_ref':self.put('required.json',{'schema_version':'information-yield-required-fields-4','fields':[{'field_id':'revenue','question_ids':[QUESTION],'baseline_state':'unknown','critical':True}]}),
   'freshness_targets_ref':self.put('freshness.json',{'schema_version':'information-yield-freshness-targets-3','targets':[{'target_id':'target','question_ids':[QUESTION],'target_sha256':H}]}),
   'financial_element_roster_ref':self.put('financial.json',{'schema_version':'information-yield-financial-roster-3','elements':[{'element_id':'entity','field_ids':['revenue']}]}),
  }
  closure=current_semantic_source_closure(ROOT)
  if closure_drift:closure={**closure,'sources_sha256':'0'*64}
  self.values['source_closure_ref']=self.put('closure.json',closure)
  self.arm_refs={arm:self.put(f'arm-{arm}.json',value) for arm,value in self.arms.items()}
  self.rebuild_request()
 def put(self,name,value):
  path=self.inputs/name;raw=canonical(value);path.write_bytes(raw);path.chmod(0o600);return {'path':str(path.relative_to(ROOT)),'sha256':sha256(raw).hexdigest()}
 def read_ref(self,ref):
  path=ROOT/ref['path'];raw=path.read_bytes();assert sha256(raw).hexdigest()==ref['sha256'];return json.loads(raw)
 def build_arm(self,arm,*,units,disposition,ambiguous,invented):
  prefix=f'{arm.lower()}-{self.case_suffix}';ids={'experiment_id':f'experiment-{prefix}','execution_id':f'execution-{prefix}','trace_id':f'trace-{prefix}'};operation=f'open-{prefix}';attempt=f'{operation}:1';arguments={'open':[{'ref_id':f'https://example.com/{prefix}.html'}],'response_length':'long'}
  raw=save(self.artifacts,{'raw':f'synthetic-{prefix}'});text=f'Synthetic disclosure says {QUOTE} in period.'+(f' Again {QUOTE}.' if ambiguous else '');text_ref=save(self.artifacts,text.encode(),suffix='txt');source=save(self.artifacts,{'schema_version':1,'access_level':'document','source_url':f'https://example.com/{prefix}.html','source_version':raw['sha256'],'raw':raw,'text':text_ref})
  assessment=save(self.artifacts,{'kind':'acquisition_quote_assessment',**ids,'operation_id':operation,'attempt_id':attempt,'question_id':QUESTION,'source_ref':source,'source_version':raw['sha256'],'raw_sha256':raw['sha256'],'text_sha256':text_ref['sha256'],'quote':QUOTE,'assessment_author_id':f'author-{prefix}','operator_id':f'operator-{prefix}'})
  unit_refs=[];review_refs=[]
  for index in range(units):
   unit=save(self.artifacts,{'kind':'acquisition_candidate_unit',**ids,'unit_id':f'unit-{prefix}-{index}','question_id':QUESTION,'assessment_ref':assessment,'source_ref':source,'quote':QUOTE});unit_refs.append(unit)
   review_refs.append(record_reviewer_decision(self.artifacts,assessment_ref=assessment,unit_ref=unit,reviewer_id=f'reviewer-{prefix}-{index}',assessment_author_id=f'author-{prefix}',operator_id=f'operator-{prefix}',disposition=disposition,checks={'question_relevance':True,'literal_support':True,'canonical_lineage':True},reason='Literal support and lineage agree.'))
  proposal=save(self.artifacts,{'kind':'acquisition_proposal','operation_id':operation,'question_ids':[QUESTION],'arguments':arguments});request_ref=save(self.artifacts,{'items':arguments['open'],'arguments':arguments});receipt=save(self.artifacts,{'kind':'acquisition_operation_receipt','execution_id':ids['execution_id'],'operation_id':operation,'operation':'open','fetch_executed':True,'provider_items':1,'request_ref':request_ref,'source_sha256s':[source['sha256']]});event=save(self.artifacts,{'operation_id':operation,'exposed_source_refs':[source]});exposure=save(self.artifacts,{'event_refs':[event]});host=save(self.artifacts,{'kind':'acquisition_eval_run','execution_id':ids['execution_id'],'backend':'native_tools.web__run','search_receipt_refs':[],'open_receipt_refs':[receipt],'exposure_ref':exposure,'usage':{'provider_items':1}});manifest=save(self.artifacts,{'questions':[{'id':QUESTION,'question':'What revenue evidence is supported?'}]});transition=save(self.artifacts,{'decision':'capture','operation_id':operation});controller=save(self.artifacts,{'manifest_ref':manifest,'transition_refs':[transition],'usage':{'provider_items':1}});driver=save(self.artifacts,{'kind':'acquisition_driver_run',**ids,'controller_summary_ref':controller,'host_run_ref':host,'assessment_refs':[assessment],'unit_refs':unit_refs,'operation_states':{operation:[{'sequence':0,'state':'reserved'},{'sequence':1,'state':'finalized'}]}})
  runner=HostedAcquisitionRunner(self.artifacts/f'runner-{prefix}',provider=lambda *_:HostedProviderResponse([b'synthetic'],observed_backend='native_tools.web__run'),configured_backend='native_tools.web__run',run_deadline=100,raw_byte_limit=1024,monotonic=lambda:1);runner.prepare(AcquisitionIdentity(RunIdentity(**ids),DispatchIdentity(operation,attempt,f'dispatch-{prefix}')),ExactArguments.from_mapping(arguments));runner.claim(f'dispatch-{prefix}');dispatch=runner.invoke(f'dispatch-{prefix}',call_deadline=50)['dispatch_ref']
  value={'schema_version':'information-yield-arm-manifest-3','arm':arm,'config':{**ids,'backend':'native_tools.web__run','model_sha256':H,'effort':'fixed','prompt_sha256':H,'tool_sha256':H,'safety_sha256':H,'catalog_sha256':H,'taxonomy_sha256':H,'budget':{'provider':1},'deadlines':{'run':10,'observed_wall_seconds':5},'cache_namespace':f'cache-{prefix}','cache_mode':'disabled','order_index':self.arm_order.index(arm),'cutoff':'2026-01-01T00:00:00Z','expected_dispatches':1,'expected_credited_units':(units if disposition=='approve' else 0),'trust_policy':'operational_host_evidence','host_session_id':f'session-{prefix}','host_adapter':'codex_native_web'},'driver_ref':driver,'dispatch_refs':[dispatch],'proposal_refs':[proposal],'review_refs':review_refs,'reconciliation_ref':save(self.artifacts,{'ok':True}),'host_invocation_refs':[],'host_profile_ref':save(self.artifacts,{'ok':True}),'credential_readiness_ref':save(self.artifacts,{'ok':True}),'recovery_opportunities':[{'opportunity_id':'r1','classification':'eligible','outcome_known_at_classification':False}]}
  if invented:value['canonical_units']=[{'invented':True}]
  return value
 def rebuild_request(self,*,swap=False):
  arm_refs={'B0':self.arm_refs['F'] if swap else self.arm_refs['B0'],'F':self.arm_refs['B0'] if swap else self.arm_refs['F']}
  core={'schema_version':'information-yield-check-request-3','evaluation_id':'eval-v3','mode':self.mode,**self.values,'arms':{arm:{'arm':arm,'manifest_ref':arm_refs[arm]} for arm in ('B0','F')}}
  core_sha=sha256(canonical(core)).hexdigest();custody={'schema_version':'information-yield-custody-3','evaluation_id':'eval-v3','case_id':self.case_id,'pre_start_bound':True,'request_core_sha256':core_sha,'arm_manifest_sha256s':{arm:arm_refs[arm]['sha256'] for arm in ('B0','F')}};custody_ref=self.put('custody.json',custody);unsigned={**core,'custody_ref':custody_ref};unsigned['request_sha256']=sha256(canonical(unsigned)).hexdigest();self.request_value=unsigned;self.request_ref=self.put('request.json',unsigned);self.request=CheckedEiyV3Request.from_mapping(unsigned);refs=[self.request_ref];manifest={'schema_version':'information-yield-evaluation-3','mode':self.mode,'evaluation_id':'eval-v3','case_request_refs':refs,'planned_cases':1,'case_set_sha256':digest(refs)};manifest['manifest_sha256']=digest(manifest);self.manifest_ref=self.put('manifest.json',manifest)
 def check(self):return check_eiy_case_v3(self.request,read_ref=self.read_ref,workspace_root=ROOT)
 def batch(self,fixtures=None,request_refs=None):
  fixtures=fixtures or [self];refs=request_refs or [f.request_ref for f in fixtures];first=fixtures[0]
  custody={'schema_version':'information-yield-evaluation-custody-4','evaluation_id':'eval-v3','mode':first.mode,'metric_policy_ref':first.values['metric_policy_ref'],'case_roster_ref':first.values['case_roster_ref'],'allocation_ref':first.values['allocation_ref'],'baseline_ref':first.values['baseline_ref'],'reference_set_ref':first.values['reference_set_ref'],'required_fields_ref':first.values['required_fields_ref'],'freshness_targets_ref':first.values['freshness_targets_ref'],'financial_element_roster_ref':first.values['financial_element_roster_ref'],'source_closure_ref':first.values['source_closure_ref'],'request_refs':refs}
  custody['custody_sha256']=digest(custody);custody_ref=first.put('evaluation-custody.json',custody);manifest={'schema_version':'information-yield-evaluation-manifest-4','evaluation_custody_ref':custody_ref};manifest['manifest_sha256']=digest(manifest);manifest_ref=first.put('evaluation-manifest-v4.json',manifest);return custody_ref,manifest_ref
class EiyV3CheckerTests(unittest.TestCase):
 def test_provider_free_fact_is_fresh_but_v3_list_reducer_disabled(self):
  f=EiyV3Fixture(self);fact=f.check();mapping=fact.to_audit_mapping();self.assertEqual(mapping['schema_version'],'information-yield-checked-fact-3');self.assertEqual(len(mapping['arms']['F']['canonical_units'][0]['chain_ids']),1)
  with self.assertRaisesRegex(Exception,'EIY_V3_EVALUATION_CONTEXT_REQUIRED'):evaluate_fresh_checked_facts(fresh_facts=[fact])
 def test_invented_evidence_never_reaches_evaluator(self):
  f=EiyV3Fixture(self,invented=True)
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN'):f.check()
 def test_ambiguous_quote_has_no_chain(self):
  f=EiyV3Fixture(self,ambiguous=True)
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_EVIDENCE_CHAIN_UNKNOWN'):f.check()
 def test_duplicate_canonical_representation_dedupes_with_two_chains(self):
  f=EiyV3Fixture(self,units=2);arm=f.check().to_audit_mapping()['arms']['F'];self.assertEqual(len(arm['canonical_units']),1);self.assertEqual(len(arm['canonical_units'][0]['chain_ids']),2)
 def test_source_closure_drift_rejected(self):
  f=EiyV3Fixture(self,closure_drift=True)
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_SOURCE_CLOSURE_DRIFT'):f.check()
 def test_o2_audit_rerun_has_nominal_fact_hash_parity(self):
  f=EiyV3Fixture(self);observed=f.check().to_audit_mapping()['fact_sha256'];audit=audit_eiy_case_v3(f.request,read_ref=f.read_ref,workspace_root=ROOT,expected_fact_sha256=observed);self.assertEqual(audit['fact_sha256'],observed)
 def test_cross_arm_swap_rejected(self):
  f=EiyV3Fixture(self);f.rebuild_request(swap=True)
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_ARM_MANIFEST'):f.check()
 def test_now_fact_is_fresh_but_v3_list_reducer_disabled(self):
  f=EiyV3Fixture(self,mode='now_diagnostic',subject='NOW');fact=f.check();self.assertEqual(fact.to_audit_mapping()['schema_version'],'information-yield-now-diagnostic-fact-3')
  with self.assertRaisesRegex(Exception,'EIY_V3_EVALUATION_CONTEXT_REQUIRED'):evaluate_now_diagnostics(fresh_facts=[fact])
 def test_now_hard_integrity_has_fixed_rejection(self):
  f=EiyV3Fixture(self,mode='now_diagnostic',subject='NOW',ambiguous=True)
  with self.assertRaisesRegex(EiyCheckerError,'ACQ_EIY_NOW_HARD_INTEGRITY_FAILURE'):f.check()
if __name__=='__main__':unittest.main()
