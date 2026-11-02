"""Observed local resolver timings and explicitly named tokenizer proxies."""
from pathlib import Path
import hashlib,json,os,statistics,subprocess,sys,time
from shared.research_sources.artifacts import ROOT,SOURCE_STATE,save
from ui.route import read_catalog,resolve
os.environ.setdefault('TIKTOKEN_CACHE_DIR',str(ROOT/'tuning/runtime/tokenizer-cache'))
import tiktoken
encoding=tiktoken.get_encoding('o200k_base')
study=SOURCE_STATE/'runtime/ui-router-intent-20261102-v1'
plans={'backend':['backend-only'],'single-layout':['layout'],'hardening':['hardening'],
       'react-race':['async-state','react-performance','browser'],
       'cinematic-landing':['landing-page','cinematic','gsap-react','gsap-scrolltrigger','browser'],
       'blocked-pencil':['pencil-design']}
rows={}
for label,decisions in plans.items():
 timings=[]
 for _ in range(100):
  t=time.perf_counter_ns();result=resolve(decisions=decisions);timings.append((time.perf_counter_ns()-t)/1e6)
 selected=[row['skill'] for row in result['selected']];text='\n'.join((ROOT/'ui/skills'/name/'SKILL.md').read_text() for name in selected)
 rows[label]={'iterations':100,'p50_ms':statistics.median(timings),'p95_ms':sorted(timings)[94],'max_ms':max(timings),'status':result['status'],'selected':selected,'selected_entrypoint_tokens_proxy':len(encoding.encode(text)),'llm_calls':0,'llm_tokens':0}
cold=[]
for _ in range(20):
 t=time.perf_counter_ns();p=subprocess.run([sys.executable,'-B',str(ROOT/'ui/route.py'),'--decision','layout'],capture_output=True,text=True,check=True);cold.append((time.perf_counter_ns()-t)/1e6)
catalog=read_catalog();alltext='\n'.join((ROOT/'ui/skills'/name/'SKILL.md').read_text() for name in catalog['skills']);policy=(ROOT/'ui/AGENTS.md').read_text()+'\n'+(ROOT/'ui/ROUTING.md').read_text();card=(ROOT/'ui/portable/ROUTING-CARD.md').read_text();record=json.loads((study/'record.json').read_text())
from shared.research_sources.artifacts import read
result={'kind':'ui_router_local_latency_and_token_proxy','tokenizer':'tiktoken0.12.0/o200k_base','scope':'warm in-process 100 calls/route and20fresh PythonCLIprocesses on this host, not model latency/general throughput; skill costs fullentrypoint proxies excluding further references.','routes':rows,'fresh_cli_layout':{'calls':20,'p50_ms':statistics.median(cold),'p95_ms':sorted(cold)[18]},'instruction_tokens_proxy':{'incumbent_startup_policy_router':len(encoding.encode(policy)),'incumbent_benchmark_policy_registry':len(encoding.encode(read(record['policies']['baseline'])['text'])),'compact_card':len(encoding.encode(card)),'all22_entrypoints_hypothetical_load':len(encoding.encode(alltext))},'important':'All22fullbodiesisahypotheticalloadbaseline,NOTcurrentprogressiveloadingbehavior. Actualproviderinput/output/cachedtokenscomeonlyfrommodelreceipts;nocostdollarsinferred.'}
ref=save(study/'measurements',result);(study/'measurement-ref.json').write_text(json.dumps(ref,indent=2)+'\n');print(json.dumps({'ref':ref,'measurements':result},indent=2))
