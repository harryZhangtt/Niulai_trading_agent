from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,os,sqlite3,stat
from pathlib import Path
class VerticalError(ValueError):pass
def req(x,c):
 if not x:raise VerticalError(c)
def canon(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(v):return hashlib.sha256(canon(v)).hexdigest()
PROMPT_SHA='3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b';SOURCE_SHA='26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a';CELLS=('F51DQ-6E3A9C17','F51DQ-B4D208FE');MODEL='claude-fable-5-1'
def _source(path,fault):
 p=Path(path);st=p.lstat();req(stat.S_ISREG(st.st_mode) and not p.is_symlink() and st.st_uid==os.getuid(),'SOURCE_CUSTODY');raw=p.read_bytes();req(hashlib.sha256(raw).hexdigest()==SOURCE_SHA,'SOURCE_HASH');text=json.loads(raw)['prompt_utf8'];data=text.encode('utf-8');req(len(data)==526 and hashlib.sha256(data).hexdigest()==PROMPT_SHA,'PROMPT_BINDING');req(fault!='prompt','INJECTED_PROMPT');return {'path':str(p), 'sha256':PROMPT_SHA,'bytes':526,'source_sha256':SOURCE_SHA,'generation':'schema9-isolated-canary-q1-ab-payload-v1'},data
def _rows(rows,fault):
 req(type(rows) is list and len(rows)==2,'ROW_COUNT');out=[]
 for i,r in enumerate(rows):
  req(set(r)=={'cell_id','provider','model','attempt_id','slot_id','operation_id','prompt_sha256','terminal','raw_ascii'},'ROW_SHAPE');req(r['cell_id']==CELLS[i] and r['provider']=='claude_host' and r['model']==MODEL and r['prompt_sha256']==PROMPT_SHA,'ROW_PROVENANCE');req(r['operation_id']==f"attempt/{r['attempt_id']}/prompt/{PROMPT_SHA}",'ROW_OPERATION');out.append(dict(r))
 req(len({x['attempt_id'] for x in out})==2 and len({x['slot_id'] for x in out})==2,'ROW_DUPLICATE');req(fault!='adapter','INJECTED_ADAPTER');return out
def _snapshot(db,fault):
 p=Path(db);req(not any(Path(str(p)+s).exists() for s in ('-wal','-shm','-journal')),'DB_NOT_QUIESCENT');st=p.stat();raw=p.read_bytes();req(st.st_uid==os.getuid() and stat.S_ISREG(st.st_mode),'DB_CUSTODY');snap=hashlib.sha256(raw).hexdigest();con=sqlite3.connect('file:'+str(p)+'?mode=ro&immutable=1',uri=True);con.execute('BEGIN');count=con.execute('select count(*) from provider_results').fetchone()[0];con.commit();con.close();req(count==2,'DB_ROWS');req(fault!='bridge','INJECTED_BRIDGE');return {'source_sha256':snap,'snapshot_sha256':snap,'bytes':len(raw)}
def _commit(root,rows,fault):
 root=Path(root);root.mkdir(mode=0o700);cells=[]
 try:
  for i,r in enumerate(rows):
   d=root/CELLS[i];d.mkdir(mode=0o700);raw=r['raw_ascii'].encode('ascii');rp=d/(CELLS[i]+'.raw');bp=d/(CELLS[i]+'.bundle.json');rp.write_bytes(raw);rp.chmod(0o600);cell={'cell_id':CELLS[i],'dq_enabled':bool(i),'model':MODEL,'terminal':r['terminal'],'denominator_included':True,'publication_attempts':0,'raw_sha256':hashlib.sha256(raw).hexdigest()};bundle={'version':2,'prompt_sha256':PROMPT_SHA,'cell':cell,'raw_ascii':r['raw_ascii']};bp.write_bytes(canon(bundle));bp.chmod(0o600);cells.append(cell)
  req(fault!='integration','INJECTED_INTEGRATION');return {'cells':cells,'denominator_count':2,'publication_attempts':0,'countable':False,'bundle_sha256':[hashlib.sha256((root/c/(c+'.bundle.json')).read_bytes()).hexdigest() for c in CELLS]}
 except:raise
def execute(*,source_path,closed_db,output_root,rows,evaluation,not_before,scheduled,deadline,fault=None):
 for v in (evaluation,not_before,scheduled,deadline):req(type(v) is datetime and v.tzinfo and v.utcoffset().total_seconds()==0 and v.microsecond==0,'TIME')
 req(evaluation<=not_before<=scheduled<=deadline and evaluation<scheduled and (deadline-not_before).total_seconds()<=300,'TIME_BOUNDS');prompt,prompt_bytes=_source(source_path,fault);validated=_rows(rows,fault);snapshot=_snapshot(closed_db,fault);ab=_commit(output_root,validated,fault);schedule={'kind':'once','at':scheduled.strftime('%Y-%m-%dT%H:%M:%SZ'),'grace_seconds':int((deadline-scheduled).total_seconds())};req(fault!='materialization','INJECTED_MATERIALIZATION');proposal={'classification':'DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE','activation':False,'apply':False,'jobs':[{'id':f'fable-v2-{i}','enabled':False,'schedule':schedule,'model':MODEL,'provider':'claude_host','prompt_sha256':PROMPT_SHA} for i in range(2)]};req(fault!='proposal','INJECTED_PROPOSAL');config={'schema_version':2,'tick_seconds':5,'heartbeat_seconds':10,'stale_seconds':60,'max_workers':1,'retry':{'version':2,'max_attempts':1,'base_delay_seconds':1,'max_delay_seconds':1,'deadline_seconds':schedule['grace_seconds']},'model_profiles':{'fable-v2':{'provider':'claude_host','model':MODEL,'effort':'low','timeout_seconds':300,'auth_home':'.job-runtime/config/fable-v2-auth','max_budget_usd':0.02}},'allocation_files':['.job-runtime/config/fable-v2-allocation.json'],'source_paths':[]};allocation={'schema_version':2,'jobs':[{'id':j['id'],'enabled':False,'schedule':schedule,'model_profile':'fable-v2','prompt_file':'.job-runtime/config/prompts/fable-v2.txt','replay_contract':{'version':1,'effect':'none','automatic_phases':['not_started'],'slot_operation_scope':f"fable/v2/{i}",'reconciliation_adapter':None}} for i,j in enumerate(proposal['jobs'])]};req(fault!='config','INJECTED_CONFIG');stages=[prompt,snapshot,ab,proposal,config,allocation];digests=[]
 for x in stages:digests.append(sha({'parent':digests[-1] if digests else 'ACTUAL_PROMPT_ROOT','value':x}))
 return {'version':1,'activation':False,'effects':{'provider':0,'network':0,'service':0,'email':0,'publication':0},'prompt':prompt,'prompt_bytes':prompt_bytes,'snapshot':snapshot,'ab':ab,'proposal':proposal,'config':config,'allocation':allocation,'budget':{'currency':'USD','per_arm_max_budget_usd':0.02,'aggregate_ceiling_usd':0.04,'status':'PROPOSED_UNAPPROVED','prompt_utf8_bytes':526,'token_evidence':'UNMEASURED','billed_authority':False},'transition_digests':digests,'final_sha256':digests[-1]}
