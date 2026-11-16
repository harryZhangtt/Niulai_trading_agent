#!/usr/bin/env python3
"""Schema plus artifact-resolving semantic validation for report data."""
import argparse, hashlib, json, math, re
from datetime import datetime
from pathlib import Path
HERE=Path(__file__).resolve().parent
SCHEMA_PATH=HERE/'report-data-v1.schema.json'
REPO_ROOT=HERE.parents[1]
CURRENT_REPORT_REL='mentor/runtime/probabilistic-manifold-leverage-20261107/artifacts/candidate-v3/report-data-v3.json'
CURRENT_REPORT_SHA256='218a1ee24f248f66290826ff0316962ce268246958ca9ea14c2b4997da4efac6'
CURRENT_REPORT_BYTES=14275
CURRENT_REF_COUNT=32
SECTIONS={'trust_gate','evidence_states','historical_support','calibration','probability_provenance','robust_worlds','leveraged_paths','position_roadmap','loss_budget','shadow_timeline','audit_appendix'}
STATUSES={'valid','recheck','stale','blocked'}
PLACEHOLDER=re.compile(r'(?:^|[-_])(placeholder|todo|tbd|example)(?:$|[-_])',re.I)
PROPER_SCORE='A proper score is a forecast error measure that rewards honest probabilities.'
BASELINE_COMPARISON='Compare that score separately with a frozen simple baseline under matched cases.'
ESS_LABEL='A dependence-adjusted information approximation, not a count of genuinely independent examples.'
CANDIDATE_ALIAS=re.compile(r'threshold|lambda|floor|cutoff|cut[-_ ]?off|boundary|radius|tolerance|minimum|min(?:imum)?_?count|cap|grid|quantile',re.I)
def need(ok,code):
 if not ok: raise ValueError(code)
def load(path):
 def pairs(items):
  out={}
  for k,v in items: need(k not in out,'DUPLICATE_JSON_KEY');out[k]=v
  return out
 return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=lambda _v:(_ for _ in()).throw(ValueError('NONFINITE')))
def typ(v,t):
 return {'object':isinstance(v,dict),'array':isinstance(v,list),'string':isinstance(v,str),'null':v is None,'boolean':isinstance(v,bool),'integer':isinstance(v,int) and not isinstance(v,bool),'number':isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)}.get(t,False)
def strict_equal(left,right):
 if isinstance(left,bool) or isinstance(right,bool):return type(left) is type(right) and left is right
 if isinstance(left,dict) or isinstance(right,dict):
  return isinstance(left,dict) and isinstance(right,dict) and set(left)==set(right) and all(strict_equal(left[k],right[k]) for k in left)
 if isinstance(left,list) or isinstance(right,list):
  return isinstance(left,list) and isinstance(right,list) and len(left)==len(right) and all(strict_equal(a,b) for a,b in zip(left,right))
 return left==right
def exact_keys(value,keys,code):need(type(value) is dict and set(value)==set(keys),code)
def nested(value,path):
 for key in path:value=value[key]
 return value
def schema_check(v,s,at='$'):
 if 'const'in s:need(strict_equal(v,s['const']),f'SCHEMA_CONST:{at}')
 if 'enum'in s:need(any(strict_equal(v,item) for item in s['enum']),f'SCHEMA_ENUM:{at}')
 if 'type'in s:
  ts=s['type'] if isinstance(s['type'],list) else [s['type']];need(any(typ(v,t) for t in ts),f'SCHEMA_TYPE:{at}')
 if isinstance(v,dict):
  need(all(k in v for k in s.get('required',[])),f'SCHEMA_REQUIRED:{at}');p=s.get('properties',{});pps=s.get('patternProperties',{})
  for k,x in v.items():
   if k in p:schema_check(x,p[k],f'{at}.{k}');continue
   matched=False
   for pattern,sub in pps.items():
    if re.search(pattern,k):schema_check(x,sub,f'{at}.{k}');matched=True
   add=s.get('additionalProperties',True)
   if not matched:need(add is not False,f'SCHEMA_ADDITIONAL:{at}.{k}');schema_check(x,add,f'{at}.{k}') if isinstance(add,dict) else None
 if isinstance(v,list):
  need(len(v)>=s.get('minItems',0),f'SCHEMA_MIN_ITEMS:{at}');need('maxItems' not in s or len(v)<=s['maxItems'],f'SCHEMA_MAX_ITEMS:{at}')
  if s.get('uniqueItems'):need(len({json.dumps(x,sort_keys=True,separators=(',',':')) for x in v})==len(v),f'SCHEMA_UNIQUE:{at}')
  if isinstance(s.get('items'),dict):
   for i,x in enumerate(v):schema_check(x,s['items'],f'{at}[{i}]')
 if isinstance(v,str):
  need(len(v)>=s.get('minLength',0),f'SCHEMA_MIN_LENGTH:{at}')
  if 'pattern'in s:need(re.fullmatch(s['pattern'],v) is not None,f'SCHEMA_PATTERN:{at}')
