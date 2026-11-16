import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { InformationYieldBridge, informationYieldOptions, start } from '../server.mjs';

async function freePort() { const s=http.createServer(); await new Promise(r=>s.listen(0,'127.0.0.1',r)); const p=s.address().port; await new Promise(r=>s.close(r)); return p; }
const B0={richness:{state:'known',value:1,unit:'canonical_units'}};const F={richness:{state:'known',value:2,unit:'canonical_units'}};const caseA={case_id:'case-A',arms:{B0,F},hard_failures:[]};
const packet={schema_version:1,view:'summary',evaluation_id:'eval-1',read_only:true,projection_state:'fresh',verdict:'inconclusive',outcomes:{richness:{},depth:{}},policy_gates:[],hard_failures:[],cases:[],selection:{case_id:null,arm:null,run:null,source:null},case:null,selected_arm:null};

test('information-yield selectors are exact and hierarchical',()=>{
  for(const q of ['', 'evaluation=../../auth', 'evaluation=e&arm=F', 'evaluation=e&case=c&run=r', 'evaluation=e&path=.env']) assert.throws(()=>informationYieldOptions(new URL('http://x/api/information-yield?'+q)),{code:'INVALID_INFORMATION_YIELD_QUERY'});
  assert.deepEqual(informationYieldOptions(new URL('http://x/api/information-yield?evaluation=e&case=c&arm=F&run=r&source=s')),{evaluation:'e',caseId:'c',arm:'F',run:'r',source:'s'});
});

test('bridge coalesces and retains stale data only for exact identity',async()=>{
 let calls=0,fail=false; const bridge=new InformationYieldBridge({ttl:0,loader:async options=>{calls++;await new Promise(r=>setTimeout(r,10));if(fail)throw Error('PRIVATE');return {...packet,evaluation_id:options.evaluation};}});
 const options={evaluation:'eval-1',caseId:null,arm:null,run:null,source:null}; const rows=await Promise.all(Array.from({length:20},()=>bridge.get(options))); assert.equal(calls,1);assert.ok(rows.every(v=>v.evaluation_id==='eval-1'));
 fail=true; const stale=await bridge.get(options,{force:true});assert.equal(stale.projection_state,'stale');await assert.rejects(bridge.get({...options,evaluation:'eval-2'}));bridge.close();
});

test('case and arm response identity cannot cross selectors or stale cache',async()=>{
 let wrong=false; const options={evaluation:'eval-1',caseId:'case-A',arm:'F',run:null,source:null};
 const bridge=new InformationYieldBridge({ttl:0,loader:async()=>wrong?{...packet,view:'detail',cases:[],selection:{case_id:'case-A',arm:'F',run:null,source:null},case:caseA,selected_arm:B0}:{...packet,view:'detail',cases:[],selection:{case_id:'case-A',arm:'F',run:null,source:null},case:caseA,selected_arm:F}});
 await bridge.get(options); wrong=true;
 await assert.rejects(bridge.get(options,{force:true}),{code:'INFORMATION_YIELD_IDENTITY_CONFLICT'});
 bridge.close();
});

test('hard-failure summary exactly reconciles visible cases and verdict',async()=>{
 const failure={case_id:'case-A',code:'TRACE_FAILURE',chain_ids:['a'.repeat(64)]}; const failedCase={...caseA,hard_failures:[{code:'TRACE_FAILURE',chain_ids:['a'.repeat(64)]}]};
 for(const invalid of [{...packet,verdict:'pass',cases:[failedCase],hard_failures:[]},{...packet,verdict:'reject',cases:[failedCase],hard_failures:[failure,{...failure,code:'SOURCE_MISMATCH'}]},{...packet,verdict:'reject',cases:[failedCase],hard_failures:[failure,failure]}]){
  const bridge=new InformationYieldBridge({loader:async()=>invalid});await assert.rejects(bridge.get({evaluation:'eval-1',caseId:null,arm:null,run:null,source:null}),{code:'INFORMATION_YIELD_IDENTITY_CONFLICT'});bridge.close();
 }
});

test('endpoint is read-only, exact, and sanitizes statuses',async()=>{
 const port=await freePort(); const informationYield=new InformationYieldBridge({loader:async options=>{if(options.evaluation==='missing')throw Object.assign(Error('PRIVATE'),{code:'EIY_PROJECTION_NOT_FOUND'});if(options.evaluation==='conflict')throw Object.assign(Error('PRIVATE'),{code:'EIY_PROJECTION_IDENTITY_CONFLICT'});if(options.evaluation==='fail')throw Error('PRIVATE');return {...packet,evaluation_id:options.evaluation};}});
 const service=await start({port,informationYield,viteFactory:async()=>({middlewares:(_q,r)=>r.end('fixture'),close:async()=>{}})});
 try { const origin='http://127.0.0.1:'+port;
  let r=await fetch(origin+'/api/information-yield?evaluation=eval-1');assert.equal(r.status,200);assert.equal((await r.json()).evaluation_id,'eval-1');
  for(const [id,status] of [['missing',404],['conflict',409],['fail',503]]){r=await fetch(origin+'/api/information-yield?evaluation='+id);assert.equal(r.status,status);assert.ok(!(await r.text()).includes('PRIVATE'));}
  r=await fetch(origin+'/api/information-yield?evaluation=e&arm=F');assert.equal(r.status,400);
  r=await fetch(origin+'/api/information-yield?evaluation=e',{method:'POST'});assert.equal(r.status,405);
 } finally { await service.close(); }
});
