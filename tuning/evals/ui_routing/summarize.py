"""Read closed authentic benchmark results; no model calls or state changes."""
import json,statistics
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,read,save,require
from tuning.evals.evidence_runtime import contracts
p=SOURCE_STATE/'runtime/ui-router-intent-20261102-v1';r=json.loads((p/'record.json').read_text());c=contracts.validate(r['contract_ref']);summary={}
for arm in ['baseline','candidate']:
 attempts=[(k,a) for k,a in r['attempts'].items() if k.startswith(arm+'-')];require(len(attempts)==2 and all(a['phase']=='closed' for _,a in attempts),'ROUTER_ATTEMPTS_INCOMPLETE')
 data=[]
 for name,a in attempts:
  result=read(a['grade_ref']);data.append({'attempt':name,'correct_cases':sum(x['passed'] for x in result['cases']),'critical_failures':[x['id'] for x in result['cases'] if not x['passed'] and x['critical']],'failed_cases':[x['id'] for x in result['cases'] if not x['passed']],'usage':a['usage'],'elapsed_seconds':a['elapsed_seconds'],'thread_id':a['thread_id'],'grade_ref':a['grade_ref'],'optional_skills_loaded':sum(x['metrics']['optional_skills_loaded'] for x in result['cases'])})
 summary[arm]={'attempts':data,'correct_observations':sum(x['correct_cases'] for x in data),'distinct_requests':len(c['cases']),'critical_distinct_requests':sum(x['critical'] for x in c['cases']),'mean_input_tokens':statistics.mean(x['usage']['input_tokens'] for x in data),'mean_output_tokens':statistics.mean(x['usage']['output_tokens'] for x in data),'mean_total_tokens':statistics.mean(x['usage']['input_tokens']+x['usage']['output_tokens'] for x in data),'mean_elapsed_seconds':statistics.mean(x['elapsed_seconds'] for x in data)}
ref=save(p/'reports',{'kind':'ui_intent_router_development_comparison','contract_ref':r['contract_ref'],'arms':summary,'input_token_reduction_fraction':1-summary['candidate']['mean_input_tokens']/summary['baseline']['mean_input_tokens'],'total_token_reduction_fraction':1-summary['candidate']['mean_total_tokens']/summary['baseline']['mean_total_tokens'],'local_measurement_ref':json.loads((p/'measurement-ref.json').read_text()),'allowed_claim':'No observed intent regression on30developmentrequests/twoorders; zeroLLMdeterministicresolver; compactpolicyreducesobservedbatchinputabout5percent. Notuniversalaccuracy orend-to-endUIquality/costgain.','limitations':r['limitations']})
(p/'report-ref.json').write_text(json.dumps(ref,indent=2)+'\n');print(json.dumps({'ref':ref,'summary':summary},indent=2))