def point(doc,frag):
 cur=doc
 if not frag:return cur
 need(frag.startswith('/'),'ARTIFACT_POINTER')
 for raw in frag[1:].split('/'):
  key=raw.replace('~1','/').replace('~0','~');need(isinstance(cur,dict) and key in cur,'ARTIFACT_POINTER');cur=cur[key]
 return cur
def resolver(entries,base):
 docs={};meta={};root=base.resolve()
 for e in entries:
  need(e['id'] not in docs,'DUPLICATE_ARTIFACT_ID');need(not PLACEHOLDER.search(e['id']),'PLACEHOLDER_REF');rel=Path(e['path']);need(not rel.is_absolute() and '..' not in rel.parts,'ARTIFACT_PATH');p=(base/rel).resolve();need(p.is_relative_to(root) and p.is_file(),'ARTIFACT_MISSING');need(hashlib.sha256(p.read_bytes()).hexdigest()==e['sha256'],'ARTIFACT_HASH_DRIFT');d=load(p);need(d.get('status')==e['required_status'],'ARTIFACT_STATUS');need(d.get('validity')==e['required_validity'],'ARTIFACT_VALIDITY');docs[e['id']]=(d,p.parent);meta[e['id']]=e
 def resolve(ref,allow_nonusable=True):
  need(isinstance(ref,str) and ref,'ARTIFACT_REF');aid,mark,frag=ref.partition('#');need(aid in docs and not PLACEHOLDER.search(aid),'UNRESOLVED_ARTIFACT_REF');document,origin=docs[aid];t=point(document,frag if mark else '');need(isinstance(t,dict),'ARTIFACT_TARGET');need(t.get('status') in STATUSES,'ARTIFACT_TARGET_STATUS');need(t.get('validity') in {'valid','stale','blocked','invalid'},'ARTIFACT_TARGET_VALIDITY')
  if not allow_nonusable:need(t['status'] in {'valid','recheck'} and t['validity']=='valid','FINAL_NONUSABLE_REF')
  for bound in t.get('bound_artifacts',[]):
   need(set(bound)=={'path','sha256'},'BOUND_ARTIFACT_SHAPE');rel=Path(bound['path']);need(not rel.is_absolute() and '..' not in rel.parts,'BOUND_ARTIFACT_PATH');p=(origin/rel).resolve();need(p.is_relative_to(root) and p.is_file(),'BOUND_ARTIFACT_MISSING');need(hashlib.sha256(p.read_bytes()).hexdigest()==bound['sha256'],'BOUND_ARTIFACT_HASH')
  return t
 return resolve,docs
