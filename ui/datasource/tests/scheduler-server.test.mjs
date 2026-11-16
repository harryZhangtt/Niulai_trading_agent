import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { SchedulerBridge, schedulerOptions, start } from '../server.mjs';

async function freePort() {
  const s = http.createServer(); await new Promise(resolve => s.listen(0, '127.0.0.1', resolve));
  const port = s.address().port; await new Promise(resolve => s.close(resolve)); return port;
}
const resilienceFixtureRaw=readFileSync(new URL('../src/scheduler-resilience-mvp/pythonProjectionFixture.json',import.meta.url));
assert.equal(createHash('sha256').update(resilienceFixtureRaw).digest('hex'),'63656d1ab0f4b074a568ca338dc51b422a18b4d26f365152fe21d31020bfb690');
const resilience=JSON.parse(resilienceFixtureRaw.toString('utf8'));
const packet = {schema_version:1,scope:'local_codex_scheduler',read_only:true,status:'ok',generated_at:resilience.generated_at,health:{state:'healthy',heartbeat_at:null,watchdog_healthy:true},provider_safety:{status:'not_applicable',jobs:0,available_jobs:0,unknown_fences:0,delayed_jobs:0,queue_depth:0,circuits:{closed:0,open:0,half_open:0,unavailable:0}},jobs:[],warnings:[]};
const standard={id:'job',title:'Job',description:'Read only',enabled:true,schedule:{kind:'interval',seconds:60},next_run_at:null,replay_safe:true,model:'m',effort:'low',delivery:{mode:'none',next_send_at:null,note:'none'},history:[],outputs:[],prompt_custody:{status:'legacy_unbound',attempts_bound:0}};
const providerSafety={status:'available',provider:'codex_cli',latest_attempt:{phase:'terminal',submission:'definitely_submitted',terminal_proof:'verified',status:'succeeded',failure:'none'},delayed_until:null,delay_source:null,retry_reason:'PROVIDER_SUCCEEDED',replay_authorization:'not_applicable',circuit:{state:'closed',open_until:null,probe_until:null,probe_eligible:false},unknown_fence:false,queue:{depth:0,oldest_delayed_at:null}};
const delayedProviderSafety={...providerSafety,latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:'2026-11-08T00:00:00Z',delay_source:'backoff',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',queue:{depth:1,oldest_delayed_at:'2026-11-08T00:00:00Z'}};
const completeStandard={...standard,provider_safety:providerSafety};
const delayedStandard={...standard,id:'delayed-job',provider_safety:delayedProviderSafety};
const mentor={...standard,id:'mentor',prompt_custody:undefined,job_type:'mentor',mentor:{work_order:{id:'w',logical_session_id:'w',starts_at:'2026-11-07T00:00:00Z',ends_at:'2026-11-07T00:01:00Z',window_state:'expired',acceptance_criteria_total:1,required_event_kinds:[]},scheduler:{status:'failed',code:'FAILED',attempts:1,dispatch:'definitely_not_dispatched'},session:{status:'failed',revision:0},progress:{cycles:{used:0,limit:1},provider_threads:{used:0,limit:1},variants:{used:0,limit:1},interventions:{used:0,limit:0},reused_evaluations:{used:0,limit:0},pending_effects:0},safeguards:{provider_thread_mode:'ephemeral_threads',record_all_variants:true,worker_holdout_access:false,require_no_pending_effects:true,configured_replay_safe:true,replay_authorization:'not_authorized'},gates:{future_wake:'failed',profile_binding:'failed',stop_propagation:'failed',model_turn:'failed',journal_cycle_postcondition:'failed',no_duplicate_dispatch:'verified'},evaluation:{attempt_ledger_preserved:true,baseline:'pending',ablation:'pending',holdout:'pending',promotion:'failed'},resilience,runtime_acceptance:{execution:'failed',acceptance:'failed',model_turn:'not_started',email:'pending'},recovery_timeline:[]}};
delete mentor.prompt_custody;
const completeMentor={...mentor,provider_safety:providerSafety};
const completePacket=job=>({...packet,provider_safety:{status:'available',jobs:1,available_jobs:1,unknown_fences:0,delayed_jobs:job.provider_safety.delayed_until===null?0:1,queue_depth:job.provider_safety.queue.depth,circuits:{closed:1,open:0,half_open:0,unavailable:0}},jobs:[job]});

test('scheduler queries accept identities only; paths, unexpected keys and output without job are rejected', () => {
  for (const search of ['job=../../auth','output='+'a'.repeat(64),'job=x&output=bad','file=.env']) {
    assert.throws(()=>schedulerOptions(new URL('http://localhost/api/scheduler?'+search)),{code:'INVALID_SCHEDULER_QUERY'});
  }
  assert.deepEqual(schedulerOptions(new URL('http://localhost/api/scheduler?job=a.b&output='+'a'.repeat(64))),{job:'a.b',output:'a'.repeat(64)});
});

test('complete standard provider-safety and mentor DTOs cross the server boundary unchanged', async () => {
  for(const job of [completeStandard,delayedStandard,completeMentor]){
    const expected=completePacket(job);
    const bridge=new SchedulerBridge({loader:async()=>expected});
    const actual=await bridge.get({job:null,output:null});
    assert.equal(actual,expected);
    assert.equal(actual.jobs[0],job);
    assert.deepEqual(actual,expected);
    bridge.close();
  }
});

test('contextual scheduler fields reject neutral wrappers before stale fallback', async () => {
  const valid=completePacket(completeStandard);let next=valid;
  const bridge=new SchedulerBridge({ttl:0,loader:async()=>next});
  await bridge.get({job:null,output:null});
  const attacks=[
    completePacket({...completeStandard,provider_safety:{...providerSafety,replay_authorization:{value:'not_applicable'}}}),
    completePacket({...completeStandard,provider_safety:{...providerSafety,delay_source:[]}}),
    completePacket({...completeMentor,mentor:{...completeMentor.mentor,safeguards:{...completeMentor.mentor.safeguards,replay_authorization:{value:'not_authorized'}}}}),
    completePacket({...completeMentor,mentor:{...completeMentor.mentor,gates:{...completeMentor.mentor.gates,profile_binding:['failed']}}}),
  ];
  for(const attack of attacks){
    next=attack;
    await assert.rejects(bridge.get({job:null,output:null},{force:true}),{code:'SCHEDULER_PACKET_REJECTED'});
  }
  assert.equal(bridge.cache.size,1);
  assert.equal(bridge.cache.values().next().value.data,valid);
  bridge.close();
});

test('mentor resilience accepts only the frozen exact nested contract', async () => {
  const valid=completePacket(completeMentor);let next=valid;
  const bridge=new SchedulerBridge({ttl:0,loader:async()=>next});
  const accepted=await bridge.get({job:null,output:null});
  assert.deepEqual(accepted.jobs[0].mentor.resilience,resilience);
  const mutate=change=>{const value=structuredClone(valid);change(value.jobs[0].mentor.resilience);return value;};
  const generated=value=>{const packetValue=structuredClone(valid);packetValue.generated_at=value;packetValue.jobs[0].mentor.resilience.generated_at=value;return packetValue;};
  const future='2026-11-05T02:01:00+00:00';
  const validLatest={phase:'terminal',status:'succeeded'};
  const attacks=[
    mutate(value=>{value.extra='x';}),
    mutate(value=>{value.private_note='x';}),
    mutate(value=>{value.scheduler.extra='x';}),
    mutate(value=>{value.scheduler.private_note='x';}),
    mutate(value=>{value.provider_safety.extra='x';}),
    mutate(value=>{value.provider_safety.private_note='x';}),
    mutate(value=>{value.provider_safety.latest_attempt={...validLatest,extra:'x'};}),
    mutate(value=>{value.provider_safety.latest_attempt={...validLatest,private_note:'x'};}),
    mutate(value=>{value.mentor.extra='x';}),
    mutate(value=>{value.mentor.private_note='x';}),
    mutate(value=>{value.mentor.no_progress.extra='x';}),
    mutate(value=>{value.mentor.repeated.private_note='x';}),
    mutate(value=>{value.health.extra='x';}),
    mutate(value=>{value.health.private_note='x';}),
    mutate(value=>{value.provider_safety.unknown_fence=true;value.provider_safety.latest_attempt={phase:'terminal',status:'succeeded'};value.provider_safety.replay_authorization='not_authorized';}),
    mutate(value=>{value.provider_safety.unknown_fence=true;value.provider_safety.latest_attempt={phase:'terminal',status:'unknown'};value.provider_safety.replay_authorization='authorized';}),
    mutate(value=>{value.provider_safety.replay_authorization='reconciliation_required';}),
    mutate(value=>{value.provider_safety.delayed_until=future;}),
    mutate(value=>{value.provider_safety.delay_source='backoff';}),
    mutate(value=>{value.provider_safety.delayed_until='2026-11-05T02:00:00.000000+00:00';value.provider_safety.delay_source='backoff';}),
    mutate(value=>{value.provider_safety.delayed_until='2026-11-05T01:59:59.999999+00:00';value.provider_safety.delay_source='backoff';}),
    generated('0000-01-01T00:00:00Z'),
    generated('2025-02-29T00:00:00Z'),
    generated('2026-02-30T00:00:00Z'),
    generated('2026-13-01T00:00:00Z'),
    generated('2026-01-01T24:00:00Z'),
    generated('2026-01-01T00:00:00.0000001Z'),
    mutate(value=>{value.scheduler.attempts=.5;}),
    mutate(value=>{value.mentor.cycles=.5;}),
    mutate(value=>{value.mentor.no_progress.used=.5;}),
    mutate(value=>{value.mentor.no_progress.limit=.5;}),
    mutate(value=>{value.mentor.repeated.used=.5;}),
    mutate(value=>{value.mentor.no_progress.used=3;}),
    mutate(value=>{value.mentor.repeated.used=3;}),
    mutate(value=>{value.generated_at='2026-11-07T00:00:01+00:00';}),
  ];
  for(const attack of attacks){
    next=attack;
    await assert.rejects(bridge.get({job:null,output:null},{force:true}),{code:'SCHEDULER_PACKET_REJECTED'});
  }
  next=mutate(value=>{value.provider_safety.delayed_until='2026-11-05T02:00:00.000001+00:00';value.provider_safety.delay_source='backoff';});
  assert.equal((await bridge.get({job:null,output:null},{force:true})).jobs[0].mentor.resilience.provider_safety.delayed_until,'2026-11-05T02:00:00.000001+00:00');
  next=generated('2024-02-29T23:59:59.999999Z');
  assert.equal((await bridge.get({job:null,output:null},{force:true})).generated_at,'2024-02-29T23:59:59.999999Z');
  next=mutate(value=>{value.provider_safety.delayed_until=future;value.provider_safety.delay_source='backoff';});
  assert.equal((await bridge.get({job:null,output:null},{force:true})).jobs[0].mentor.resilience.provider_safety.delayed_until,future);
  next=mutate(value=>{value.provider_safety.unknown_fence=true;value.provider_safety.latest_attempt=null;value.provider_safety.replay_authorization='not_authorized';});
  assert.equal((await bridge.get({job:null,output:null},{force:true})).jobs[0].mentor.resilience.provider_safety.latest_attempt,null);
  next=mutate(value=>{value.provider_safety.unknown_fence=true;value.provider_safety.latest_attempt={phase:'terminal',status:'unknown'};value.provider_safety.replay_authorization='reconciliation_required';});
  assert.equal((await bridge.get({job:null,output:null},{force:true})).jobs[0].mentor.resilience.provider_safety.unknown_fence,true);
  bridge.close();
});

test('scheduler coalesces requests and labels stale snapshots; shutdown closes bounded workers', async () => {
  let calls=0, fail=false;
  const bridge=new SchedulerBridge({ttl:0,loader:async()=>{calls++;await new Promise(r=>setTimeout(r,10));if(fail)throw Error('SYNTHETIC_PRIVATE');return packet;}});
  const values=await Promise.all(Array.from({length:20},()=>bridge.get({job:null,output:null})));
  assert.equal(calls,1);assert.ok(values.every(x=>x===packet));
  fail=true;const stale=await bridge.get({job:null,output:null},{force:true});assert.equal(stale.projection_state,'stale');
  assert.ok(!JSON.stringify(stale).includes('SYNTHETIC_PRIVATE'));bridge.close();
  await assert.rejects(bridge.get({job:null,output:null}),{code:'SERVER_CLOSING'});
});

test('unknown and private scheduler fields are rejected before cache and stale fallback', async () => {
  const canary=`SERVER_PRIVATE_${globalThis.crypto.randomUUID().replaceAll('-','')}`;
  const valid={...packet,jobs:[standard]}; let next=valid;
  const bridge=new SchedulerBridge({ttl:0,loader:async()=>next});
  await bridge.get({job:null,output:null});
  const rejectedKeys=['credentials','password','passwd','secret','token','api_key','private_key','authorization','cookie','prompt','artifact_ref','source_identity','binding_hash'];
  const attacks=[
    {...valid,private_root:canary},
    {...valid,warnings:[{code:'SAFE',private_path:canary}]},
    {...valid,jobs:[{...standard,content:{text:canary}}]},
    ...rejectedKeys.map(key=>({...valid,jobs:[{...standard,[key]:canary}]})),
    {...valid,jobs:[{...mentor,mentor:{...mentor.mentor,private_note:canary}}]},
    {...valid,jobs:[{...mentor,mentor:{...mentor.mentor,work_order:{...mentor.mentor.work_order,source_identity:canary}}}]},
  ];
  for(const attack of attacks){
    next=attack;
    await assert.rejects(bridge.get({job:null,output:null},{force:true}),error=>{
      assert.equal(error.code,'SCHEDULER_PACKET_REJECTED');
      assert.ok(!String(error.message).includes(canary));
      return true;
    });
  }
  assert.equal(bridge.cache.size,1);
  assert.equal(bridge.cache.values().next().value.data,valid);
  bridge.close();
});

test('actual loopback endpoint is read-only, independent from datasource and sanitizes failures',async()=>{
  const port=await freePort();let actual;
  const scheduler=new SchedulerBridge({loader:async options=>{actual=options;if(options.job==='fail')throw Error('SYNTHETIC_PRIVATE');return packet;}});
  const service=await start({port,scheduler,viteFactory:async()=>({middlewares:(_q,r)=>r.end('fixture'),close:async()=>{}})});
  try {
    const origin='http://127.0.0.1:'+port;
    let r=await fetch(origin+'/api/scheduler?job=example');assert.equal(r.status,200);assert.deepEqual(actual,{job:'example',output:null});assert.deepEqual(await r.json(),packet);
    r=await fetch(origin+'/api/scheduler?job=fail');assert.equal(r.status,503);assert.ok(!(await r.text()).includes('SYNTHETIC_PRIVATE'));
    for(const method of ['POST','PUT','PATCH','DELETE']){r=await fetch(origin+'/api/scheduler',{method});assert.equal(r.status,405);}
    r=await fetch(origin+'/api/scheduler',{headers:{Origin:'https://evil.example'}});assert.equal(r.status,403);
    r=await fetch(origin+'/api/scheduler?job=../../auth');assert.equal(r.status,400);
    r=await fetch(origin+'/api/datasource/health');assert.equal(r.status,200);assert.equal((await r.json()).read_only,true);
  } finally {await service.close();}
});
