import copy,json,re
from pathlib import Path
import unittest
from factor.docker.gcp import profile
from factor.docker.gcp import output_contracts as outputs
ROOT=Path(__file__).resolve().parents[1]; CANDIDATE=ROOT/'runtime-profile.json'; SYNTHETIC=ROOT/'fixtures/synthetic-ready-v1.json'
def schema_accepts(s,v):
    if 'const'in s:return type(v)is type(s['const'])and v==s['const']
    if 'oneOf'in s and set(s)<= {'$schema','$id','title','oneOf'}:return sum(schema_accepts(x,v)for x in s['oneOf'])==1
    if 'type'in s:
     types={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool}
     if s['type']in types and type(v)is not types[s['type']]:return False
    if 'enum'in s and v not in s['enum']:return False
    if 'pattern'in s and (type(v)is not str or re.fullmatch(s['pattern'],v)is None):return False
    if type(v)is dict:
     if s.get('additionalProperties')is False and not set(v)<=set(s.get('properties',{})):return False
     if not set(s.get('required',[]))<=set(v):return False
     if any(not schema_accepts(spec,v[k])for k,spec in s.get('properties',{}).items()if k in v):return False
    if type(v)is list:
     if len(v)<s.get('minItems',0)or len(v)>s.get('maxItems',10**9):return False
     if s.get('uniqueItems')and len({json.dumps(x,sort_keys=True)for x in v})!=len(v):return False
     if 'items'in s and any(not schema_accepts(s['items'],x)for x in v):return False
    if 'oneOf'in s and sum(schema_accepts(x,v)for x in s['oneOf'])!=1:return False
    return True