def canonical_sha(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def validate_extensions(x,resolve,docs):
 registry=docs['source_registry'][0];chart=docs['chart_data'][0]
 claim=x['sections']['evidence_states']['claim_state_authority'];need(strict_equal(claim,registry['model_boundaries']['claim_state_authority']),'CLAIM_STATE_AUTHORITY')
 snapshot=registry['index_snapshot'];hist=x['sections']['historical_support']['index_identity_and_boundaries'];expected={k:snapshot[k] for k in ('official_name','official_symbol','aliases','dated_packet_exact_fields','unverifiable_fields','oneq_proxy_boundary','source_registry_refs')};need(strict_equal(hist,expected),'INDEX_IDENTITY_BOUNDARY_DRIFT')
 need([a['symbol'] for a in hist['aliases']]==['^IXIC','NASDAQCOM'],'INDEX_ALIAS_SPOOF');need(all(hist['oneq_proxy_boundary'][k] is False for k in ('exact_IXIC_identity','exact_IXIC_membership','exact_IXIC_weights','exact_IXIC_valuation','IXIC_NAV','IXIC_reset_benchmark')),'INDEX_PROXY_SPOOF')
 lev=x['sections']['leveraged_paths'];wrapper=resolve(lev['model_boundaries_ref']);boundaries=registry['model_boundaries']
 need(strict_equal(wrapper.get('canonical_object'),boundaries) and strict_equal(boundaries,wrapper.get('visible_object')) and strict_equal(boundaries,wrapper.get('accessible_object')),'MODEL_BOUNDARY_PARITY');need(wrapper.get('canonical_object_sha256')==canonical_sha(boundaries) and wrapper.get('recursive_exact_match') is True,'MODEL_BOUNDARY_HASH')
 need(boundaries.get('targets_merged') is False and boundaries.get('cross_target_probability_transport') is None,'MODEL_MERGING');need(boundaries.get('common_factor_is_causal') is False,'CAUSAL_SPOOF');need(boundaries.get('market_price_equivalent_to_NAV') is False and boundaries.get('market_price_equivalent_to_exact_reset_benchmark') is False,'NAV_SPOOF');need(strict_equal(boundaries.get('probability_and_actions'),{'current_probability':None,'actions':None,'blocked':True}),'PROBABILITY_ACTION_BOUNDARY')
 equation='total_log_return = intercept_log_return + factor_common_log_return + residual_log_return';residual='Mechanical remainder after the aggregate intercept and supplied factor terms; never fundamentals, causal contribution, alpha, or probability.'
 need(lev['decomposition_equation']==equation and lev['residual_definition']==residual,'DECOMPOSITION_BOUNDARY');need(boundaries['decomposition']['equation']==equation and boundaries['decomposition']['residual_definition']==residual,'MODEL_DECOMPOSITION_BOUNDARY')
 rows=registry['fund_decompositions'];need([r['target'] for r in rows]==['SOXL','TQQQ'] and len({r['model_id'] for r in rows})==2,'MODEL_MERGING')
 projected=[{'target':r['target'],'exact_reset_benchmark':r['exact_reset_benchmark'],'investable_proxy_identities':r['investable_proxy_identities'],'return_basis':r['return_basis'],'reconciliation':r['reconciliation'],'source_registry_refs':r['source_registry_refs']} for r in rows];need(strict_equal(lev['decompositions'],projected),'REPORT_DECOMPOSITION_DRIFT')
 expected={'SOXL':('NYSE Semiconductor Index',['SOXX','SMH']),'TQQQ':('Nasdaq-100',['QQQ'])}
 for row in lev['decompositions']:
  target=row['target'];benchmark,proxies=expected[target];need(row['exact_reset_benchmark']==benchmark,'RESET_BENCHMARK_IDENTITY');need([q['symbol'] for q in row['investable_proxy_identities']]==proxies,'PROXY_IDENTITY');need(all('NAV' in q['not_exact_for'][0] or 'NAV' in q['not_exact_for'][1] for q in row['investable_proxy_identities']),'NAV_BOUNDARY')
  r=row['reconciliation'];rhs=math.fsum((r['intercept_log_return'],r['factor_common_log_return'],r['residual_log_return']));need(r['recomputed_total_log_return']==rhs and r['reconciliation_error']==rhs-r['total_log_return'] and math.isclose(rhs,r['total_log_return'],rel_tol=0.0,abs_tol=r['absolute_tolerance']),'RECONCILIATION')
 boolean_paths={
  ('benchmark_and_proxy_identities','QQQ','NAV_equivalence'):False,('benchmark_and_proxy_identities','QQQ','exact_reset_return'):False,
  ('benchmark_and_proxy_identities','SMH','NAV_equivalence'):False,('benchmark_and_proxy_identities','SMH','exact_reset_return'):False,
  ('benchmark_and_proxy_identities','SOXX','NAV_equivalence'):False,('benchmark_and_proxy_identities','SOXX','exact_reset_return'):False,
  ('claim_state_authority','consequential_authority'):False,('claim_state_authority','structural_only'):True,
  ('common_factor_is_causal',):False,('decomposition','targets',0,'reconciliation','reconciles'):True,
  ('decomposition','targets',1,'reconciliation','reconciles'):True,('market_price_equivalent_to_NAV',):False,
  ('market_price_equivalent_to_exact_reset_benchmark',):False,('probability_and_actions','blocked'):True,('targets_merged',):False}
 need(all(type(nested(boundaries,path)) is bool and nested(boundaries,path) is expected for path,expected in boolean_paths.items()),'MODEL_BOUNDARY_BOOLEAN_TYPE')
 exact_keys(boundaries.get('probability_and_actions'),{'current_probability','actions','blocked'},'PROBABILITY_ACTION_SHAPE')
 nulls=registry.get('null_outputs');expected_null_status={'backtest':'not_available','calibration':'not_available','current_probability':'withheld','ood':'inconclusive','prospective':'not_available','support':'inconclusive'}
 exact_keys(nulls,set(expected_null_status),'NULL_OUTPUTS_SHAPE')
 for key,status in expected_null_status.items():
  row=nulls[key];exact_keys(row,{'reason','status','value'},f'NULL_OUTPUT_SHAPE:{key}');need(type(row['reason']) is str and bool(row['reason'].strip()) and type(row['status']) is str and row['status']==status and row['value'] is None,f'NULL_OUTPUT_TYPE_OR_VALUE:{key}')
 policy=registry.get('policy_outputs');action_fields={'recommendation','personalized_position_size','alert_write','automatic_execution'}
 exact_keys(policy,action_fields|{'reason'},'POLICY_OUTPUTS_SHAPE');need(type(policy['reason']) is str and bool(policy['reason'].strip()),'POLICY_OUTPUTS_REASON');need(all(policy[k] is None for k in action_fields),'ACTION_OUTPUT')
 expected_artifacts={'chart_data':('chart-data-v3.json','recheck','valid'),'source_registry':('source-registry-v3.json','recheck','valid')};need(strict_equal({a['id']:[a['path'],a['required_status'],a['required_validity']] for a in x['artifacts']},{k:list(v) for k,v in expected_artifacts.items()}),'AUDIT_ARTIFACT_BINDINGS')
 charts={'trust_gate':'chart_data#/charts/support','historical_support':'chart_data#/charts/support','calibration':'chart_data#/charts/calibration','loss_budget':'chart_data#/charts/loss_budget'}
 for name,row in x['sections'].items():
  need(strict_equal(row['artifact_refs'],[f'source_registry#/projection_targets/{name}']) and row['table_ref']==f'chart_data#/tables/{name}' and row['chart_ref']==charts.get(name),'AUDIT_SECTION_BINDINGS')
 need(strict_equal(x['sections']['calibration']['reliability_evidence'],{'bins_ref':'chart_data#/reliability/bins','counts_ref':'chart_data#/reliability/counts','uncertainty_ref':'chart_data#/reliability/uncertainty','sparse_suppression_ref':'chart_data#/reliability/sparse_suppression'}),'AUDIT_RELIABILITY_BINDINGS')
 need((x['source_ledger_ref'],x['evidence_ledger_ref'],x['palette_receipt_ref'])==('source_registry#/ledger_binding','source_registry#/evidence_binding','chart_data#/palette_receipt'),'AUDIT_GLOBAL_BINDINGS')
def validate(x,base,final=False):
 schema_check(x,load(SCHEMA_PATH));need(set(x['sections'])==SECTIONS,'SECTIONS');datetime.fromisoformat(x['cutoff'].replace('Z','+00:00'));resolve,docs=resolver(x['artifacts'],base);all_refs=[]
 for name,row in x['sections'].items():
  refs=row['artifact_refs']+[row['table_ref']]+([row['chart_ref']] if row['chart_ref'] else []);targets=[resolve(ref,not final) for ref in refs];all_refs+=refs
  if any(t['status']=='blocked' for t in targets):need(row['status']=='blocked','BLOCKED_REMAINS_BLOCKED')
  elif any(t['status']=='stale' for t in targets):need(row['status'] in {'stale','blocked'},'STALE_REMAINS_STALE')
  elif any(t['status']=='recheck' for t in targets):need(row['status'] in {'recheck','stale','blocked'},'RECHECK_PROPAGATION')
  need(all(row[k].strip() for k in ('what_this_says','what_could_be_wrong','what_changes_the_roadmap')),'PLAIN_LANGUAGE')
  if row['status']!='valid':need(row['visible_gap'],'NONVALID_GAP_MUST_BE_VISIBLE')
  if final:need(row['status'] in {'valid','recheck'},'FINAL_SECTION_NONUSABLE')
 hist=x['sections']['historical_support'];labels=hist.get('plain_language_labels',{});need(labels.get('effective_sample_size')==ESS_LABEL,'ESS_LABEL')
 cal=x['sections']['calibration'];labels=cal.get('plain_language_labels',{});proper=labels.get('proper_score_definition','');baseline=labels.get('baseline_comparison','');need(proper==PROPER_SCORE,'PROPER_SCORE_DEFINITION');need(baseline==BASELINE_COMPARISON,'BASELINE_COMPARISON')
 rel=cal.get('reliability_evidence',{});need(set(rel)=={'bins_ref','counts_ref','uncertainty_ref','sparse_suppression_ref'},'RELIABILITY_EVIDENCE')
 bins=resolve(rel['bins_ref'],not final);counts=resolve(rel['counts_ref'],not final);unc=resolve(rel['uncertainty_ref'],not final);sparse=resolve(rel['sparse_suppression_ref'],not final);all_refs+=list(rel.values())
 edges=bins.get('bin_edges');need(bins.get('frozen') is True and isinstance(edges,list) and len(edges)>=2 and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in edges) and edges[0]==0 and edges[-1]==1 and all(a<b for a,b in zip(edges,edges[1:])),'FROZEN_BINS')
 observed=counts.get('counts');denominators=counts.get('denominators');need(counts.get('frozen') is True and isinstance(observed,list) and isinstance(denominators,list) and len(observed)==len(denominators)==len(edges)-1 and all(isinstance(v,int) and not isinstance(v,bool) and v>=0 for v in observed+denominators) and all(o<=d for o,d in zip(observed,denominators)),'FROZEN_COUNTS')
 params_unc=unc.get('parameters');need(unc.get('frozen') is True and isinstance(unc.get('method'),str) and unc['method'].strip() and isinstance(params_unc,dict) and params_unc and all(v is not None and (not isinstance(v,str) or v.strip()) for v in params_unc.values()) and unc.get('parameter_label')=='local_candidate_not_literature_fact','FROZEN_UNCERTAINTY')
 minimum=sparse.get('minimum_count');need(sparse.get('frozen') is True and isinstance(sparse.get('suppression_rule'),str) and sparse['suppression_rule'].strip() and isinstance(minimum,int) and not isinstance(minimum,bool) and minimum>=0 and sparse.get('threshold_label')=='local_candidate_not_literature_fact','SPARSE_SUPPRESSION')
 provenance=x['sections']['probability_provenance'];params=provenance.get('candidate_parameters',[]);need(any(p['name']=='lambda_grid' for p in params),'LAMBDA_GRID');need(any(CANDIDATE_ALIAS.search(p['name']) for p in params),'CANDIDATE_PARAMETERS');need(all(p['label']=='local_candidate_not_literature_fact' and isinstance(p.get('values'),list) and p['values'] for p in params),'CANDIDATE_LABEL')
 floor=x['sections']['shadow_timeline'].get('operational_floor',{});need(floor.get('label')=='local_operational_candidate_not_statistical_validation','SHADOW_FLOOR_LABEL')
 validate_extensions(x,resolve,docs);globals_=[x['source_ledger_ref'],x['evidence_ledger_ref'],x['palette_receipt_ref']];all_refs+=globals_;[resolve(ref,not final) for ref in globals_]
 need(len(set(all_refs))==CURRENT_REF_COUNT,'REFERENCE_COUNT')
 if final:
  need(x['status']=='final' and x['render_receipt_ref'],'FINAL_RENDER_RECEIPT');receipt=resolve(x['render_receipt_ref'],False);all_refs.append(x['render_receipt_ref']);need(receipt.get('kind')=='render_receipt' and receipt.get('section_count')==11 and receipt.get('inspection_status')=='passed','FINAL_RENDER_RECEIPT');need('automatic_trade' in x['prohibited_actions'],'ACTION_BOUNDARY')
 else:need(x['status'] in {'draft','final'},'STATUS')
 return {'status':'valid','mode':'final' if final else 'draft','sections':11,'resolved_refs':len(set(all_refs)),'document_sha256':hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'schema_sha256':hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()}
