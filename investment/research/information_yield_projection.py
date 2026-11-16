"""Bounded read-only projection for immutable EIY v4 results."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator
from shared.research_sources.artifacts import ROOT, SourceError, digest, read

ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"); SHA=re.compile(r"^[a-f0-9]{64}$")
FORBIDDEN=re.compile(r"(?:^|_)(?:raw(?:_result)?|payload|prompt|credentials?|auth(?:entication|orization)?|token|secret|private|path|quote|exception|password|api_?key|access_?key)(?:$|_)",re.I)
SCHEMA=ROOT/'tuning/evals/information_fetch/information_yield/schemas/evaluation-result.schema.json'

class ProjectionError(ValueError):
 def __init__(self,code,exit_code=1):super().__init__(code);self.code=code;self.exit_code=exit_code
class SafeParser(argparse.ArgumentParser):
 def error(self,message):raise ProjectionError('EIY_PROJECTION_ARGUMENTS',2)
def need(ok,code,exit_code=1):
 if not ok:raise ProjectionError(code,exit_code)
def ident(v):need(isinstance(v,str) and ID.fullmatch(v),'EIY_PROJECTION_ID_INVALID',2);return v
def sha(v):need(isinstance(v,str) and SHA.fullmatch(v),'EIY_PROJECTION_HASH_INVALID');return v
def ref(v):
 need(isinstance(v,dict) and set(v)=={'path','sha256'},'EIY_PROJECTION_REF_INVALID',2)
 need(isinstance(v['path'],str) and len(v['path'])<=512,'EIY_PROJECTION_REF_INVALID',2)
 return {'path':v['path'],'sha256':sha(v['sha256'])}
def observation(v,unit,reason):
 if isinstance(v,(int,float)) and not isinstance(v,bool):need(v==v and abs(v)!=float('inf'),'EIY_PROJECTION_NUMBER_INVALID');return {'state':'known','value':v,'unit':unit}
 need(v is None,'EIY_PROJECTION_NUMBER_INVALID');return {'state':'unavailable','reason_code':reason}
def public(v,depth=0):
 need(depth<=6,'EIY_PROJECTION_VALUE_INVALID')
 if v is None or isinstance(v,(bool,int,float,str)):
  need(not isinstance(v,float) or (v==v and abs(v)!=float('inf')),'EIY_PROJECTION_VALUE_INVALID')
  need(not isinstance(v,str) or len(v)<=256,'EIY_PROJECTION_VALUE_INVALID');return v
 if isinstance(v,list):need(len(v)<=128,'EIY_PROJECTION_VALUE_INVALID');return [public(x,depth+1) for x in v]
 need(isinstance(v,dict) and len(v)<=64,'EIY_PROJECTION_VALUE_INVALID');out={}
 for k,x in v.items():need(isinstance(k,str) and len(k)<=64 and not FORBIDDEN.search(k),'EIY_PROJECTION_PRIVATE_FIELD');out[k]=public(x,depth+1)
 return out
def registry(v):
 need(isinstance(v,dict) and set(v)=={'schema_version','information_yield_results'} and v['schema_version']==1 and isinstance(v['information_yield_results'],list),'EIY_PROJECTION_REGISTRY_INVALID')
 need(len(v['information_yield_results'])<=64,'EIY_PROJECTION_REGISTRY_INVALID');index={}
 for row in v['information_yield_results']:
  need(isinstance(row,dict) and set(row)=={'evaluation_id','result_ref'},'EIY_PROJECTION_REGISTRY_INVALID');key=ident(row['evaluation_id']);need(key not in index,'EIY_PROJECTION_REGISTRY_DUPLICATE');index[key]=ref(row['result_ref'])
 return index
def case_dto(v):
 need(isinstance(v,dict) and isinstance(v.get('arms'),dict) and set(v['arms'])=={'B0','F'},'EIY_PROJECTION_CASE_INVALID');arms={}
 for arm in ('B0','F'):
  x=v['arms'][arm];need(isinstance(x,dict),'EIY_PROJECTION_CASE_INVALID');arms[arm]={
   'richness':observation(x.get('richness'),'canonical_units','RICHNESS_UNAVAILABLE'),'depth':observation(x.get('depth'),'field_state_steps','DEPTH_UNAVAILABLE'),
   'precision':observation(x.get('precision'),'ratio','PRECISION_UNAVAILABLE'),'wall_seconds':observation(x.get('wall_seconds'),'seconds','WALL_TIME_UNAVAILABLE'),
   'lineages':observation(x.get('lineages'),'original_lineages','LINEAGE_UNAVAILABLE'),'critical_unsupported':observation(x.get('critical_unsupported'),'units','CRITICAL_SUPPORT_UNAVAILABLE'),'trace':public(x.get('trace'))}
 failures=[];failure_keys=set()
 for f in v.get('hard_failures',[]):
  need(isinstance(f,dict) and set(f)=={'code','chain_ids'} and isinstance(f['chain_ids'],list),'EIY_PROJECTION_CASE_INVALID');code=ident(f['code']);chain_ids=sorted(sha(x) for x in f['chain_ids']);need(len(chain_ids)==len(set(chain_ids)),'EIY_PROJECTION_CASE_INVALID');key=(code,tuple(chain_ids));need(key not in failure_keys,'EIY_PROJECTION_CASE_INVALID');failure_keys.add(key);failures.append({'code':code,'chain_ids':chain_ids})
 failures.sort(key=lambda x:(x['code'],x['chain_ids']))
 return {'case_id':ident(v.get('case_id')),'issuer_id':ident(v.get('issuer_id')),'subject':ident(v.get('subject')),'window_id':ident(v.get('window_id')),'evidence_level':v.get('evidence_level'),'split':v.get('split'),'arm_order':list(v.get('arm_order',[])),'request_sha256':sha(v.get('request_sha256')),'fact_sha256':sha(v.get('fact_sha256')),'delta_r':observation(v.get('delta_r'),'canonical_units','RICHNESS_UNAVAILABLE'),'delta_d':observation(v.get('delta_d'),'field_state_steps','DEPTH_UNAVAILABLE'),'lineage_delta':observation(v.get('lineage_delta'),'original_lineages','LINEAGE_UNAVAILABLE'),'arms':arms,'hard_failures':failures}
def metric(v,unit):
 need(isinstance(v,dict),'EIY_PROJECTION_METRIC_INVALID')
 return {k:observation(v.get(k),unit,'OUTCOME_UNAVAILABLE') for k in ('mean','median','minimum','maximum','range','total')}|{k:v.get(k) for k in ('denominator','wins','ties','losses')}|{'leave_one_issuer_out':public(v.get('leave_one_issuer_out',[]))}
def project(registry_ref,evaluation_id,*,case_id=None,arm=None,run=None,source=None):
 evaluation_id=ident(evaluation_id)
 if arm is not None:need(case_id is not None and arm in {'B0','F'},'EIY_PROJECTION_SELECTOR_INVALID',2)
 if run is not None:need(arm is not None and isinstance(run,str) and ID.fullmatch(run),'EIY_PROJECTION_SELECTOR_INVALID',2)
 if source is not None:need(run is not None and isinstance(source,str) and ID.fullmatch(source),'EIY_PROJECTION_SELECTOR_INVALID',2)
 registry_ref=ref(registry_ref)
 try:index=registry(read(registry_ref))
 except SourceError as e:raise ProjectionError('EIY_PROJECTION_REGISTRY_UNAVAILABLE') from e
 need(evaluation_id in index,'EIY_PROJECTION_NOT_FOUND',3);result_ref=index[evaluation_id]
 try:result=read(result_ref);Draft202012Validator(json.loads(SCHEMA.read_text())).validate(result)
 except SourceError as e:raise ProjectionError('EIY_PROJECTION_RESULT_UNAVAILABLE') from e
 except Exception as e:raise ProjectionError('EIY_PROJECTION_RESULT_INVALID') from e
 need(result.get('evaluation_id')==evaluation_id,'EIY_PROJECTION_IDENTITY_CONFLICT',4)
 signed=dict(result);expected_summary=signed.pop('summary_sha256',None);need(isinstance(expected_summary,str) and digest(signed)==expected_summary,'EIY_PROJECTION_SUMMARY_CONFLICT',4)
 cases=[case_dto(x) for x in [*result['confirmation_cases'],*result['development_cases']]];need(len(cases)<=64 and len({x['case_id'] for x in cases})==len(cases),'EIY_PROJECTION_CASE_INVALID')
 selected=None
 if case_id is not None:case_id=ident(case_id);selected=next((x for x in cases if x['case_id']==case_id),None);need(selected is not None,'EIY_PROJECTION_NOT_FOUND',3)
 if run is not None or source is not None:raise ProjectionError('EIY_PROJECTION_NOT_FOUND',3)
 gates=[{'name':ident(g['name']),'status':g['status'],'observed':public(g['observed']),'threshold':public(g['threshold']),'numerator':public(g['numerator']),'denominator':public(g['denominator']),'case_results':public(g['case_results']),'reason_codes':[ident(x) for x in g['reason_codes']]} for g in result['policy_gates']]
 global_failures=sorted(({'case_id':c['case_id'],**f} for c in cases for f in c['hard_failures']),key=lambda x:(x['case_id'],x['code'],x['chain_ids']))
 need(not global_failures or result['verdict']=='reject','EIY_PROJECTION_VERDICT_CONFLICT',4)
 visible_cases=[selected] if selected else cases
 failures=sorted(({'case_id':c['case_id'],**f} for c in visible_cases for f in c['hard_failures']),key=lambda x:(x['case_id'],x['code'],x['chain_ids']))
 out={'schema_version':1,'view':'detail' if selected else 'summary','evaluation_id':evaluation_id,'registry_sha256':registry_ref['sha256'],'result_sha256':result_ref['sha256'],'verdict':result['verdict'],'counts':dict(result['counts']),'evidence':{'context_sha256':sha(result['context_sha256']),'fact_set_sha256':sha(result['fact_set_sha256']),'policy_sha256':sha(result['policy_sha256']),'source_closure_sha256':sha(result['source_closure_sha256']),'summary_sha256':sha(result['summary_sha256']),'claim_limits':[ident(x) for x in result['claim_limits']]},'outcomes':{'richness':metric(result['statistics']['richness'],'canonical_units'),'depth':metric(result['statistics']['depth'],'field_state_steps')},'policy_gates':gates,'hard_failures':failures,'cases':cases if selected is None else [],'selection':{'case_id':selected['case_id'] if selected else None,'arm':arm,'run':run,'source':source},'case':selected,'selected_arm':selected['arms'][arm] if selected and arm else None,'projection_state':'fresh','read_only':True}
 need(len(json.dumps(out,separators=(',',':'),allow_nan=False).encode())<=512*1024,'EIY_PROJECTION_OUTPUT_LIMIT');return out
def main(argv=None):
 p=SafeParser(add_help=False);p.add_argument('--registry-ref');p.add_argument('--evaluation-id');p.add_argument('--case-id');p.add_argument('--arm');p.add_argument('--run-id');p.add_argument('--source-id')
 try:
  a=p.parse_args(argv);need(a.registry_ref is not None and a.evaluation_id is not None,'EIY_PROJECTION_ARGUMENTS',2);out=project(json.loads(a.registry_ref),a.evaluation_id,case_id=a.case_id,arm=a.arm,run=a.run_id,source=a.source_id);print(json.dumps(out,separators=(',',':'),sort_keys=True));return 0
 except (ProjectionError,json.JSONDecodeError) as e:
  code=e.code if isinstance(e,ProjectionError) else 'EIY_PROJECTION_ARGUMENTS';status=e.exit_code if isinstance(e,ProjectionError) else 2;print(json.dumps({'error':{'code':code}},separators=(',',':')));return status
if __name__=='__main__':raise SystemExit(main())