class Tests(unittest.TestCase):
 def setUp(self):self.c=profile.load_profile(CANDIDATE);self.s=profile.load_profile(SYNTHETIC)
 def test_candidate_disabled(self):
  self.assertFalse(self.c['runnable']);self.assertTrue(all(x is None for x in self.c['projects'].values()));self.assertTrue(all(x is False or x is None for x in self.c['activation'].values()))
 def test_actual_v2_job_shape_and_nonoverride_invocation(self):
  t=profile.render_templates(self.s)
  for role,wrapper in t['jobs'].items():
   job=wrapper['job'];contract=wrapper['contract']
   self.assertEqual(set(job),{'name','labels','template','launchStage','binaryAuthorization'})
   self.assertEqual(job['name'],f"projects/{self.s['projects'][self.s['jobs'][role]['project_role']]}/locations/us-central1/jobs/factor-{role}")
   task=job['template']['template'];self.assertEqual(len(task['containers']),1);self.assertIn('@sha256:',task['containers'][0]['image']);self.assertEqual(task['vpcAccess']['egress'],'ALL_TRAFFIC');self.assertNotIn('image',job);self.assertNotIn('ingress',job);self.assertNotIn('outputContract',job);self.assertNotIn('active',job)
   self.assertFalse(contract['active']);self.assertFalse(contract['rawRows'])
   self.assertEqual(t['iam_policy_specs'][role]['allow']['permission'],'run.jobs.run');self.assertIn('run.jobs.runWithOverrides',t['iam_policy_specs'][role]['denyPermissions'])
 def test_executor_concrete_egress(self):
  n=profile.render_templates(self.s)['network_policy_spec']['executor'];self.assertEqual(n['routes'][0]['destinationRange'],'199.36.153.4/30');self.assertEqual(n['rules'][-1]['action'],'deny');self.assertEqual(n['rules'][-1]['destinationRanges'],['0.0.0.0/0']);self.assertFalse(n['publicEgress']);self.assertEqual(n['vpcServiceControls']['services'],['storage.googleapis.com','cloudkms.googleapis.com'])
 def test_security_mutations_fail(self):
  cases=[]
  for path,val in [(('network','executor','public_egress'),True),(('jobs','executor','sidecars'),True),(('jobs','executor','active_access'),True)]:
   d=copy.deepcopy(self.s);d[path[0]][path[1]][path[2]]=val;cases.append(d)
  d=copy.deepcopy(self.s);d['jobs']['executor']['secrets']=['x'];cases.append(d)
  d=copy.deepcopy(self.s);d['jobs']['executor']['image_digest']='repo:latest';cases.append(d)
  for x in cases:
   with self.assertRaises(profile.GcpProfileError):profile.validate_profile(x)
 def test_concern_reuse_fails(self):
  for f in('service_account','vpc','subnet','network_tag'):
   d=copy.deepcopy(self.s);d['jobs']['executor'][f]=d['jobs']['controller'][f]
   with self.assertRaises(profile.GcpProfileError):profile.validate_profile(d)
 def test_exact_profile_and_template_schemas(self):
  ps=json.loads((ROOT/'runtime-profile-v1.schema.json').read_text());ts=json.loads((ROOT/'templates-v1.schema.json').read_text());t=profile.render_templates(self.s)
  self.assertTrue(schema_accepts(ps,self.c));self.assertTrue(schema_accepts(ps,self.s));self.assertTrue(schema_accepts(ts,t));bad=copy.deepcopy(t);bad['jobs']['executor']['job']['template']['template']['containers'][0]['args']=['--override'];self.assertFalse(schema_accepts(ts,bad));self.assertRaises(profile.GcpProfileError,profile.validate_templates,bad,self.s)
  custom=copy.deepcopy(t);custom['jobs']['executor']['job']['outputContract']={'unsafe':True};self.assertFalse(schema_accepts(ts,custom));self.assertRaises(profile.GcpProfileError,profile.validate_templates,custom,self.s)
 def binding(self):return {'bucket':'factor-label-fixture','object':'versions/v1.json','generation':'1','metageneration':1,'commitment_sha256':'a'*64}
 def test_output_contracts_are_value_free_and_exact(self):
  structural={'schema_version':1,'kind':'factor_structural_receipt','role':'executor','job_name':'factor-executor','execution_id':'exec-one','image_digest_sha256':'b'*64,'request_sha256':'c'*64,'artifact_binding':self.binding(),'outcome_accessed':False,'protected_labels_accessed':False,'performance_claim':'withheld','raw_rows_emitted':False};self.assertEqual(outputs.validate_structural(structural),structural)
  aggregate={'schema_version':1,'kind':'factor_aggregate_receipt','role':'evaluator','job_name':'factor-evaluator','execution_id':'eval-one','image_digest_sha256':'b'*64,'checkpoint_binding':self.binding(),'label_binding':self.binding(),'aggregate_commitment_sha256':'d'*64,'output_schema_id':'factor-evaluator-aggregate-v1','redaction_policy_id':'factor-no-sensitive-output-v1','raw_rows_emitted':False,'labels_emitted':False,'structured_stdout_only':True,'performance_claim':'withheld'};self.assertEqual(outputs.validate_aggregate(aggregate),aggregate)
  schema=json.loads((ROOT/'aggregate-receipt-v1.schema.json').read_text());self.assertTrue(schema_accepts(schema,aggregate))
  bad=copy.deepcopy(aggregate);bad['raw_rows_emitted']=True
  with self.assertRaises(outputs.OutputError):outputs.validate_aggregate(bad)
  wrong=copy.deepcopy(aggregate);wrong['output_schema_id']='factor-checker-aggregate-v1';self.assertFalse(schema_accepts(schema,wrong))
  with self.assertRaises(outputs.OutputError):outputs.validate_aggregate(wrong)
 def test_catalog_requires_two_approvals_and_inactive(self):
  v={'schema_version':1,'kind':'factor_publication_catalog_entry','release_id':'release-one','manifest_commitment_sha256':'1'*64,'evaluator_receipt_sha256':'2'*64,'checker_receipt_sha256':'3'*64,'approval_commitments':['4'*64,'5'*64],'signature_commitment_sha256':'6'*64,'catalog_binding':self.binding(),'publication_active':False};self.assertEqual(outputs.validate_catalog(v),v);v['approval_commitments']=['4'*64,'4'*64]
  with self.assertRaises(outputs.OutputError):outputs.validate_catalog(v)
if __name__=='__main__':unittest.main()
