from __future__ import annotations
import ast, copy, hashlib, json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.adapters import AdapterContractError, PrimitiveAdapter, ClaudeAttemptAdapterV9, claude_adapter, codex_adapter
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.bundle import AttemptBundleStore, read_attempt_bundle
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import CHECK_NAMES, PROVIDER_BINDINGS, TRACE, canonical_bytes, sha256_bytes, sha256_json, strict_json_loads, validate_attempt_bundle
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.pipeline import PipelineError, execute
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.publication import PublicationTrace
try:
 from jsonschema import Draft202012Validator
except ImportError: Draft202012Validator=None
ROOT=Path(__file__).resolve().parents[5];PKG=ROOT/'shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1';FIX=ROOT/'shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1'
CASES=json.loads((FIX/'cases.json').read_text())['cells'];D='1'*64
ARTIFACTS={'ARM-A':json.loads((FIX/'claude-sanitized-publication.json').read_text()),'ARM-B':json.loads((FIX/'codex-sanitized-publication.json').read_text())}
MATERIALS={'ARM-A':json.loads((FIX/'claude-research-material.json').read_text()),'ARM-B':json.loads((FIX/'codex-research-material.json').read_text())}
RAW=b'{"raw":"synthetic"}'
BEHAVIORAL_CLOSURE=ROOT/'shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/behavioral-closure-v9.json'
def readback(cell):return {'version':1,'job_id':'job-'+cell,'slot_id':'slot-'+cell,'attempt_id':'attempt-'+cell,'operation_id':'operation/'+cell,'prompt_binding_sha256':D,'transaction':'BEGIN_IMMEDIATE_POST_WRITE_READBACK','counts':{'job':1,'slot':1,'attempt':1}}
def checks(status='PASS'):return [{'name':n,'status':status,'code':'CHECK_'+status} for n in CHECK_NAMES]
def research_material(cell,terminal,rb,artifact):
 value=copy.deepcopy(MATERIALS[cell['blind_provider_label']]);identity=PROVIDER_BINDINGS[cell['blind_provider_label']];binding={'cell_id':cell['cell_id'],'job_id':rb['job_id'],'slot_id':rb['slot_id'],'attempt_id':rb['attempt_id'],'operation_id':rb['operation_id'],'prompt_binding_sha256':D,'canonical_engine_readback_digest':sha256_json(rb),'source_cutoff_sha256':'2'*64,'blind_provider_label':identity['blind_provider_label'],'provider_schema':identity['provider_schema'],'publication_driver_identity_sha256':identity['publication_driver_identity_sha256']};raw_sha=sha256_bytes(RAW);artifact_sha=sha256_json(artifact)
 for body in value.values():body['binding']=copy.deepcopy(binding);body['provider_terminal']=terminal;body['raw_sha256']=raw_sha;body['publication_artifact_sha256']=artifact_sha
 if terminal!='PASS':value['sanitized_output']['answer']='Attempt ended with terminal '+terminal+'.';value['sanitized_output']['complete']=False
 return value
class EnvelopeTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir=FIX);self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
 def adapter(self,label,root,publication_fault=None):
  if label=='ARM-A':return claude_adapter(root/'owner-a',root/'public-a',PublicationTrace('public_file_fsync' if publication_fault=='partial' else None))
  return codex_adapter(root/'owner-b',root/'public-b','short_write' if publication_fault=='partial' else None)
 def invoke(self,cell,terminal='PASS',check_status='PASS',publication_fault=None,retention_fault=None,claimed=None,artifact=None,material=None,root=None,adapter=None):
  root=root or self.base;rb=readback(cell['cell_id']);adapter=adapter or self.adapter(cell['blind_provider_label'],root,publication_fault);artifact=copy.deepcopy(ARTIFACTS[cell['blind_provider_label']] if artifact is None else artifact);material=research_material(cell,terminal,rb,artifact) if material is None else copy.deepcopy(material)
  if claimed is not None:
   for body in material.values():body['binding']['canonical_engine_readback_digest']=claimed
  result=execute(adapter,root/'bundles',cell_id=cell['cell_id'],blind_addon_label=cell['blind_addon_label'],checks_enabled=cell['checks_enabled'],job_id=rb['job_id'],slot_id=rb['slot_id'],attempt_id=rb['attempt_id'],operation_id=rb['operation_id'],prompt_binding_sha256=D,readback=rb,raw=RAW,provider_publication_artifact=artifact,research_material=material,terminal_state=terminal,source_cutoff_sha256='2'*64,dq_checks=checks(check_status) if cell['checks_enabled'] else None,claimed_readback_digest=claimed,retention_fault=retention_fault)
  return result,root
 def reseal(self,bundle):
  value=copy.deepcopy(bundle);env=value['envelope'];value['denominator_record']['disposition']=env['publication_decision'];value['denominator_record']['terminal_state']=env['terminal_state'];value['denominator_record']['envelope_sha256']=sha256_json(env);body=dict(value);body.pop('bundle_digest',None);value['bundle_digest']=sha256_json(body);return value
 def owner_root_for(self,bundle):
  relative=Path(bundle['raw_custody_receipt']['raw_ref']['relative_ref'])
  for candidate in self.base.rglob(relative.name):
   if tuple(candidate.parts[-len(relative.parts):])==relative.parts:
    root=candidate
    for _ in relative.parts:root=root.parent
    return root
  raise AssertionError(('owner root not found',relative))
 def assert_bundle(self,r,root):
  files=list((root/'bundles').glob('*'));self.assertEqual(len(files),1);self.assertTrue(files[0].name.endswith('.attempt-bundle.json'));self.assertFalse(any(p.name.startswith('.stage-') for p in (root/'bundles').iterdir()));self.assertFalse((root/'private').exists());self.assertFalse((root/'ledger').exists())
  b=read_attempt_bundle(files[0],r['bundle_receipt']['sha256']);self.assertEqual(b,r['attempt_bundle']);self.assertIn('provider_publication_artifact_body',b);self.assertIn('envelope',b);self.assertTrue(b['denominator_record']['included']);self.assertFalse(b['denominator_record']['replay_allowed']);self.assertEqual(b['denominator_record'],r['denominator_record']);return b
 def test_real_adapters_publish_only_exact_committed_provider_shapes(self):
  for cell in (CASES[0],CASES[1]):
   root=self.base/cell['cell_id'];root.mkdir();r,_=self.invoke(cell,root=root);b=self.assert_bundle(r,root);self.assertEqual(r['publication']['status'],'PASS');self.assertEqual(json.loads(b['provider_publication_artifact_body']),ARTIFACTS[cell['blind_provider_label']]);self.assertEqual(r['bundle_receipt']['primitive'],'LINK_NO_REPLACE_SINGLE_FILE');self.assertTrue(r['bundle_receipt']['file_fsync'] and r['bundle_receipt']['parent_dir_fsync'] and r['bundle_receipt']['no_overwrite'])
   a=self.adapter(cell['blind_provider_label'],root/'wrong-digest')
   with self.assertRaises(Exception):a.publish_committed('never',root/'bundles'/r['bundle_receipt']['path'],'0'*64)
 def test_all_retention_faults_recover_one_whole_bundle_without_replay_or_residue(self):
  for i,fault in enumerate(('short_write','file_fsync','commit','dir_fsync','crash')):
   cell=CASES[i%4];root=self.base/('retention-'+fault);root.mkdir();r,_=self.invoke(cell,root=root,retention_fault=fault);b=self.assert_bundle(r,root);self.assertEqual(r['retention_recovery']['fault'],{'short_write':'BUNDLE_SHORT_WRITE','file_fsync':'BUNDLE_FILE_FSYNC','commit':'BUNDLE_COMMIT','dir_fsync':'BUNDLE_DIR_FSYNC','crash':'BUNDLE_CRASH_AFTER_STAGE_FSYNC'}[fault]);self.assertFalse(r['retention_recovery']['replay']);self.assertEqual(r['bundle_receipt']['recovered_fault'],r['retention_recovery']['fault']);self.assertTrue(b['denominator_record']['included']);self.assertIn('provider_publication_artifact_body',b);self.assertIn('envelope',b);self.assertEqual(r['publication']['attempts'],1)
 def test_no_selective_attrition_every_terminal_has_one_denominator_bundle(self):
  for i,terminal in enumerate(('PASS','FAIL','STOP','MALFORMED','MISSING','UNKNOWN')):
   cell=CASES[i%4];root=self.base/('terminal-'+terminal);root.mkdir();r,_=self.invoke(cell,terminal=terminal,root=root);b=self.assert_bundle(r,root);self.assertEqual(b['denominator_record']['terminal_state'],terminal);self.assertTrue(r['envelope']['retained'] and r['envelope']['denominator_member']);self.assertFalse(r['publication']['replay'])
 def test_old_generic_rejection_unknown_secret_partial_all_retain_bundle(self):
  generic={'sanitized':'{}','decision':{'decision':'DELEGATE_SANITIZED'}}
  for cell in (CASES[0],CASES[1]):
   root=self.base/('generic-'+cell['blind_provider_label']);root.mkdir();a=self.adapter(cell['blind_provider_label'],root)
   with self.assertRaises(Exception):a.validate_publication(generic)
   r,_=self.invoke(cell,artifact=generic,root=root,adapter=a);self.assertFalse(r['envelope']['provider_artifact_validated']);self.assertEqual(r['publication']['attempts'],0);self.assert_bundle(r,root)
   for suffix,kw in [('reject',{'check_status':'FAIL'} if cell['checks_enabled'] else {'terminal':'FAIL'}),('unknown',{'terminal':'UNKNOWN'})]:
    sub=self.base/(cell['blind_provider_label']+'-'+suffix);sub.mkdir();x,_=self.invoke(cell,root=sub,**kw);self.assertEqual(x['publication']['attempts'],0);self.assert_bundle(x,sub)
   sub=self.base/(cell['blind_provider_label']+'-secret');sub.mkdir();bad=copy.deepcopy(ARTIFACTS[cell['blind_provider_label']]);bad['api_key']='synthetic';x,_=self.invoke(cell,root=sub,artifact=bad);self.assertFalse(x['envelope']['provider_artifact_validated']);self.assert_bundle(x,sub)
   sub=self.base/(cell['blind_provider_label']+'-partial');sub.mkdir();x,_=self.invoke(cell,root=sub,publication_fault='partial');self.assertEqual(x['publication'],{'status':'UNKNOWN','attempts':1,'replay':False});self.assert_bundle(x,sub)
 def test_off_on_identical_plumbing_only_six_check_statuses_differ(self):
  results=[]
  for cell in CASES:
   r,_=self.invoke(cell);results.append(r);self.assertEqual(tuple(r['envelope']['pipeline_trace']),TRACE);self.assertEqual([x['status'] for x in r['envelope']['dq_checks']],['PASS']*6 if cell['checks_enabled'] else ['NOT_RUN_TREATMENT_DISABLED']*6)
  self.assertEqual({tuple(r['envelope']['pipeline_trace']) for r in results},{TRACE});self.assertEqual(len(list((self.base/'bundles').glob('*.attempt-bundle.json'))),4)
 def test_engine_mismatch_duplicate_and_path_swap_retain_or_no_replace(self):
  root=self.base/'mismatch';root.mkdir();r,_=self.invoke(CASES[0],claimed='0'*64,root=root);self.assertFalse(r['envelope']['readback_match']);self.assert_bundle(r,root)
  root=self.base/'duplicate';root.mkdir();r,_=self.invoke(CASES[1],root=root);before=(root/'bundles'/r['bundle_receipt']['path']).read_bytes()
  with self.assertRaisesRegex(PipelineError,'RAW_CAPTURE_FAILED'):self.invoke(CASES[1],root=root)
  self.assertEqual((root/'bundles'/r['bundle_receipt']['path']).read_bytes(),before);self.assertEqual(len(list((root/'bundles').glob('*.attempt-bundle.json'))),1)
  root=self.base/'swap';root.mkdir();faulted=claude_adapter(root/'owner-a',root/'public-a',capture_digest_fault=True)
  with self.assertRaisesRegex(PipelineError,'RAW_CAPTURE_DESCRIPTOR_MISMATCH'):self.invoke(CASES[0],root=root,adapter=faulted)
 def test_semantically_inconsistent_resealed_bundles_reject(self):
  root=self.base/'semantic';root.mkdir();r,_=self.invoke(CASES[1],root=root);base=r['attempt_bundle']
  variants=[]
  x=copy.deepcopy(base);x['envelope']['readback_match']=False;x['envelope']['gate_decision']='REJECT';x['envelope']['publication_decision']='SUPPRESS_SAFETY';variants.append(('READBACK_MATCH_NOT_DERIVED',x))
  x=copy.deepcopy(base);x['envelope']['gate_decision']='REJECT';x['envelope']['publication_decision']='SUPPRESS_GATE_REJECTED';variants.append(('GATE_DECISION_NOT_DERIVED',x))
  x=copy.deepcopy(base);x['envelope']['publication_decision']='SUPPRESS_GATE_REJECTED';variants.append(('PUBLICATION_DECISION_NOT_DERIVED',x))
  x=copy.deepcopy(base);x['envelope']['dq_checks'][0]['status']='NOT_RUN_TREATMENT_DISABLED';x['envelope']['dq_checks'][0]['code']='NOT_RUN_TREATMENT_DISABLED';variants.append(('ON_CHECK_DISABLED',x))
  offroot=self.base/'semantic-off';offroot.mkdir();off,_=self.invoke(CASES[0],root=offroot);x=copy.deepcopy(off['attempt_bundle']);x['envelope']['dq_checks'][0]={'name':CHECK_NAMES[0],'status':'PASS','code':'CHECK_PASS'};variants.append(('OFF_CHECK_NOT_DISABLED',x))
  for i,(code,value) in enumerate(variants):
   value=self.reseal(value)
   with self.assertRaisesRegex(Exception,code):validate_attempt_bundle(value)
   target=self.base/('adversarial-'+str(i));target.mkdir()
   with self.assertRaisesRegex(Exception,code):AttemptBundleStore(target,owner_root=self.owner_root_for(value)).commit(value)
 def test_every_duplicated_authoritative_field_cross_bound_after_reseal(self):
  root=self.base/'cross-bind';root.mkdir();r,_=self.invoke(CASES[1],root=root);base=r['attempt_bundle'];variants=[]
  mutations={
   'blind_provider_label':'ARM-Z',
   'blind_addon_label':'CONDITION-Z',
   'checks_enabled':False,
   'terminal_state':'FAIL',
   'raw_ref':dict(base['normalized_attempt']['raw_ref'],name='other-raw.ref'),
   'source_inventory':['other-official-source'],
   'citation_inventory':['other-citation'],
   'source_cutoff_sha256':'3'*64,
   'readback_ref':dict(base['normalized_attempt']['readback_ref'],job_id='other-job'),
   'key':dict(base['normalized_attempt']['key'],job_id='other-job'),
   'publication_artifact_ref':dict(base['normalized_attempt']['publication_artifact_ref'],name='other-publication.json'),
  }
  for field,changed in mutations.items():
   value=copy.deepcopy(base);value['normalized_attempt'][field]=changed;value=self.reseal(value);variants.append((field,value))
  for i,(field,value) in enumerate(variants):
   code='ATTEMPT_BUNDLE_CROSS_BIND_'+field.upper()
   with self.assertRaisesRegex(Exception,code):validate_attempt_bundle(value)
   target=self.base/('cross-bind-adversarial-'+str(i));target.mkdir()
   with self.assertRaisesRegex(Exception,code):AttemptBundleStore(target,owner_root=self.owner_root_for(value)).commit(value)
 def test_v7_missing_and_semantic_evidence_mismatches_reject(self):
  cell=CASES[1];rb=readback(cell['cell_id']);artifact=copy.deepcopy(ARTIFACTS['ARM-B']);base=research_material(cell,'PASS',rb,artifact);variants=[]
  missing=copy.deepcopy(base);missing.pop('factual_evidence');variants.append(('RESEARCH_MATERIAL_SHAPE',missing,True))
  secret=copy.deepcopy(base);secret['sanitized_output']['answer']='bearer synthetic-value';variants.append(('RESEARCH_SECRET_OR_PATH_FORBIDDEN',secret,True))
  cutoff=copy.deepcopy(base);cutoff['source_inventory']['sources'][0]['source_cutoff_sha256']='9'*64;variants.append(('SOURCE_CUTOFF_OR_ELIGIBILITY',cutoff,True))
  source=copy.deepcopy(base);source['citation_inventory']['citations'][0]['source_id']='missing-source';variants.append(('CITATION_SOURCE_LOCATION_BINDING',source,True))
  location=copy.deepcopy(base);location['citation_inventory']['citations'][0]['literal_location']='missing-location';variants.append(('CITATION_SOURCE_LOCATION_BINDING',location,True))
  claim=copy.deepcopy(base);claim['citation_inventory']['citations'][0]['claim_id']='missing-claim';variants.append(('RESEARCH_CLAIM_BINDING',claim,True))
  raw=copy.deepcopy(base);raw['factual_evidence']['raw_sha256']='8'*64;variants.append(('RESEARCH_RAW_DIGEST_MISMATCH',raw,True))
  for i,(code,material,_) in enumerate(variants):
   root=self.base/('v7-material-'+str(i));root.mkdir()
   with self.assertRaisesRegex(Exception,code):self.invoke(cell,root=root,artifact=artifact,material=material)
 def test_v7_resealed_bundle_refs_and_bodies_reject(self):
  root=self.base/'v7-nominal';root.mkdir();r,_=self.invoke(CASES[0],root=root);base=r['attempt_bundle'];variants=[]
  x=copy.deepcopy(base);x['research_evidence'].pop('factual_evidence');variants.append(('RESEARCH_EVIDENCE_SHAPE',x))
  x=copy.deepcopy(base);x['research_evidence']['sanitized_output']['ref']['relative_ref']='../escape.json';variants.append(('OWNER_REF_PATH_INVALID',x))
  x=copy.deepcopy(base);x['research_evidence']['sanitized_output']['body']['answer']='Substituted answer';variants.append(('SANITIZED_OUTPUT_DIGEST_BINDING',x))
  x=copy.deepcopy(base);x['raw_custody_receipt']['raw_sha256']='8'*64;variants.append(('RAW_CUSTODY_BINDING',x))
  for i,(code,value) in enumerate(variants):
   value=self.reseal(value)
   with self.assertRaisesRegex(Exception,code):validate_attempt_bundle(value)
   target=self.base/('v7-bundle-'+str(i));target.mkdir()
   with self.assertRaisesRegex(Exception,code):AttemptBundleStore(target,owner_root=self.owner_root_for(value)).commit(value)
 def test_v7_owner_ref_substitution_mode_and_raw_tamper_block_publication(self):
  for i,cell in enumerate((CASES[0],CASES[1])):
   root=self.base/('v7-owner-'+str(i));root.mkdir();r,_=self.invoke(cell,root=root);bundle_path=root/'bundles'/r['bundle_receipt']['path'];adapter=self.adapter(cell['blind_provider_label'],root)
   support_ref=r['research_evidence']['sanitized_output']['ref']['relative_ref'];support_path=adapter.owner_root/support_ref
   support_path.chmod(0o644)
   with self.assertRaisesRegex(Exception,'OWNER_REF_FILE_UNSAFE'):adapter.publish_committed(r['attempt_bundle']['key_digest'],bundle_path,r['bundle_receipt']['sha256'])
   support_path.chmod(0o600)
   raw_path=adapter.owner_root/r['raw_custody_receipt']['raw_ref']['relative_ref'];raw_path.write_bytes(b'tampered');raw_path.chmod(0o600)
   with self.assertRaisesRegex(Exception,'OWNER_REF_DIGEST_MISMATCH'):adapter.publish_committed(r['attempt_bundle']['key_digest'],bundle_path,r['bundle_receipt']['sha256'])
 def test_v7_stop_unknown_retain_complete_research_evidence(self):
  for terminal,cell in (('STOP',CASES[0]),('UNKNOWN',CASES[1])):
   root=self.base/('v7-'+terminal.lower());root.mkdir();r,_=self.invoke(cell,terminal=terminal,root=root);bundle=self.assert_bundle(r,root);self.assertEqual(bundle['raw_custody_receipt']['provider_terminal'],terminal);self.assertEqual(bundle['research_evidence']['sanitized_output']['body']['provider_terminal'],terminal);self.assertFalse(bundle['research_evidence']['sanitized_output']['body']['complete']);self.assertTrue(bundle['denominator_record']['included']);self.assertFalse(bundle['denominator_record']['replay_allowed'])
 def test_representation_exact_type_and_nested_alias_adversaries_reject(self):
  onroot=self.base/'repr-on';onroot.mkdir();on,_=self.invoke(CASES[1],root=onroot);offroot=self.base/'repr-off';offroot.mkdir();off,_=self.invoke(CASES[0],root=offroot);variants=[]
  x=copy.deepcopy(on['attempt_bundle']);x['normalized_attempt']['checks_enabled']=1;variants.append(('ATTEMPT_BUNDLE_CROSS_BIND_TYPE_CHECKS_ENABLED',x))
  x=copy.deepcopy(off['attempt_bundle']);x['normalized_attempt']['checks_enabled']=0;variants.append(('ATTEMPT_BUNDLE_CROSS_BIND_TYPE_CHECKS_ENABLED',x))
  nested=[('readback_ref',lambda v:v['normalized_attempt']['readback_ref']['counts'].__setitem__('job',True)),('raw_ref',lambda v:v['normalized_attempt']['raw_ref'].__setitem__('bytes',True)),('source_inventory',lambda v:v['normalized_attempt'].__setitem__('source_inventory',[1])),('citation_inventory',lambda v:v['normalized_attempt'].__setitem__('citation_inventory',[True])),('key',lambda v:v['normalized_attempt']['key'].__setitem__('job_id',1)),('publication_artifact_ref',lambda v:v['normalized_attempt']['publication_artifact_ref'].__setitem__('bytes',1.0))]
  for field,mutate in nested:
   x=copy.deepcopy(on['attempt_bundle']);mutate(x);variants.append(('ATTEMPT_BUNDLE_CROSS_BIND_'+field.upper(),x))
  for i,(code,value) in enumerate(variants):
   value=self.reseal(value)
   with self.assertRaisesRegex(Exception,code):validate_attempt_bundle(value)
   target=self.base/('representation-adversarial-'+str(i));target.mkdir()
   with self.assertRaisesRegex(Exception,code):AttemptBundleStore(target,owner_root=self.owner_root_for(value)).commit(value)
 def test_duplicate_key_safe_json_rejects_nested_duplicates(self):
  with self.assertRaisesRegex(Exception,'DUPLICATE_KEY_TEST'):strict_json_loads('{"outer":{"x":1,"x":2}}','DUPLICATE_KEY_TEST')
 def test_real_process_crash_restart_stage_and_post_link(self):
  prep=self.base/'crash-prep';prep.mkdir();r,_=self.invoke(CASES[0],root=prep);bundle=r['attempt_bundle'];owner_root=self.owner_root_for(bundle);source=self.base/'crash-input.json';source.write_bytes(canonical_bytes(bundle));worker=Path(__file__).with_name('_crash_worker.py')
  for window in ('stage_created','post_link'):
   target=self.base/('real-crash-'+window);target.mkdir();env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1';proc=subprocess.run([sys.executable,str(worker),str(source),str(target),window,str(owner_root)],cwd=str(ROOT),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False);self.assertLess(proc.returncode,0,(window,proc.returncode,proc.stderr.decode('utf-8',errors='replace')))
   stage=target/('.stage-'+bundle['key']['cell_id']+'.attempt-bundle.json');dest=target/(bundle['key']['cell_id']+'.attempt-bundle.json')
   self.assertTrue(stage.exists())
   if window=='stage_created':self.assertFalse(dest.exists())
   else:
    self.assertTrue(dest.exists());sm=stage.stat();dm=dest.stat();self.assertEqual((sm.st_dev,sm.st_ino),(dm.st_dev,dm.st_ino));self.assertEqual(dm.st_nlink,2)
   receipt=AttemptBundleStore(target,owner_root=owner_root).commit(bundle,recovered_fault='REAL_CRASH_'+window.upper());self.assertTrue(dest.exists());self.assertFalse(stage.exists());self.assertEqual(dest.stat().st_nlink,1);value=read_attempt_bundle(dest,receipt.sha256);self.assertEqual(value,bundle);self.assertTrue(value['denominator_record']['included']);self.assertFalse(value['denominator_record']['replay_allowed']);self.assertEqual(len(list(target.glob('*.attempt-bundle.json'))),1)
 def test_publish_committed_requires_exact_name_and_bundle_digest(self):
  for cell in (CASES[0],CASES[1]):
   root=self.base/('publish-binding-'+cell['blind_provider_label']);root.mkdir();r,_=self.invoke(cell,root=root);path=root/'bundles'/r['bundle_receipt']['path'];a=self.adapter(cell['blind_provider_label'],root)
   with self.assertRaisesRegex(Exception,'BUNDLE_PUBLICATION_NAME_MISMATCH'):a.publish_committed('wrong-name',path,r['bundle_receipt']['sha256'])
   with self.assertRaisesRegex(Exception,'BUNDLE_READBACK_DIGEST'):a.publish_committed(r['attempt_bundle']['key_digest'],path,'0'*64)
 def test_v8_fact_citation_claim_and_source_tuple_swaps_reject_every_boundary(self):
  cell=CASES[1];root=self.base/'v9-tuple-base';root.mkdir();result,_=self.invoke(cell,root=root);base=copy.deepcopy(result['attempt_bundle']);owner_root=self.owner_root_for(base);evidence=base['research_evidence']
  evidence['sanitized_output']['body']['claim_ids']=['claim-a','claim-b','claim-shared']
  evidence['factual_evidence']['body']['facts']=[{'fact_id':'fact-a','claim_id':'claim-a','value':'A','source_id':'source-one','citation_id':'citation-a'},{'fact_id':'fact-b','claim_id':'claim-b','value':'B','source_id':'source-one','citation_id':'citation-b'},{'fact_id':'fact-c','claim_id':'claim-shared','value':'C','source_id':'source-one','citation_id':'citation-c'},{'fact_id':'fact-d','claim_id':'claim-shared','value':'D','source_id':'source-two','citation_id':'citation-d'}]
  evidence['source_inventory']['body']['sources']=[{'source_id':'source-one','url':'https://www.microsoft.com/source-one','document_identity_sha256':'3'*64,'source_cutoff_sha256':'2'*64,'eligible':True,'literal_locations':['loc-a','loc-b','loc-c']},{'source_id':'source-two','url':'https://www.microsoft.com/source-two','document_identity_sha256':'5'*64,'source_cutoff_sha256':'2'*64,'eligible':True,'literal_locations':['loc-d']}]
  evidence['citation_inventory']['body']['citations']=[{'citation_id':'citation-a','claim_id':'claim-a','source_id':'source-one','literal_location':'loc-a','quote_sha256':'4'*64},{'citation_id':'citation-b','claim_id':'claim-b','source_id':'source-one','literal_location':'loc-b','quote_sha256':'6'*64},{'citation_id':'citation-c','claim_id':'claim-shared','source_id':'source-one','literal_location':'loc-c','quote_sha256':'7'*64},{'citation_id':'citation-d','claim_id':'claim-shared','source_id':'source-two','literal_location':'loc-d','quote_sha256':'8'*64}]
  for entry in evidence.values():
   raw=canonical_bytes(entry['body']);entry['canonical_sha256']=sha256_bytes(raw);entry['ref']['sha256']=sha256_bytes(raw);entry['ref']['canonical_sha256']=sha256_bytes(raw);entry['ref']['bytes']=len(raw)
  variants=[]
  x=copy.deepcopy(base);x['research_evidence']['factual_evidence']['body']['facts'][0]['citation_id']='citation-b';x['research_evidence']['factual_evidence']['body']['facts'][1]['citation_id']='citation-a';variants.append(x)
  x=copy.deepcopy(base);x['research_evidence']['factual_evidence']['body']['facts'][2]['citation_id']='citation-d';x['research_evidence']['factual_evidence']['body']['facts'][3]['citation_id']='citation-c';variants.append(x)
  adapter=self.adapter('ARM-B',root)
  for i,value in enumerate(variants):
   entry=value['research_evidence']['factual_evidence'];raw=canonical_bytes(entry['body']);entry['canonical_sha256']=sha256_bytes(raw);entry['ref']['sha256']=sha256_bytes(raw);entry['ref']['canonical_sha256']=sha256_bytes(raw);entry['ref']['bytes']=len(raw);value=self.reseal(value)
   with self.assertRaisesRegex(Exception,'FACT_CITATION_SOURCE_TUPLE_BINDING'):validate_attempt_bundle(value)
   target=self.base/('v9-tuple-commit-'+str(i));target.mkdir()
   with self.assertRaisesRegex(Exception,'FACT_CITATION_SOURCE_TUPLE_BINDING'):AttemptBundleStore(target,owner_root=owner_root).commit(value)
   malicious=self.base/('v9-tuple-publish-'+str(i));malicious.mkdir();path=malicious/(value['key']['cell_id']+'.attempt-bundle.json');blob=canonical_bytes(value);path.write_bytes(blob);path.chmod(0o600)
   with self.assertRaisesRegex(Exception,'FACT_CITATION_SOURCE_TUPLE_BINDING'):adapter.publish_committed(value['key_digest'],path,sha256_bytes(blob))
 def test_v8_false_owner_uid_rejects_commit_and_publication_for_all_refs(self):
  for index,cell in enumerate((CASES[0],CASES[1])):
   root=self.base/('v8-uid-'+str(index));root.mkdir();r,_=self.invoke(cell,root=root);base=r['attempt_bundle'];owner_root=self.owner_root_for(base);refs=[base['raw_custody_receipt']['raw_ref']]+[base['research_evidence'][name]['ref'] for name in ('sanitized_output','factual_evidence','source_inventory','citation_inventory')];adapter=self.adapter(cell['blind_provider_label'],root)
   for j in range(len(refs)):
    value=copy.deepcopy(base);target_refs=[value['raw_custody_receipt']['raw_ref']]+[value['research_evidence'][name]['ref'] for name in ('sanitized_output','factual_evidence','source_inventory','citation_inventory')];target_refs[j]['owner_uid']+=1;value=self.reseal(value);target=self.base/('v8-uid-commit-'+str(index)+'-'+str(j));target.mkdir()
    with self.assertRaisesRegex(Exception,'OWNER_REF_FILE_UNSAFE'):AttemptBundleStore(target,owner_root=owner_root).commit(value)
    malicious=self.base/('v8-uid-publish-'+str(index)+'-'+str(j));malicious.mkdir();path=malicious/(value['key']['cell_id']+'.attempt-bundle.json');blob=canonical_bytes(value);path.write_bytes(blob);path.chmod(0o600)
    with self.assertRaisesRegex(Exception,'OWNER_REF_FILE_UNSAFE'):adapter.publish_committed(value['key_digest'],path,sha256_bytes(blob))
 def test_v8_cross_provider_material_swap_rejects(self):
  cell=CASES[1];rb=readback(cell['cell_id']);artifact=copy.deepcopy(ARTIFACTS['ARM-B']);material=copy.deepcopy(MATERIALS['ARM-A']);binding={'cell_id':cell['cell_id'],'job_id':rb['job_id'],'slot_id':rb['slot_id'],'attempt_id':rb['attempt_id'],'operation_id':rb['operation_id'],'prompt_binding_sha256':D,'canonical_engine_readback_digest':sha256_json(rb),'source_cutoff_sha256':'2'*64,'blind_provider_label':'ARM-A','provider_schema':'claude-evidence-v1','publication_driver_identity_sha256':PROVIDER_BINDINGS['ARM-A']['publication_driver_identity_sha256']}
  for body in material.values():body['binding']=copy.deepcopy(binding);body['provider_terminal']='PASS';body['raw_sha256']=sha256_bytes(RAW);body['publication_artifact_sha256']=sha256_json(artifact)
  root=self.base/'v8-provider-swap';root.mkdir()
  with self.assertRaisesRegex(Exception,'EVIDENCE_BINDING_MISMATCH'):self.invoke(cell,root=root,artifact=artifact,material=material)
 def test_v9_arbitrary_base_and_subclass_adapters_reject(self):
  with self.assertRaisesRegex(AdapterContractError,'ARBITRARY_PROVIDER_ADAPTER_FORBIDDEN'):PrimitiveAdapter()
  class EvilClaude(ClaudeAttemptAdapterV9):pass
  root=self.base/'v9-subclass';root.mkdir();evil=EvilClaude(root/'owner-a',root/'public-a')
  with self.assertRaisesRegex(Exception,'PROVIDER_ADAPTER_TYPE_MISMATCH'):self.invoke(CASES[0],root=root,adapter=evil)
  class Arbitrary:
   pass
  with self.assertRaisesRegex(Exception,'PROVIDER_ADAPTER_TYPE_MISMATCH'):self.invoke(CASES[0],root=self.base/'v9-arbitrary',adapter=Arbitrary())
 def test_v9_coherent_claude_to_codex_relabel_reseal_rejects_all_boundaries(self):
  cell=CASES[1];rb=readback(cell['cell_id']);artifact=copy.deepcopy(ARTIFACTS['ARM-B']);material=copy.deepcopy(MATERIALS['ARM-A']);identity=PROVIDER_BINDINGS['ARM-B'];binding={'cell_id':cell['cell_id'],'job_id':rb['job_id'],'slot_id':rb['slot_id'],'attempt_id':rb['attempt_id'],'operation_id':rb['operation_id'],'prompt_binding_sha256':D,'canonical_engine_readback_digest':sha256_json(rb),'source_cutoff_sha256':'2'*64,'blind_provider_label':'ARM-B','provider_schema':identity['provider_schema'],'publication_driver_identity_sha256':identity['publication_driver_identity_sha256']}
  for body in material.values():body['binding']=copy.deepcopy(binding);body['provider_terminal']='PASS';body['raw_sha256']=sha256_bytes(RAW);body['publication_artifact_sha256']=sha256_json(artifact)
  root=self.base/'v9-relabel';root.mkdir()
  with self.assertRaisesRegex(Exception,'PROVIDER_RESEARCH_MATERIAL_MISMATCH'):self.invoke(cell,root=root,artifact=artifact,material=material)
  validroot=self.base/'v9-valid-codex';validroot.mkdir();result,_=self.invoke(cell,root=validroot);value=copy.deepcopy(result['attempt_bundle']);owner_root=self.owner_root_for(value)
  for name,body in material.items():
   entry=value['research_evidence'][name];entry['body']=copy.deepcopy(body);raw=canonical_bytes(entry['body']);entry['canonical_sha256']=sha256_bytes(raw);entry['ref']['sha256']=sha256_bytes(raw);entry['ref']['canonical_sha256']=sha256_bytes(raw);entry['ref']['bytes']=len(raw)
  value=self.reseal(value)
  with self.assertRaisesRegex(Exception,'PROVIDER_RESEARCH_MATERIAL_MISMATCH'):validate_attempt_bundle(value)
  target=self.base/'v9-relabel-commit';target.mkdir()
  with self.assertRaisesRegex(Exception,'PROVIDER_RESEARCH_MATERIAL_MISMATCH'):AttemptBundleStore(target,owner_root=owner_root).commit(value)
  malicious=self.base/'v9-relabel-publication';malicious.mkdir();path=malicious/(value['key']['cell_id']+'.attempt-bundle.json');blob=canonical_bytes(value);path.write_bytes(blob);path.chmod(0o600);adapter=self.adapter('ARM-B',validroot)
  with self.assertRaisesRegex(Exception,'PROVIDER_RESEARCH_MATERIAL_MISMATCH'):adapter.publish_committed(value['key_digest'],path,sha256_bytes(blob))
 def test_v8_behavioral_closure_is_complete_and_candidate_referenced_not_active(self):
  closure=json.loads(BEHAVIORAL_CLOSURE.read_text());self.assertEqual(closure['status'],'DISABLED_CANDIDATE_REFERENCED_NOT_ACTIVE_RUNTIME');self.assertFalse(closure['activation']);self.assertEqual(closure['authority'],'NONE');self.assertEqual(closure['active_runtime_consumers'],[])
  for row in closure['direct_dependencies']+closure['candidate_consumers']+closure['test_consumers']:
   raw=(ROOT/row['path']).read_bytes();self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(row['bytes'],row['sha256']),row['path'])
  token='r6_data_quality_attempt_envelope_v1';actual=[];actual_tests=[]
  for path in sorted(ROOT.rglob('*.py')):
   if any(part in ('.git','runtime','__pycache__') for part in path.parts):continue
   if token in path.read_text() and token not in path.parts:
    (actual_tests if 'tests' in path.parts else actual).append(path.relative_to(ROOT).as_posix())
  self.assertEqual(actual,[row['path'] for row in closure['candidate_consumers']])
  self.assertEqual(actual_tests,[row['path'] for row in closure['test_consumers']])
  self.assertEqual([path for path in (ROOT/'shared/job_runtime').glob('*.py') if token in path.read_text()],[])
 @unittest.skipUnless(Draft202012Validator is not None,'Draft 2020-12 validator unavailable')
 def test_five_closed_draft_schemas_validate_real_bundle_instances(self):
  schemas={p.name:json.loads(p.read_text()) for p in PKG.glob('*.schema.json')};self.assertEqual(len(schemas),11)
  for s in schemas.values():Draft202012Validator.check_schema(s);self.assertFalse(s['additionalProperties'])
  root=self.base/'schema';root.mkdir();r,_=self.invoke(CASES[0],root=root);instances={'normalized-attempt-v1.schema.json':r['attempt'],'dq-attempt-envelope-v1.schema.json':r['envelope'],'sanitized-publication-decision-v1.schema.json':r['publication_decision'],'canonical-engine-readback-ref-v1.schema.json':readback(CASES[0]['cell_id']),'attempt-bundle-v1.schema.json':r['attempt_bundle'],'owner-artifact-ref-v1.schema.json':r['raw_custody_receipt']['raw_ref'],'raw-custody-receipt-v1.schema.json':r['raw_custody_receipt'],'sanitized-research-output-v1.schema.json':r['research_evidence']['sanitized_output']['body'],'factual-evidence-v1.schema.json':r['research_evidence']['factual_evidence']['body'],'source-inventory-v1.schema.json':r['research_evidence']['source_inventory']['body'],'citation-inventory-v1.schema.json':r['research_evidence']['citation_inventory']['body']}
  for name,value in instances.items():Draft202012Validator(schemas[name]).validate(value);bad=copy.deepcopy(value);bad['extra']=True;self.assertFalse(Draft202012Validator(schemas[name]).is_valid(bad))
 def test_disabled_unreferenced_frozen_sources_and_history_exact(self):
  forbidden={'socket','subprocess','smtplib','urllib','http'}
  for path in PKG.glob('*.py'):
   imports=set();tree=ast.parse(path.read_text())
   for n in ast.walk(tree):
    if isinstance(n,ast.Import):imports.update(a.name.split('.')[0] for a in n.names)
    elif isinstance(n,ast.ImportFrom) and n.module:imports.add(n.module.split('.')[0])
   self.assertTrue(imports.isdisjoint(forbidden),(path,imports&forbidden))
  frozen=[(ROOT/'shared/job_runtime/engine.py',71795,'42721bf751ebe50cc0720138bfb66509cababd2b873e41192ee50d9cf8df10be'),(ROOT/'shared/job_runtime/engine_schema.py',17377,'f3f22ce1ec6531ad4d0e9cfdb7aa63b78b5a21ddee69fa74b6b60d713ad87e9b'),(ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-producer-verification.json',5685,'52c1907ef6865903d8e73c71b87e9056cd8f480cb70195f643cc823f10a40d10'),(ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-producer-verification-v2.json',7833,'70fd915e9273387995f6cf4f0991ad10339f6eb4693bbfce1fd0302cba97471f'),(ROOT/'mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-independent-review.json',0,'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')]
  for path,size,digest in frozen:
   raw=path.read_bytes();self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(size,digest))
  self.assertEqual([p for p in (ROOT/'shared/job_runtime').glob('*.py') if 'r6_data_quality_attempt_envelope_v1' in p.read_text()],[])
if __name__=='__main__':unittest.main()
