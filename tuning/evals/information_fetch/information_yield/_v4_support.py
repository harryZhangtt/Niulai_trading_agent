from copy import deepcopy
from investment.research.acquisition_eiy_checker import check_eiy_evaluation_v4,FreshEiyFact,FreshEiyEvaluation,_FRESH_TOKEN,_EVALUATION_TOKEN
from investment.research.tests.test_acquisition_eiy_v3 import EiyV3Fixture
from shared.research_sources.artifacts import ROOT,digest
COMMON=("metric_policy_ref","case_roster_ref","allocation_ref","baseline_ref","reference_set_ref","required_fields_ref","freshness_targets_ref","financial_element_roster_ref","source_closure_ref")
def build_batch(testcase,*,confirmation=6,development=0,shuffle=False):
 rows=[];total=confirmation+development;confirmation_seen=0
 for index in range(1,total+1):
  is_development=index<=development
  if is_development:level,split,order='development','development',['B0','F']
  else:
   level,split='confirmation','untouched';order=['B0','F'] if confirmation_seen<3 else ['F','B0'];confirmation_seen+=1
  rows.append({'case_id':f'case-{index}','issuer_id':f'ISSUER-{index}','subject':'ACME','window_id':f'2026Q{index}','cutoff':'2026-01-01T00:00:00Z','evidence_level':level,'split':split,'arm_order':order})
 ids=[r['case_id'] for r in rows];fixtures=[]
 for index,row in enumerate(rows,1):
  fixtures.append(EiyV3Fixture(testcase,case_index=index,issuer=row['issuer_id'],all_case_ids=ids,all_case_rows=rows,arm_order=row['arm_order'],evidence_level=row['evidence_level'],split=row['split'],disposition_by_arm={'B0':'reject','F':'approve'}))
 first=fixtures[0]
 for fixture in fixtures:
  for name in COMMON:fixture.values[name]=first.values[name]
  fixture.rebuild_request()
 refs=[f.request_ref for f in fixtures]
 if shuffle:refs=list(reversed(refs))
 custody_ref,manifest_ref=first.batch(fixtures,refs)
 evaluation=check_eiy_evaluation_v4(custody_ref,read_ref=first.read_ref,workspace_root=ROOT)
 return fixtures,evaluation,custody_ref,manifest_ref
def mutate_evaluation(evaluation,mutator):
 data=evaluation.to_audit_mapping();mutator(data)
 for fact in data['facts']:
  fact['fact_sha256']=digest({k:v for k,v in fact.items() if k!='fact_sha256'})
 fact_by={f['case_id']:f for f in data['facts']}
 for row in data['context']['planned_cases']:row['fact_sha256']=fact_by[row['case_id']]['fact_sha256']
 core={k:v for k,v in data['context'].items() if k not in {'context_sha256','fact_set_sha256','fact_bindings'}};context_sha=digest(core)
 bindings=[{'case_id':row['case_id'],'request_sha256':row['request_sha256'],'fact_sha256':row['fact_sha256'],'context_sha256':context_sha} for row in data['context']['planned_cases']]
 data['context']['context_sha256']=context_sha;data['context']['fact_bindings']=bindings;data['context']['fact_set_sha256']=digest(bindings)
 facts=[FreshEiyFact(f,_FRESH_TOKEN) for f in data['facts']]
 return FreshEiyEvaluation(data['context'],facts,data['policy'],evaluation.input_paths,_EVALUATION_TOKEN)