LEGACY_EXPECTED={
 'invalid-report-missing-explanation.json':'SCHEMA_MIN_LENGTH','invalid-report-unresolved-ref.json':'UNRESOLVED_ARTIFACT_REF','invalid-report-stale-final-ref.json':'FINAL_NONUSABLE_REF','invalid-report-ten-sections.json':'SCHEMA_CONST','invalid-report-placeholder-ref.json':'PLACEHOLDER_REF','invalid-report-schema-extra.json':'SCHEMA_ADDITIONAL','invalid-report-reliability-unfrozen.json':'FROZEN_BINS','invalid-report-labels.json':'PROPER_SCORE_DEFINITION','invalid-report-bin-domain.json':'FROZEN_BINS','invalid-report-count-cardinality.json':'FROZEN_COUNTS','invalid-report-negative-denominator.json':'FROZEN_COUNTS','invalid-report-uncertainty-parameters.json':'FROZEN_UNCERTAINTY','invalid-report-suppression-minimum.json':'SPARSE_SUPPRESSION','invalid-report-proper-score-near-match.json':'PROPER_SCORE_DEFINITION','invalid-report-cutoff-grid-label.json':'SCHEMA_CONST'}
LEGACY_INVALID_FIXTURES=tuple(LEGACY_EXPECTED)
def legacy_document(path):
 doc=load(path);current=load(REPO_ROOT/CURRENT_REPORT_REL)
 for section,fields in {'evidence_states':('claim_state_authority',),'historical_support':('index_identity_and_boundaries',),'leveraged_paths':('model_boundaries_ref','decomposition_equation','residual_definition','decompositions')}.items():
  if section in doc.get('sections',{}):
   for field in fields:doc['sections'][section][field]=current['sections'][section][field]
 return doc
