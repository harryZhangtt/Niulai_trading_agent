import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { InformationYieldV5Bridge, informationYieldV5Options, start } from '../server.mjs';

async function freePort(){const server=http.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
const names=['confirmation_cohort','richness_mean','richness_positive_cases','depth_mean','depth_positive_cases','case_delta_floor','issuer_loo','precision_delta','arm_wall_limit','case_wall_ratio','aggregate_wall_ratio','complete_trace_ratio','complete_pooled_review','zero_critical_unsupported','lineage','execution_custody','zero_hard_failures','unknown_semantics'];
const ids=Array.from({length:6},(_,index)=>`case-${index+1}`);const populations={C:ids,D:[],E:ids,N:[]};
const obs=(value,unit)=>({state:'known',value,unit});const metric=unit=>({mean:obs(1,unit),median:obs(1,unit),minimum:obs(1,unit),maximum:obs(1,unit),range:obs(0,unit),total:obs(6,unit),denominator:6,wins:6,ties:0,losses:0,leave_one_issuer_out:[]});
const arm={richness:obs(2,'canonical_units'),depth:obs(2,'field_state_steps'),precision:obs(1,'ratio'),wall_seconds:obs(10,'seconds'),trace:{complete:1,credited:1,unjudged:0}};
const rows=ids.map((case_id,index)=>({case_id,issuer_id:`ISSUER-${index+1}`,window_id:`2026Q${index+1}`,evidence_level:'confirmation',split:'untouched',arm_order:index<3?['B0','F']:['F','B0'],request_sha256:'a'.repeat(64),fact_sha256:String(index+1).repeat(64).slice(0,64),delta_r:obs(1,'canonical_units'),delta_d:obs(1,'field_state_steps'),arms:{B0:{...arm,richness:obs(1,'canonical_units'),depth:obs(1,'field_state_steps')},F:arm},hard_failure_codes:[]}));
const gates=names.map((name,index)=>({ordinal:index+1,name,population:index<8?'C':'E',decisive:index>=11&&index<=16,population_case_ids:ids,status:'pass',observed:1,threshold:1,numerator:null,denominator:null,case_results:[],reason_codes:[]}));
const packet={wire_version:'information-yield-wire-5',publication:'information-yield-v5',view:'summary',evaluation_id:'eval-1',index_sha256:'a'.repeat(64),custody_sha256:'b'.repeat(64),result_sha256:'c'.repeat(64),verdict:'pass',counts:{planned:6,confirmation:6,development:0},evidence:{context_sha256:'d'.repeat(64),fact_set_sha256:'e'.repeat(64),policy_sha256:'b25d0e9dd7fd5d1db6f95c1114a179d0963d2bc55b7ef839227364e300df887f',gate_authority_sha256:'558c4add60096842836aa67472731785f869897bc662dcd873b740b08de16878',source_closure_sha256:'2'.repeat(64),claim_limits:['vector_only_no_scalar'],same_user_trust:'integrity_and_nominal_issuance_only',same_user_limitations:['no_malicious_same_user_resistance','no_remote_attestation','registry_and_self_hash_do_not_elevate_trust']},outcomes:{richness:metric('canonical_units'),depth:metric('field_state_steps')},populations,policy_gates:gates,hard_failures:[],cases:rows,selection:{case_id:null,arm:null},case:null,selected_arm:null,projection_state:'fresh',read_only:true};

test('v5 query accepts identities only and rejects aliases',()=>{
 for(const query of ['', 'evaluation=../../auth', 'evaluation=e&arm=F', 'evaluation=e&path=x', 'evaluation=e&result=x', 'evaluation=e&registry=x', 'evaluation=e&run=x']) assert.throws(()=>informationYieldV5Options(new URL(`http://x/api/information-yield/v5?${query}`)),{code:'INVALID_INFORMATION_YIELD_V5_QUERY'});
 assert.deepEqual(informationYieldV5Options(new URL('http://x/api/information-yield/v5?evaluation=e&case=c&arm=F')),{evaluation:'e',caseId:'c',arm:'F'});
});

test('v5 is disabled unless exact flag and never invokes its loader',async()=>{
 let calls=0;const bridge=new InformationYieldV5Bridge({enabled:false,loader:async()=>{calls++;return packet;}});
 await assert.rejects(bridge.get({evaluation:'eval-1',caseId:null,arm:null}),{code:'INFORMATION_YIELD_V5_DISABLED'});assert.equal(calls,0);bridge.close();
});

test('v5 coalesces exact identities, retains transient stale, but not authority conflicts',async()=>{
 let calls=0,mode='ok';const options={evaluation:'eval-1',caseId:null,arm:null};
 const bridge=new InformationYieldV5Bridge({enabled:true,ttl:0,loader:async()=>{calls++;await new Promise(resolve=>setTimeout(resolve,10));if(mode==='transient')throw Error('PRIVATE');if(mode==='conflict')throw Object.assign(Error('PRIVATE'),{code:'EIY_PROJECTION_V5_AUTHORITY_MISMATCH'});return packet;}});
 const values=await Promise.all(Array.from({length:20},()=>bridge.get(options)));assert.equal(calls,1);assert.ok(values.every(value=>value.wire_version==='information-yield-wire-5'));
 mode='transient';assert.equal((await bridge.get(options,{force:true})).projection_state,'stale');
 mode='conflict';await assert.rejects(bridge.get(options,{force:true}),{code:'EIY_PROJECTION_V5_AUTHORITY_MISMATCH'});bridge.close();
});

test('v5 bridge rejects old wire, gate, population and selector mismatches',async()=>{
 const invalid=[];invalid.push({...packet,wire_version:'information-yield-wire-4'});
 const reordered=structuredClone(packet);reordered.policy_gates.reverse();invalid.push(reordered);
 const population=structuredClone(packet);population.policy_gates[0].population_case_ids=['case-2'];invalid.push(population);
 const decisive=structuredClone(packet);decisive.policy_gates[11].decisive=false;invalid.push(decisive);
 const verdict=structuredClone(packet);verdict.verdict='reject';invalid.push(verdict);
 const authority=structuredClone(packet);authority.evidence.policy_sha256='0'.repeat(64);invalid.push(authority);
 for(const value of invalid){const bridge=new InformationYieldV5Bridge({enabled:true,loader:async()=>value});await assert.rejects(bridge.get({evaluation:'eval-1',caseId:null,arm:null}),{code:'EIY_PROJECTION_V5_IDENTITY_CONFLICT'});bridge.close();}
});

test('v5 endpoint exposes fixed sanitized codes and remains read-only',async()=>{
 const port=await freePort();const informationYieldV5=new InformationYieldV5Bridge({enabled:true,loader:async options=>{if(options.evaluation==='missing')throw Object.assign(Error('PRIVATE'),{code:'EIY_PROJECTION_V5_NOT_FOUND'});if(options.evaluation==='conflict')throw Object.assign(Error('PRIVATE'),{code:'EIY_PROJECTION_V5_POLICY_MISMATCH'});if(options.evaluation==='fail')throw Error('PRIVATE');return {...packet,evaluation_id:options.evaluation};}});
 const service=await start({port,informationYieldV5,viteFactory:async()=>({middlewares:(_request,response)=>response.end('fixture'),close:async()=>{}})});
 try{const origin=`http://127.0.0.1:${port}`;let response=await fetch(`${origin}/api/information-yield/v5?evaluation=eval-1`);assert.equal(response.status,200);assert.equal((await response.json()).wire_version,'information-yield-wire-5');
  for(const [id,status,code] of [['missing',404,'INFORMATION_YIELD_V5_NOT_FOUND'],['conflict',409,'INFORMATION_YIELD_V5_CONFLICT'],['fail',503,'INFORMATION_YIELD_V5_UNAVAILABLE']]){response=await fetch(`${origin}/api/information-yield/v5?evaluation=${id}`);assert.equal(response.status,status);const text=await response.text();assert.ok(text.includes(code));assert.ok(!text.includes('PRIVATE'));}
  response=await fetch(`${origin}/api/information-yield/v5?evaluation=e&path=.env`);assert.equal(response.status,400);assert.equal((await response.json()).error.code,'INVALID_INFORMATION_YIELD_V5_QUERY');
  response=await fetch(`${origin}/api/information-yield/v5?evaluation=e`,{method:'POST'});assert.equal(response.status,405);
 }finally{await service.close();}
});

test('default endpoint reports disabled with no fallback',async()=>{
 const port=await freePort();const service=await start({port,informationYieldV5:new InformationYieldV5Bridge({enabled:false,loader:async()=>packet}),viteFactory:async()=>({middlewares:(_request,response)=>response.end('fixture'),close:async()=>{}})});
 try{const response=await fetch(`http://127.0.0.1:${port}/api/information-yield/v5?evaluation=eval-1`);assert.equal(response.status,503);assert.equal((await response.json()).error.code,'INFORMATION_YIELD_V5_DISABLED');}finally{await service.close();}
});