def validate_current():
 p=REPO_ROOT/CURRENT_REPORT_REL;b=p.read_bytes();need(len(b)==CURRENT_REPORT_BYTES,'CURRENT_REPORT_BYTES');need(hashlib.sha256(b).hexdigest()==CURRENT_REPORT_SHA256,'CURRENT_REPORT_SHA256');return validate(load(p),p.parent,False)
def self_test():
 current=validate_current();fd=REPO_ROOT/'mentor/runtime/probabilistic-manifold-leverage-20261107/fixtures';results=[]
 for name,expected in LEGACY_EXPECTED.items():
  try:validate(legacy_document(fd/name),fd,name=='invalid-report-stale-final-ref.json');actual='accepted'
  except Exception as e:actual=str(e)
  passed=actual.startswith(expected);results.append({'fixture':name,'expected':expected,'passed':passed,'actual':actual})
 need(all(r['passed'] for r in results),'SELF_TEST_FAILED');return {'status':'valid','tests':1+len(results),'current':current,'results':results}
def main():
 p=argparse.ArgumentParser();p.add_argument('path',type=Path,nargs='?');p.add_argument('--final',action='store_true');p.add_argument('--self-test',action='store_true');a=p.parse_args()
 try:r=self_test() if a.self_test else validate(load(a.path),a.path.resolve().parent,a.final);c=0
 except Exception as e:r={'status':'rejected','error':str(e)};c=1
 print(json.dumps(r,sort_keys=True));raise SystemExit(c)
if __name__=='__main__':main()
