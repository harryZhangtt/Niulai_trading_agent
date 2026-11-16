import {test, expect} from '../../verification/node_modules/@playwright/test/index.mjs';

const stamp='2026-11-02T16:00:00+00:00';
function job(id,title,patch={}) {return {id,title,description:'Stored scheduler fixture',enabled:true,replay_safe:true,model:'synthetic',effort:'low',schedule:{kind:'daily',timezone:'America/New_York',times:['13:00','19:00'],grace_seconds:3600},next_run_at:'2026-11-02T18:00:00Z',delivery:{mode:'scheduled',next_send_at:'2026-11-02T18:00:00Z',note:'Delivery follows processing.'},history:[],outputs:[],prompt_custody:{status:'legacy_unbound',attempts_bound:0},...patch};}
const alpha=job('alpha','Alpha report'), beta=job('beta','Beta report');
const mentorTruth={
  work_order:{id:'mentor-work-order',logical_session_id:'mentor-work-order',starts_at:'2026-11-02T14:00:00+00:00',ends_at:'2026-11-02T15:00:00+00:00',window_state:'expired',acceptance_criteria_total:1,required_event_kinds:['provider_thread','cycle']},
  scheduler:{status:'failed',code:'OPERATOR_RECONCILED',attempts:1,dispatch:'definitely_not_dispatched'},session:{status:'active',revision:0},
  progress:{cycles:{used:0,limit:2},provider_threads:{used:0,limit:2},variants:{used:0,limit:1},interventions:{used:0,limit:0},reused_evaluations:{used:0,limit:0},pending_effects:0},
  safeguards:{provider_thread_mode:'ephemeral_threads',record_all_variants:true,worker_holdout_access:false,require_no_pending_effects:true,configured_replay_safe:true,replay_authorization:'not_authorized'},
  gates:{future_wake:'verified',profile_binding:'not_verified',stop_propagation:'not_verified',model_turn:'failed',journal_cycle_postcondition:'not_verified',no_duplicate_dispatch:'verified'},
  evaluation:{attempt_ledger_preserved:true,baseline:'pending',ablation:'not_required',holdout:'unverified',promotion:'inconclusive'},
  resilience:{generated_at:stamp,status:'partial',projection_state:'current',scheduler:{status:'failed',attempts:1},provider_safety:{latest_attempt:{phase:'terminal',status:'unknown'},delayed_until:null,delay_source:null,unknown_fence:true,replay_authorization:'reconciliation_required'},mentor:{cycles:4,no_progress:{used:2,limit:4},repeated:{used:2,limit:3},evidence_reset:false},health:{heartbeat_age_seconds:48,watchdog_healthy:true}},
  runtime_acceptance:{execution:'failed',acceptance:'failed',model_turn:'not_started',email:'pending'},
  recovery_timeline:[{event:'scheduled',status:'recorded',at:'2026-11-05T02:00:00+00:00'},{event:'attempt_started',status:'recorded',at:'2026-11-05T02:00:01+00:00'},{event:'dispatch_failed',status:'failed',at:'2026-11-05T02:00:03+00:00'},{event:'operator_reconciled',status:'resolved',at:'2026-11-05T02:00:04+00:00'}]
};
function mentor(patch={}) {return job('mentor.scheduler.fixture','Mentor scheduler acceptance',{job_type:'mentor',description:'Read-only mentor scheduler status.',delivery:{mode:'acceptance',next_send_at:null,note:'Runtime acceptance email status is shown separately.'},history:[],outputs:[],prompt_custody:undefined,mentor:mentorTruth,...patch});}
function providerSafety(patch={}) {return {status:'available',provider:'codex_cli',latest_attempt:{phase:'terminal',submission:'definitely_submitted',terminal_proof:'verified',status:'succeeded',failure:'none'},delayed_until:null,delay_source:null,retry_reason:'PROVIDER_SUCCEEDED',replay_authorization:'not_applicable',circuit:{state:'closed',open_until:null,probe_until:null,probe_eligible:false},unknown_fence:false,queue:{depth:0,oldest_delayed_at:null},...patch};}
function providerSummary(jobs) {
  const items=jobs.filter(item=>item.provider_safety!==undefined), available=items.filter(item=>item.provider_safety?.status==='available');
  const circuits={closed:0,open:0,half_open:0,unavailable:0};for(const item of available)circuits[item.provider_safety.circuit?.state in circuits?item.provider_safety.circuit.state:'unavailable']++;
  return {status:items.length===0?'not_applicable':available.length===0?'unavailable':available.length===items.length?'available':'partial',jobs:items.length,available_jobs:available.length,unknown_fences:available.filter(item=>item.provider_safety.unknown_fence).length,delayed_jobs:available.filter(item=>item.provider_safety.delayed_until).length,queue_depth:available.reduce((sum,item)=>sum+(Number.isInteger(item.provider_safety.queue?.depth)?item.provider_safety.queue.depth:0),0),circuits};
}
function packet(jobs) {return {schema_version:1,scope:'local_codex_scheduler',read_only:true,status:'ok',generated_at:stamp,health:{state:'healthy',heartbeat_at:stamp,watchdog_healthy:true},provider_safety:providerSummary(jobs),jobs,warnings:[]};}
async function fixtures(page, handler) {
  await page.route('**/api/scheduler*',async route=>{
    const p=new URL(route.request().url()).searchParams;
    const value=await handler(p,route);
    if(value!==undefined)await route.fulfill({json:value});
  });
}
const jobRows = page => page.getByRole('region',{name:'Scheduled jobs'}).locator('ul').getByRole('button');
const rowFor = (page,title) => jobRows(page).filter({hasText:title});
const standardViews = page => page.getByRole('navigation',{name:'Job detail views'});
const mentorViews = page => page.getByRole('navigation',{name:'Mentor detail views'});
async function custody(page) {
  await standardViews(page).getByRole('button',{name:'Prompt custody',exact:true}).click();
}
function detailFact(page,label) {
  return page.locator('.scheduler-detail dt').filter({hasText:new RegExp(`^${label}$`)}).locator('..').locator('dd');
}
const detailStatus = (page,label) => detailFact(page,label).locator('.badge');
function run(id,status,code) {
  return {id,scheduled_at:stamp,updated_at:stamp,status,code,attempts:1};
}

test('live registered jobs, next sends, schedule and persisted instructions',async({page,request})=>{
  const response=await request.get('/api/scheduler?job=niulai.daily-business.v1');expect(response.ok()).toBe(true);
  const current=(await response.json()).jobs[0];
  const formatted=zone=>new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',hour12:false,timeZone:zone}).format(new Date(current.delivery.next_send_at));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/scheduler?job=niulai.daily-business.v1');
  await expect(page.getByRole('heading',{name:'Daily price and holdings report',exact:true})).toBeVisible();
  await expect(standardViews(page).getByRole('button',{name:'Overview',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toHaveCount(0);
  await expect(detailFact(page,'Next scheduled send')).toHaveText(formatted('Asia/Shanghai'));
  await custody(page);
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  await standardViews(page).getByRole('button',{name:'Overview',exact:true}).click();
  await page.getByLabel('Display timezone').selectOption('America/New_York');
  await expect(detailFact(page,'Next scheduled send')).toHaveText(formatted('America/New_York'));
  await expect(page.locator('.scheduler-facts').first()).toContainText('America/New_York');
  await page.getByRole('button',{name:'Run history',exact:true}).click();
  await expect(page.getByText('A completed run does not, by itself, prove a message was sent.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:/Saved messages \(\d+\)/}).click();
  if(current.outputs.length===0)await expect(page.getByRole('heading',{name:'No production messages saved yet'})).toBeVisible();
  else await expect(page.getByLabel('Saved message',{exact:true})).toBeVisible();
  await page.getByRole('navigation',{name:'Workspace',exact:true}).getByRole('link',{name:'Research evidence',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Research observability',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation',{name:'Workspace',exact:true}).getByRole('link',{name:'Scheduler',exact:true})).toBeVisible();
  expect(errors).toEqual([]);
});

test('late response for A cannot overwrite B after selection changes',async({page})=>{
  let release, seen;const gate=new Promise(r=>release=r), arrived=new Promise(r=>seen=r);
  await fixtures(page,async p=>{if(!p.get('job'))return packet([alpha,beta]);if(p.get('job')==='alpha'){seen();await gate;return packet([alpha]);}return packet([beta]);});
  await page.goto('/scheduler');await arrived;
  await rowFor(page,'Beta report').click();
  await expect(page.getByRole('heading',{name:'Beta report',exact:true})).toBeVisible();release();
  await custody(page);
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toHaveCount(0);
});

test('failed refresh retains same-job content and retry recovers without raw errors',async({page})=>{
  let failed=false;
  await fixtures(page,async(p,route)=>{if(p.get('job')&&failed){await route.fulfill({status:503,json:{error:{message:'SYNTHETIC_PRIVATE_EXCEPTION'}}});return;}return packet([alpha]);});
  await page.goto('/scheduler');await custody(page);await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  failed=true;await page.getByRole('button',{name:'Refresh selected job'}).click();
  await expect(page.getByRole('alert').getByText('Job details unavailable',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  await expect(page.locator('body')).not.toContainText('SYNTHETIC_PRIVATE_EXCEPTION');
  failed=false;await page.getByRole('button',{name:'Retry details'}).click();
  await expect(page.getByRole('alert').getByText('Job details unavailable',{exact:true})).toHaveCount(0);
});

test('finite sequence jobs show list and detail next runs and exhausted jobs are finished',async({page})=>{
  const future=job('sequence-future','Sequence future',{schedule:{kind:'sequence',timestamps:['2026-11-02T17:00:00Z','2026-11-02T18:00:00Z'],grace_seconds:60},next_run_at:'2026-11-02T17:00:00Z'});
  const exhausted=job('sequence-finished','Sequence finished',{schedule:{kind:'sequence',timestamps:['2026-11-02T15:00:00Z'],grace_seconds:60},next_run_at:null});
  await fixtures(page,async p=>packet(p.get('job')?[p.get('job')===future.id?future:exhausted]:[future,exhausted]));
  await page.goto('/scheduler');
  const formatted=new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',hour12:false,timeZone:'Asia/Shanghai'}).format(new Date(future.next_run_at));
  const futureRow=rowFor(page,'Sequence future');
  await expect(futureRow).toContainText('Next run');await expect(futureRow).toContainText(formatted);await expect(futureRow).toContainText('Finite sequence · 2 scheduled runs');
  await expect(page.locator('.scheduler-facts').first()).toContainText(formatted);
  await expect(rowFor(page,'Sequence finished')).toHaveCount(0);
  await page.getByLabel('Show',{exact:true}).selectOption({label:'All jobs, including historical tests'});
  const finishedRow=rowFor(page,'Sequence finished');await expect(finishedRow).toContainText('Finished');
  await finishedRow.click();await expect(page.getByRole('heading',{name:'Sequence finished',exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-detail')).toContainText('Not scheduled');await expect(page.locator('.scheduler-detail')).toContainText('Finite sequence · 1 scheduled run');await expect(page.locator('.scheduler-detail')).toContainText('Finished');
});

test('malformed sequence schedules are rejected at the adapter boundary',async({page})=>{
  const malformed=job('bad-sequence','Bad sequence',{schedule:{kind:'sequence',timestamps:['2026-11-02T18:00:00Z','2026-11-02T17:00:00Z'],grace_seconds:60}});
  await fixtures(page,async()=>packet([malformed]));await page.goto('/scheduler');
  await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Bad sequence',exact:true})).toHaveCount(0);
});

test('unknown envelope states and inconsistent sequence next runs are rejected',async({page})=>{
  const sequenceJob=job('strict-sequence','Strict sequence',{schedule:{kind:'sequence',timestamps:['2026-11-02T17:00:00Z','2026-11-02T18:00:00Z'],grace_seconds:60},next_run_at:'2026-11-02T17:00:00Z'});
  const baseline=packet([sequenceJob]);
  const canary=`NESTED_PRIVATE_${globalThis.crypto.randomUUID().replaceAll('-','')}`;
  const validRun={id:'run',scheduled_at:stamp,updated_at:stamp,status:'succeeded',code:'DONE',attempts:1};
  const validSaved={id:'d'.repeat(64),subject:'Saved',status:'accepted',verified:true,created_at:stamp,verified_at:stamp,kind:'initial'};
  const validOutput={id:'d'.repeat(64),subject:'Saved',html:'<p>Safe</p>',attachments:[{name:'report.pdf',type:'application/pdf'}]};
  const degradedCustody=packet([{...sequenceJob,prompt_custody:{...sequenceJob.prompt_custody,artifact_ref:'PROMPT_CANARY'}}]);
  await fixtures(page,async()=>degradedCustody);await page.goto('/scheduler');
  await expect(page.getByRole('alert').getByText('Some scheduler evidence is unavailable',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Strict sequence',exact:true})).toBeVisible();
  await custody(page);await expect(page.getByText('unavailable',{exact:true})).toBeVisible();
  await expect(page.locator('body')).not.toContainText('PROMPT_CANARY');
  const malformed=[
    {...baseline,status:'mystery'},
    {...baseline,private_root:'ROOT_CANARY'},
    {...baseline,warnings:[{code:'SAFE',private_path:'WARNING_CANARY'}]},
    packet([{...sequenceJob,private_key:'STANDARD_CANARY'}]),
    {...baseline,projection_state:'fresh'},
    {...baseline,health:{...baseline.health,state:'green'}},
    {...baseline,health:{...baseline.health,private_note:canary}},
    packet([{...sequenceJob,delivery:{...sequenceJob.delivery,private_note:canary}}]),
    packet([{...sequenceJob,history:[{...validRun,private_note:canary}]}]),
    packet([{...sequenceJob,outputs:[{...validSaved,private_note:canary}]}]),
    packet([{...sequenceJob,output:{...validOutput,private_note:canary}}]),
    packet([{...sequenceJob,output:{...validOutput,attachments:[{...validOutput.attachments[0],private_note:canary}]}}]),
    {...baseline,generated_at:'2026-11-02T12:00:00-04:00'},
    {...baseline,generated_at:'2026-02-30T16:00:00Z'},
    {...baseline,health:{...baseline.health,heartbeat_at:'2026-11-02T24:00:00Z'}},
    packet([{...sequenceJob,schedule:{...sequenceJob.schedule,timestamps:['2025-02-29T17:00:00Z']},next_run_at:'2025-02-29T17:00:00Z'}]),
    packet([{...sequenceJob,next_run_at:'2026-11-02T18:00:00Z'}]),
    packet([{...sequenceJob,next_run_at:'2026-11-02T24:00:00Z'}]),
    packet([{...sequenceJob,next_run_at:'not-a-time'}]),
  ];
  for(const value of malformed){
    await page.unroute('**/api/scheduler*');await fixtures(page,async()=>value);
    if(page.url()==='about:blank')await page.goto('/scheduler');else await page.reload();
    await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Strict sequence',exact:true})).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(canary);
  }
});

test('wrong job identity and malformed snapshots fail visibly',async({page})=>{
  await fixtures(page,async p=>p.get('job')?packet([beta]):packet([alpha]));
  await page.goto('/scheduler');await expect(page.getByRole('alert').getByText('Job details unavailable',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Beta report',exact:true})).toHaveCount(0);
});

test('malformed run data is rejected before rendering instead of crashing the page',async({page})=>{
  await fixtures(page,async p=>packet([p.get('job')?{...alpha,history:[{id:'bad',code:null}]}:alpha]));
  await page.goto('/scheduler');await expect(page.getByRole('alert').getByText('Job details unavailable',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Scheduler',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Scheduler could not be displayed'})).toHaveCount(0);
});

test('provider Retry-After and backoff schedules remain distinct from delivery',async({page})=>{
  const retryAt='2026-11-02T17:00:00+00:00';
  const retryAfter=job('provider-retry-after','Provider Retry-After',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'http'},delayed_until:retryAt,delay_source:'retry_after',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  const backoff=job('provider-backoff','Provider backoff',{provider_safety:providerSafety({provider:'claude_host',latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:retryAt,delay_source:'backoff',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',queue:{depth:2,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  const due=job('provider-due','Provider retry due',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized'})});
  const jobs=[retryAfter,backoff,due];await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));await page.goto('/scheduler');
  await expect(rowFor(page,'Provider Retry-After')).toContainText('Retry-After');await expect(rowFor(page,'Provider Retry-After')).toContainText('Queue: 1');
  await expect(rowFor(page,'Provider retry due')).toContainText('Provider retry is due now');await rowFor(page,'Provider retry due').click();await expect(detailFact(page,'Retry schedule')).toHaveText('Due now; awaiting scheduler');
  await rowFor(page,'Provider backoff').click();await expect(page.getByRole('heading',{name:'Provider retry and circuit',exact:true})).toBeVisible();
  await expect(detailFact(page,'Provider')).toHaveText('Claude host');await expect(detailFact(page,'Retry schedule')).toContainText('backoff');await expect(detailFact(page,'Provider queue')).toContainText('2 attempts');
  await expect(page.locator('.scheduler-provider-panel')).toContainText('do not prove the business task completed or an email was delivered');
  await expect(page.locator('.scheduler-provider-panel').getByRole('button',{name:/Retry|Reconcile|Run now/i})).toHaveCount(0);
});

test('provider open and half-open circuits show effective circuit timing',async({page})=>{
  const openUntil='2026-11-02T17:30:00+00:00',probeUntil='2026-11-02T17:10:00+00:00';
  const open=job('provider-open','Open circuit delay',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:openUntil,delay_source:'circuit',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',circuit:{state:'open',open_until:openUntil,probe_until:null,probe_eligible:false},queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  const half=job('provider-half','Half-open circuit probe',{provider_safety:providerSafety({latest_attempt:null,retry_reason:null,replay_authorization:'unavailable',circuit:{state:'half_open',open_until:null,probe_until:probeUntil,probe_eligible:false}})});
  const jobs=[open,half];await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));await page.goto('/scheduler');
  await expect(rowFor(page,'Open circuit delay')).toContainText('Circuit Open');await rowFor(page,'Open circuit delay').click();await expect(detailFact(page,'Circuit')).toContainText('Open until');await expect(detailFact(page,'Retry schedule')).toContainText('circuit');
  await rowFor(page,'Half-open circuit probe').click();await expect(detailFact(page,'Circuit')).toContainText('Half-open');await expect(detailFact(page,'Circuit')).toContainText('Probe until');
});

test('unknown provider outcomes require reconciliation and never become delivery evidence',async({page})=>{
  const unknown=job('provider-unknown','Unknown provider outcome',{provider_safety:providerSafety({latest_attempt:{phase:'terminal',submission:'possibly_submitted',terminal_proof:'absent',status:'unknown',failure:'timeout'},retry_reason:'PROVIDER_OUTCOME_UNKNOWN',replay_authorization:'reconciliation_required',unknown_fence:true})});
  await fixtures(page,async()=>packet([unknown]));await page.goto('/scheduler');
  await expect(rowFor(page,'Unknown provider outcome')).toContainText('Unknown outcome—reconciliation required');
  await expect(page.getByText('Unknown outcome—reconciliation required',{exact:true}).last()).toBeVisible();
  await expect(detailFact(page,'Replay authorization')).toHaveText('reconciliation required');await expect(detailFact(page,'Failure classification')).toHaveText('Timeout');
  await expect(detailStatus(page,'Recorded delivery')).toHaveText('No delivery record');
  await expect(page.locator('.scheduler-provider-panel').getByRole('button',{name:/Retry|Reconcile|Run now/i})).toHaveCount(0);
});

test('provider unavailable is visible while legacy standard jobs remain unchanged',async({page})=>{
  const unavailable=job('provider-unavailable','Unavailable provider safety',{provider_safety:{status:'unavailable'}}),legacy=job('provider-legacy','Legacy scheduler job');
  const jobs=[unavailable,legacy];await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));await page.goto('/scheduler');
  await expect(rowFor(page,'Unavailable provider safety')).toContainText('Provider safety unavailable');await rowFor(page,'Unavailable provider safety').click();
  await expect(page.getByText('Retry, circuit and outcome-fence evidence could not be validated.',{exact:false})).toBeVisible();
  await rowFor(page,'Legacy scheduler job').click();await expect(page.getByRole('heading',{name:'Provider retry and circuit',exact:true})).toHaveCount(0);await expect(rowFor(page,'Legacy scheduler job')).not.toContainText('Provider');
});

test('malformed provider enums, times and cross-state combinations fail only that item visibly unavailable',async({page})=>{
  const malformed=[
    providerSafety({provider:'private_provider'}),
    providerSafety({delayed_until:'2026-11-02T12:00:00-05:00',delay_source:'backoff'}),
    providerSafety({delayed_until:stamp,delay_source:null}),
    providerSafety({latest_attempt:{phase:'streaming',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'}}),
    providerSafety({latest_attempt:{phase:'terminal',submission:'definitely_submitted',terminal_proof:'verified',status:'succeeded',failure:'provider'}}),
    providerSafety({latest_attempt:{phase:'terminal',submission:'definitely_submitted',terminal_proof:'verified',status:'running',failure:'provider'}}),
    providerSafety({circuit:{state:'open',open_until:null,probe_until:null,probe_eligible:false}}),
    providerSafety({queue:{depth:0,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}}),
    {...providerSafety(),operation_id:'PRIVATE_OPERATION_CANARY',error:'PRIVATE_ERROR_CANARY',receipt:'PRIVATE_RECEIPT_CANARY'},
  ];
  for(const [index,safety] of malformed.entries()){
    const value=job(`bad-provider-${index}`,'Malformed provider safety',{provider_safety:safety});await page.unroute('**/api/scheduler*');await fixtures(page,async()=>packet([value]));
    if(page.url()==='about:blank')await page.goto('/scheduler');else await page.reload();
    await expect(rowFor(page,'Malformed provider safety')).toContainText('Provider safety unavailable');await expect(page.getByText('Provider safety unavailable',{exact:true}).last()).toBeVisible();
    await expect(page.locator('.scheduler-detail').getByText('Job evidence is incomplete',{exact:true})).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/PRIVATE_OPERATION_CANARY|PRIVATE_ERROR_CANARY|PRIVATE_RECEIPT_CANARY/);
  }
});

test('concrete running provider result degrades to unavailable and forces partial despite matching aggregate',async({page})=>{
  const malformed=job('provider-concrete-running','Concrete running provider result',{provider_safety:providerSafety({latest_attempt:{phase:'terminal',submission:'definitely_submitted',terminal_proof:'verified',status:'running',failure:'provider'}})});
  const unavailableSummary={status:'unavailable',jobs:1,available_jobs:0,unknown_fences:0,delayed_jobs:0,queue_depth:0,circuits:{closed:0,open:0,half_open:0,unavailable:0}};
  await fixtures(page,async()=>({...packet([malformed]),status:'ok',provider_safety:unavailableSummary}));await page.goto('/scheduler');
  await expect(rowFor(page,'Concrete running provider result').locator('.scheduler-row-meta .badge')).toHaveText('Provider safety unavailable');
  await expect(page.getByRole('alert').getByText('Some scheduler evidence is unavailable',{exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-detail').getByText('Job evidence is incomplete',{exact:true})).toBeVisible();
  const attention=page.getByRole('button',{name:/Needs attention/});await expect(attention).toContainText('1');await attention.click();await expect(rowFor(page,'Concrete running provider result')).toBeVisible();
});

test('malformed provider aggregate fails the refresh while stale provider snapshots stay labelled',async({page})=>{
  const retryAt='2026-11-02T17:00:00+00:00';const withSafety=job('stale-provider','Stale provider retry',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:retryAt,delay_source:'backoff',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  await fixtures(page,async()=>({...packet([withSafety]),projection_state:'stale'}));await page.goto('/scheduler');await expect(page.getByText('This job is showing a retained stale snapshot.',{exact:false})).toBeVisible();await expect(detailFact(page,'Retry schedule')).toContainText('backoff');
  await page.unroute('**/api/scheduler*');await fixtures(page,async()=>({...packet([withSafety]),provider_safety:{...providerSummary([withSafety]),status:'not_applicable'}}));await page.reload();
  await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();
});

test('provider safety supports RTL mobile layout and long standard job identities',async({page})=>{
  const longId='p'+ 'x'.repeat(95),openUntil='2026-11-02T17:30:00+00:00';
  const value=job(longId,'Long provider identity',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:openUntil,delay_source:'circuit',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',circuit:{state:'open',open_until:openUntil,probe_until:null,probe_eligible:false},queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  await fixtures(page,async()=>packet([value]));await page.setViewportSize({width:320,height:800});await page.goto('/scheduler');await page.evaluate(()=>document.documentElement.dir='rtl');
  await rowFor(page,'Long provider identity').click();await expect(page.getByRole('heading',{name:'Provider retry and circuit',exact:true})).toBeVisible();
  await custody(page);await standardViews(page).getByRole('button',{name:'Overview',exact:true}).click();
  await expect(page.locator('body')).not.toContainText(longId);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('standard job identities beyond the server contract fail visibly',async({page})=>{
  const value=job('x'.repeat(97),'Oversized job identity');await fixtures(page,async()=>packet([value]));await page.goto('/scheduler');
  await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Oversized job identity',exact:true})).toHaveCount(0);
});

test('empty search, keyboard focus, narrow layouts and long stored content',async({page})=>{
  const long=job('long','A long operational job '+ 'W'.repeat(150),{prompt_custody:{status:'bound',attempts_bound:1000000}});
  await fixtures(page,async()=>packet([long]));
  await page.setViewportSize({width:360,height:800});await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/scheduler');
  await rowFor(page,long.title).click();await custody(page);
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  const overflow=await page.locator('body *').evaluateAll(nodes=>nodes.filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right})));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),JSON.stringify(overflow)).toBe(true);
  await page.getByRole('button',{name:'Back to jobs',exact:true}).click();
  expect(await page.getByLabel('Find a job',{exact:true}).evaluate(e=>e.getBoundingClientRect().width)).toBeGreaterThan(250);
  await page.getByLabel('Find a job',{exact:true}).focus();expect(await page.evaluate(()=>document.activeElement.matches(':focus-visible'))).toBe(true);
  await page.getByLabel('Find a job',{exact:true}).fill('no match');await expect(page.getByRole('heading',{name:'No jobs match your search'})).toBeVisible();
  expect(await page.evaluate(()=>window.__CANARY)).toBeUndefined();
});

test('full mentor truth renders all grouped evidence without private write surfaces',async({page})=>{
  const mixed=[mentor(),alpha];
  await fixtures(page,async p=>packet(p.get('job')==='mentor.scheduler.fixture'?[mentor()]:p.get('job')?[alpha]:mixed));
  await page.setViewportSize({width:360,height:900});await page.goto('/scheduler');
  await page.getByLabel('Display timezone').selectOption('UTC');
  await expect(rowFor(page,'Alpha report')).toBeVisible();
  await rowFor(page,'Mentor scheduler acceptance').click();
  await expect(page.getByRole('heading',{name:'Mentor scheduler acceptance',exact:true})).toBeVisible();
  await expect(mentorViews(page).getByRole('button',{name:'Overview',exact:true})).toHaveAttribute('aria-pressed','true');
  for(const heading of ['Plan and acceptance gates','Runtime acceptance','Resilience','Snapshot','Active work','Recovery','Host timing'])await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible();
  for(const label of ['Future wake','Profile binding','Stop propagation','Model turn','Journal cycle postcondition','No duplicate dispatch'])await expect(page.locator('.mentor-detail dt').filter({hasText:new RegExp(`^${label}$`)}).first()).toBeVisible();
  const resiliencePanel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  const recordedAt=resiliencePanel.locator('dt').filter({hasText:/^Recorded at$/}).locator('..').locator('time');
  await expect(recordedAt).toHaveAttribute('datetime',stamp);
  await expect(recordedAt).toContainText('UTC');
  await expect(recordedAt).toContainText(new Intl.DateTimeFormat('en',{dateStyle:'medium',timeStyle:'short',hour12:false,timeZone:'UTC'}).format(new Date(stamp)));
  for(const label of ['Recorded at','Snapshot completeness','Effective freshness','Scheduler','Latest provider attempt','Unknown-outcome fence','Provider replay authorization','Retry timing','Mentor cycles','No-progress budget','Repeated-evidence budget','Evidence reset','Heartbeat age at snapshot','Watchdog observation','Last tick','Catch-up'])await expect(resiliencePanel.locator('dt').filter({hasText:new RegExp(`^${label}$`)})).toBeVisible();
  await expect(resiliencePanel.getByText('Unknown',{exact:true}).first()).toBeVisible();
  await expect(resiliencePanel.getByText('reconciliation required',{exact:true})).toBeVisible();
  for(const label of ['Last tick','Catch-up'])await expect(resiliencePanel.locator('dt').filter({hasText:new RegExp(`^${label}$`)}).locator('..').locator('dd')).toHaveText('Not recorded');
  await expect(resiliencePanel.getByText('Provider execution, business acceptance and email delivery are separate outcomes.',{exact:true})).toBeVisible();
  await expect(resiliencePanel.locator('button, form, input, select, textarea')).toHaveCount(0);
  await expect(page.getByText('failed',{exact:true}).first()).toBeVisible();
  await expect(page.getByText('pending',{exact:true}).first()).toBeVisible();
  await mentorViews(page).getByRole('button',{name:'Evidence and safeguards',exact:true}).click();
  for(const heading of ['Overview and work order','Safeguards and progress','Evaluation and overfitting controls','History and current scheduler state'])await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible();
  for(const label of ['Work-order ID','Logical session ID','Session','Revision','Starts','Ends','Window','Acceptance criteria','Required event kinds','Cycles','Provider threads','Variants','Interventions','Reused evaluations','Pending effects','Provider thread mode','Record all variants','Worker holdout access','Require no pending effects','Configured replay-safe','Replay authorization','Attempt ledger preserved','Baseline','Ablation','Holdout','Promotion','Scheduler status','Scheduler code','Attempts','Dispatch','Session revision'])await expect(page.locator('.mentor-detail dt').filter({hasText:new RegExp(`^${label}$`)}).first()).toBeVisible();
  for(const text of ['mentor-work-order','provider thread, cycle','0 used / 2 limit','ephemeral threads','not authorized','OPERATOR_RECONCILED'])await expect(page.getByText(text,{exact:true}).first()).toBeVisible();
  await mentorViews(page).getByRole('button',{name:'Recovery timeline',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Recovery timeline',exact:true})).toBeVisible();
  for(const event of ['scheduled','attempt started','dispatch failed','operator reconciled'])await expect(page.locator('.mentor-timeline').getByText(event,{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Prompt custody'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Replay|Dispatch|Start/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('mentor layout supports keyboard selection, RTL and long identifiers on mobile',async({page})=>{
  const longId='mentor-'+ 'x'.repeat(300);const longMentor=mentor({mentor:{...mentorTruth,work_order:{...mentorTruth.work_order,id:longId,logical_session_id:longId}}});
  await fixtures(page,async()=>packet([longMentor]));await page.setViewportSize({width:320,height:800});await page.goto('/scheduler');
  await page.evaluate(()=>document.documentElement.dir='rtl');const row=rowFor(page,'Mentor scheduler acceptance');await row.focus();await page.keyboard.press('Enter');
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  for(const heading of ['Snapshot','Active work','Recovery','Host timing'])await expect(panel.getByRole('heading',{name:heading,exact:true})).toBeVisible();
  await expect(panel.getByText('Not recorded',{exact:true})).toHaveCount(2);
  expect(await page.getByRole('button',{name:'Back to jobs'}).locator('svg').evaluate(node=>getComputedStyle(node).transform)).toBe('none');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await mentorViews(page).getByRole('button',{name:'Evidence and safeguards',exact:true}).click();
  await expect(page.getByText(longId,{exact:true}).first()).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('mentor resilience thresholds and evidence reset remain distinct',async({page})=>{
  const evidenceJob=(id,title,evidence)=>mentor({id,title,mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,mentor:{...mentorTruth.resilience.mentor,...evidence}}}});
  const jobs=[
    evidenceJob('resilience-no-progress-info','No-progress info',{no_progress:{used:1,limit:4}}),
    evidenceJob('resilience-no-progress-warning','No-progress warning',{no_progress:{used:2,limit:4}}),
    evidenceJob('resilience-no-progress-critical','No-progress critical',{no_progress:{used:4,limit:4}}),
    evidenceJob('resilience-repeated-limit-one','Repeated limit one',{repeated:{used:1,limit:1}}),
    evidenceJob('resilience-repeated-info','Repeated info',{repeated:{used:1,limit:3}}),
    evidenceJob('resilience-repeated-warning','Repeated warning',{repeated:{used:2,limit:3}}),
    evidenceJob('resilience-repeated-critical','Repeated critical',{repeated:{used:3,limit:3}}),
    evidenceJob('resilience-repeated-reset','Repeated reset',{repeated:{used:3,limit:3},evidence_reset:true}),
  ];
  await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));await page.goto('/scheduler');
  const state=label=>page.getByRole('region',{name:'Scheduler resilience evidence'}).locator('dt').filter({hasText:new RegExp(`^${label}$`)}).locator('..').locator('[class*=threshold]');
  for(const [title,label,threshold] of [['No-progress info','No-progress budget','Below warning threshold'],['No-progress warning','No-progress budget','Warning threshold'],['No-progress critical','No-progress budget','Limit reached'],['Repeated limit one','Repeated-evidence budget','Limit reached'],['Repeated info','Repeated-evidence budget','Below warning threshold'],['Repeated warning','Repeated-evidence budget','Warning threshold'],['Repeated critical','Repeated-evidence budget','Limit reached'],['Repeated reset','Repeated-evidence budget','Within threshold']]){
    await rowFor(page,title).click();await expect(state(label)).toHaveText(threshold);
  }
});

test('mentor unknown fence stays visible without invented provider phase',async({page})=>{
  const unknown=mentor({id:'mentor-unknown-null-provider',title:'Unknown mentor provider outcome',mentor:{...mentorTruth,scheduler:{status:'unknown',code:'MENTOR_JOB_CYCLE_UNKNOWN',attempts:1,dispatch:'possibly_dispatched'},resilience:{...mentorTruth.resilience,scheduler:{status:'unknown',attempts:1},provider_safety:{latest_attempt:null,delayed_until:null,delay_source:null,unknown_fence:true,replay_authorization:'not_authorized'}},runtime_acceptance:{execution:'partial',acceptance:'partial',model_turn:'unknown',email:'unknown'}}});
  await fixtures(page,async()=>packet([unknown]));await page.goto('/scheduler');
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  await expect(panel.getByText('Outcome unknown; replay fenced',{exact:true})).toBeVisible();
  await expect(panel.getByText('not authorized',{exact:true})).toBeVisible();
  await expect(panel.locator('dt').filter({hasText:/^Unknown-outcome fence$/}).locator('..').locator('[class*=semanticState]')).toHaveText('Critical status');
  await expect(panel.locator('dt').filter({hasText:/^Provider replay authorization$/}).locator('..').locator('[class*=semanticState]')).toHaveText('Warning status');
  await expect(panel.locator('dt').filter({hasText:/^Retry timing$/}).locator('..').locator('dd')).toHaveText('No retry scheduled · Source No retry source');
  await expect(panel.locator('dt').filter({hasText:/^Latest provider attempt$/}).locator('..').locator('dd')).toHaveText('Phase Unavailable · Status Unavailable');

  const safe=mentor({id:'mentor-safe-provider',title:'Safe mentor provider state',mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,provider_safety:{latest_attempt:{phase:'terminal',status:'succeeded'},delayed_until:null,delay_source:null,unknown_fence:false,replay_authorization:'not_applicable'}}}});
  await page.unroute('**/api/scheduler*');await fixtures(page,async()=>packet([safe]));await page.reload();
  await expect(panel.getByText('No unknown fence recorded',{exact:true})).toBeVisible();
  await expect(panel.locator('dt').filter({hasText:/^Unknown-outcome fence$/}).locator('..').locator('[class*=semanticState]')).toHaveText('Clear status');
  await expect(panel.getByText('not applicable',{exact:true})).toBeVisible();
  await expect(panel.locator('dt').filter({hasText:/^Provider replay authorization$/}).locator('..').locator('[class*=semanticState]')).toHaveCount(0);

  const scheduled=mentor({id:'mentor-scheduled-retry',title:'Scheduled mentor retry',mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,provider_safety:{latest_attempt:{phase:'terminal',status:'retryable'},delayed_until:'2026-11-02T17:00:00+00:00',delay_source:'backoff',unknown_fence:false,replay_authorization:'authorized'}}}});
  await page.unroute('**/api/scheduler*');await fixtures(page,async()=>packet([scheduled]));await page.reload();
  const retryRow=panel.locator('dt').filter({hasText:/^Retry timing$/}).locator('..').locator('dd');
  await expect(retryRow).toContainText('Source backoff');
  await expect(retryRow.locator('time')).toHaveAttribute('datetime','2026-11-02T17:00:00+00:00');
  await expect(panel.locator('dt').filter({hasText:/^Provider replay authorization$/}).locator('..').locator('[class*=semanticState]')).toHaveText('Clear status');
});

test('forged mentor shape and malformed discriminated mentor fail visibly',async({page})=>{
  const forged=job('forged','Forged legacy job',{mentor:mentorTruth});
  await fixtures(page,async()=>packet([forged]));
  await page.goto('/scheduler');await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toHaveCount(0);
  for(const malformed of [mentor({mentor:{...mentorTruth,extra:{}}}),mentor({mentor:{...mentorTruth,work_order:{...mentorTruth.work_order,source_identity:'MENTOR_PROMPT_CANARY'}}}),mentor({job_type:'MENTOR'}),mentor({mentor:{...mentorTruth,scheduler:{...mentorTruth.scheduler,code:'raw private'}}}),mentor({mentor:{...mentorTruth,progress:{...mentorTruth.progress,cycles:{used:3,limit:2}}}}),mentor({mentor:{...mentorTruth,work_order:{...mentorTruth.work_order,starts_at:'not-a-time'}}}),mentor({mentor:{...mentorTruth,work_order:{...mentorTruth.work_order,window_state:'upcoming'}}}),mentor({mentor:{...mentorTruth,recovery_timeline:[{...mentorTruth.recovery_timeline[0],at:'2025-02-29T02:00:00Z'}]}}),mentor({mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,private_receipt:'RESILIENCE_PRIVATE_CANARY'}}}),mentor({mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,provider_safety:{...mentorTruth.resilience.provider_safety,latest_attempt:{...mentorTruth.resilience.provider_safety.latest_attempt,private_receipt:'RESILIENCE_PRIVATE_CANARY'}}}}}),mentor({mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,mentor:{...mentorTruth.resilience.mentor,no_progress:{used:5,limit:4}}}}}),mentor({mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,provider_safety:{...mentorTruth.resilience.provider_safety,unknown_fence:false}}}}),mentor({mentor:{...mentorTruth,resilience:{...mentorTruth.resilience,provider_safety:{...mentorTruth.resilience.provider_safety,delayed_until:'2026-11-02T17:00:00+00:00'}}}})]){
    await page.unroute('**/api/scheduler*');
    await fixtures(page,async()=>packet([malformed]));
    await page.reload();
    await expect(page.getByRole('alert').getByText('Scheduler refresh failed',{exact:true})).toBeVisible();
    await expect(page.getByRole('heading',{name:'Overview and work order'})).toHaveCount(0);
  }
});

test('passed and staged mentor states remain distinct and bounded',async({page})=>{
  const verifiedGates=Object.fromEntries(Object.keys(mentorTruth.gates).map(key=>[key,'verified']));
  const passed=mentor({mentor:{...mentorTruth,scheduler:{status:'succeeded',code:'MENTOR_JOB_CYCLE_SUCCEEDED',attempts:1,dispatch:'confirmed_dispatched'},session:{status:'completed',revision:2},gates:verifiedGates,runtime_acceptance:{execution:'passed',acceptance:'passed',model_turn:'completed',email:'verified'},recovery_timeline:mentorTruth.recovery_timeline.slice(0,2)}});
  await fixtures(page,async()=>packet([passed]));await page.goto('/scheduler');
  await expect(page.getByText('completed',{exact:true}).first()).toBeVisible();await expect(page.getByText('confirmed dispatched',{exact:true})).toBeVisible();
  await page.unroute('**/api/scheduler*');
  const staged=mentor({mentor:{...mentorTruth,scheduler:{status:'ready',code:'MENTOR_JOB_CYCLE_BLOCKED',attempts:0,dispatch:'not_attempted'},gates:{...mentorTruth.gates,future_wake:'not_verified',model_turn:'not_verified',no_duplicate_dispatch:'not_verified'},runtime_acceptance:{execution:'pending',acceptance:'unverified',model_turn:'not_started',email:'pending'},recovery_timeline:[]}});
  await fixtures(page,async()=>packet([staged]));await page.reload();
  await expect(page.getByText('not attempted',{exact:true})).toBeVisible();
  await mentorViews(page).getByRole('button',{name:'Recovery timeline',exact:true}).click();
  await expect(page.getByText('No recovery events are recorded.')).toBeVisible();
});

test('exact unavailable mentor sentinel renders honest unavailable state',async({page})=>{
  const unavailable=mentor({mentor:{status:'unavailable'}});
  await fixtures(page,async()=>packet([unavailable]));await page.goto('/scheduler');
  await expect(page.getByText('The bounded evidence could not be validated. No success, dispatch, acceptance, or delivery is inferred.')).toBeVisible();
});

test('stored message preview cannot execute scripts, navigate parent or load remote content',async({page})=>{
  const id='b'.repeat(64), message={id,subject:'Stored report',status:'accepted',verified:true,created_at:stamp,verified_at:stamp,kind:'initial'};
  const withMessage=job('alpha','Alpha report',{outputs:[message]});
  await fixtures(page,async p=>packet([{...withMessage,...(p.get('output')?{output:{id,subject:'Stored report',html:'<script>parent.__CANARY=1</script><img src="https://example.invalid/tracker"><h1>Captured report</h1>',attachments:[{name:'prices.pdf',type:'application/pdf'}]}}:{})}]));
  const external=[];page.on('request',r=>{if(r.url().includes('example.invalid'))external.push(r.url());});
  await page.goto('/scheduler');await expect(detailStatus(page,'Recorded delivery')).toHaveText('Delivery verified');await page.getByRole('button',{name:'Saved messages (1)'}).click();await page.getByLabel('Saved message',{exact:true}).selectOption(id);
  await expect(page.frameLocator('iframe').getByRole('heading',{name:'Captured report'})).toBeVisible();
  expect(await page.locator('iframe').getAttribute('sandbox')).toBe('');expect(await page.evaluate(()=>window.__CANARY)).toBeUndefined();expect(external).toEqual([]);
  await expect(page.getByText('Saved attachments: prices.pdf')).toBeVisible();
});

test('current work, attention and recurring views count operational jobs without treating finite work as recurring',async({page})=>{
  const daily=job('daily-healthy','Daily market report',{history:[run('daily-ok','succeeded','DAILY_REPORT_ACCEPTED')]});
  const recovery=job('conditional-recovery','Conditional recovery',{schedule:{kind:'interval',seconds:300,grace_seconds:60},delivery:{mode:'conditional',next_send_at:null,note:'Only when eligible pending recovery is ready.'},history:[run('recovery-no-send','succeeded','DAILY_NO_RECOVERY_DUE')]});
  const failed=job('failed-report','Failed report',{history:[run('report-failed','failed','DAILY_REPORT_FAILED')]});
  const unknown=mentor({schedule:{kind:'once',at:'2026-11-02T15:00:00Z',grace_seconds:60},next_run_at:null,mentor:{...mentorTruth,scheduler:{status:'unknown',code:'MENTOR_RESULT_UNKNOWN',attempts:1,dispatch:'possibly_dispatched'},session:{status:'blocked_pending_effect',revision:0},progress:{...mentorTruth.progress,pending_effects:1},runtime_acceptance:{execution:'unverified',acceptance:'unverified',model_turn:'unknown',email:'unknown'}}});
  const future=job('future-sequence','Future finite task',{schedule:{kind:'sequence',timestamps:['2026-11-02T17:00:00Z'],grace_seconds:60},next_run_at:'2026-11-02T17:00:00Z',delivery:{mode:'none',next_send_at:null,note:'No email schedule.'}});
  const finished=job('finished-sequence','Finished finite task',{schedule:{kind:'sequence',timestamps:['2026-11-02T15:00:00Z'],grace_seconds:60},next_run_at:null});
  const disabled=job('disabled-once','Disabled historical task',{enabled:false,schedule:{kind:'once',at:'2026-11-02T15:00:00Z',grace_seconds:60},next_run_at:null});
  const jobs=[daily,recovery,failed,unknown,future,finished,disabled];
  await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));
  const methods=[];page.on('request',request=>{if(new URL(request.url()).pathname==='/api/scheduler')methods.push(request.method());});
  await page.goto('/scheduler');
  await expect(page.getByLabel('Show',{exact:true}).locator('option:checked')).toHaveText('Current jobs');
  await expect(jobRows(page)).toHaveCount(5);
  await expect(rowFor(page,'Finished finite task')).toHaveCount(0);await expect(rowFor(page,'Disabled historical task')).toHaveCount(0);
  await expect(page.getByText('Next scheduled run',{exact:true})).toBeVisible();
  await rowFor(page,'Daily market report').click();await expect(detailStatus(page,'Last execution')).toHaveText('Completed');await expect(detailStatus(page,'Recorded delivery')).toHaveText('No delivery record');
  const attention=page.getByRole('button',{name:/Needs attention/});await expect(attention).toContainText('2');await attention.click();
  await expect(page.getByLabel('Show',{exact:true}).locator('option:checked')).toHaveText('Needs attention');await expect(jobRows(page)).toHaveCount(2);
  await expect(rowFor(page,'Failed report')).toBeVisible();await expect(rowFor(page,'Mentor scheduler acceptance')).toContainText(/unknown/i);
  await page.getByLabel('Show',{exact:true}).selectOption({label:'Recurring jobs'});await expect(jobRows(page)).toHaveCount(3);
  await expect(rowFor(page,'Future finite task')).toHaveCount(0);await expect(rowFor(page,'Mentor scheduler acceptance')).toHaveCount(0);
  await rowFor(page,'Conditional recovery').click();await expect(page.locator('.scheduler-detail')).toContainText('Only when recovery is ready');await expect(detailStatus(page,'Last execution')).toHaveText('No send due');
  await page.getByLabel('Show',{exact:true}).selectOption({label:'All jobs, including historical tests'});await expect(jobRows(page)).toHaveCount(7);
  expect(methods.length).toBeGreaterThan(0);expect(methods.every(method=>method==='GET')).toBe(true);
});

test('provider hazards enter Needs attention while healthy closed and legacy jobs remain unchanged',async({page})=>{
  const delayedAt='2026-11-02T17:00:00+00:00',openUntil='2026-11-02T17:30:00+00:00',probeUntil='2026-11-02T17:10:00+00:00';
  const healthy=job('provider-attention-healthy','Healthy closed provider',{provider_safety:providerSafety()}),legacy=job('provider-attention-legacy','Legacy provider-free job');
  const unavailable=job('provider-attention-unavailable','Unavailable provider evidence',{provider_safety:{status:'unavailable'}});
  const unknown=job('provider-attention-unknown','Unknown fenced provider',{provider_safety:providerSafety({latest_attempt:{phase:'terminal',submission:'possibly_submitted',terminal_proof:'absent',status:'unknown',failure:'timeout'},retry_reason:'PROVIDER_OUTCOME_UNKNOWN',replay_authorization:'reconciliation_required',unknown_fence:true})});
  const open=job('provider-attention-open','Fully open circuit hazard',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:openUntil,delay_source:'circuit',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',circuit:{state:'open',open_until:openUntil,probe_until:null,probe_eligible:false},queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  const half=job('provider-attention-half','Circuit probe hazard',{provider_safety:providerSafety({latest_attempt:null,retry_reason:null,replay_authorization:'unavailable',circuit:{state:'half_open',open_until:null,probe_until:probeUntil,probe_eligible:false}})});
  const delayed=job('provider-attention-delayed','Delayed provider retry',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},delayed_until:delayedAt,delay_source:'backoff',retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized',queue:{depth:1,oldest_delayed_at:'2026-11-02T16:01:00+00:00'}})});
  const due=job('provider-attention-due','Due provider retry',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'retryable',failure:'connection'},retry_reason:'RETRY_SCHEDULED',replay_authorization:'authorized'})});
  const denied=job('provider-attention-denied','Denied provider replay',{provider_safety:providerSafety({latest_attempt:{phase:'connecting',submission:'not_submitted',terminal_proof:'absent',status:'failed',failure:'connection'},retry_reason:'REPLAY_AUTHORITY_ABSENT',replay_authorization:'not_authorized'})});
  const jobs=[healthy,legacy,unavailable,unknown,open,half,delayed,due,denied];await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));await page.goto('/scheduler');
  const attention=page.getByRole('button',{name:/Needs attention/});await expect(attention).toContainText('7');await attention.click();await expect(jobRows(page)).toHaveCount(7);
  for(const [title,reason] of [['Unavailable provider evidence','Provider safety unavailable'],['Unknown fenced provider','Provider reconciliation required'],['Fully open circuit hazard','Provider circuit open'],['Circuit probe hazard','Provider circuit half-open'],['Delayed provider retry','Provider retry scheduled'],['Due provider retry','Provider retry due'],['Denied provider replay','Provider replay not authorized']])await expect(rowFor(page,title).locator('.scheduler-row-meta .badge')).toHaveText(reason);
  await expect(rowFor(page,'Healthy closed provider')).toHaveCount(0);await expect(rowFor(page,'Legacy provider-free job')).toHaveCount(0);
  await rowFor(page,'Delayed provider retry').click();await expect(detailFact(page,'Retry schedule')).toContainText('backoff');await expect(detailStatus(page,'Recorded delivery')).toHaveText('No delivery record');
  await page.getByLabel('Show',{exact:true}).selectOption({label:'Current jobs'});await expect(rowFor(page,'Healthy closed provider')).toBeVisible();await expect(rowFor(page,'Legacy provider-free job')).toBeVisible();
});

test('deep links preserve exact disabled and finite identities while unknown requests do not fall back',async({page})=>{
  const historical=job('disabled-history','Archived acceptance task',{enabled:false,schedule:{kind:'once',at:'2026-11-02T15:00:00Z',grace_seconds:60},next_run_at:null});
  const finite=job('finite-link','Finite linked task',{schedule:{kind:'sequence',timestamps:['2026-11-02T17:00:00Z'],grace_seconds:60},next_run_at:'2026-11-02T17:00:00Z'});
  const jobs=[alpha,historical,finite];
  await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));
  await page.goto('/scheduler?job=disabled-history');
  await expect(page.getByRole('heading',{name:'Archived acceptance task',exact:true})).toBeVisible();
  await expect(rowFor(page,'Archived acceptance task')).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toHaveCount(0);
  await custody(page);await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  await page.goto('/scheduler?job=finite-link');await expect(page.getByRole('heading',{name:'Finite linked task',exact:true})).toBeVisible();
  await expect(rowFor(page,'Finite linked task')).toHaveAttribute('aria-pressed','true');
  await page.getByLabel('Find a job',{exact:true}).fill('alpha');await expect(jobRows(page)).toHaveCount(1);
  await expect(page.getByRole('heading',{name:'Finite linked task',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toBeVisible();
  await expect(page).not.toHaveURL(/job=finite-link/);
  await rowFor(page,'Alpha report').click();
  await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toBeVisible();await expect(page).toHaveURL(/job=alpha/);
  await page.goto('/scheduler?job=not-in-registry');
  await expect(page.getByRole('heading',{name:'Requested job not found',exact:true})).toBeVisible();
  await expect(page).toHaveURL(/job=not-in-registry/);
  await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toHaveCount(0);
  await expect(rowFor(page,'Alpha report')).toHaveAttribute('aria-pressed','false');
});

test('stale list, detail and preview remain explicitly labelled without cross-entity data',async({page})=>{
  const outputId='c'.repeat(64);
  const withMessage=job('stale-alpha','Retained report',{outputs:[{id:outputId,subject:'Retained message',status:'accepted',verified:true,created_at:stamp,verified_at:stamp,kind:'initial'}]});
  await fixtures(page,async p=>{
    const current={...withMessage,...(p.get('output')?{output:{id:outputId,subject:'Retained message',html:'<p>Retained safe content</p>',attachments:[]}}:{})};
    return {...packet([current]),projection_state:'stale'};
  });
  await page.goto('/scheduler');
  await expect(page.getByRole('alert').getByText('Some scheduler evidence is unavailable',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Retained report',exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-detail').getByText('Job evidence is incomplete',{exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-detail p').filter({hasText:'This job is showing a retained stale snapshot.'})).toContainText('This job is showing a retained stale snapshot.');
  await standardViews(page).getByRole('button',{name:'Saved messages (1)',exact:true}).click();
  await page.getByLabel('Saved message',{exact:true}).selectOption(outputId);
  await expect(page.locator('.scheduler-preview').getByText('Saved message evidence is incomplete',{exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-preview p').filter({hasText:'This preview is showing a retained stale snapshot.'})).toContainText('This preview is showing a retained stale snapshot.');
  await expect(page.frameLocator('iframe').getByText('Retained safe content')).toBeVisible();
  await page.unroute('**/api/scheduler*');
  await fixtures(page,async p=>p.get('job')?{...packet([alpha]),status:'partial'}:packet([alpha]));
  await page.goto('/scheduler');await expect(page.getByRole('heading',{name:'Alpha report',exact:true})).toBeVisible();
  await expect(page.locator('.scheduler-detail').getByText('Job evidence is incomplete',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Retained report',exact:true})).toHaveCount(0);
});

test('mentor refresh failure stays stale through retry and recovers only on success',async({page})=>{
  let mode='success', release;
  await fixtures(page,async(p,route)=>{
    if(!p.get('job'))return packet([mentor()]);
    if(mode==='fail'){await route.fulfill({status:503,json:{error:{message:'RESILIENCE_PRIVATE_CANARY'}}});return;}
    if(mode==='pending')await new Promise(resolve=>{release=resolve;});
    return packet([mentor()]);
  });
  await page.goto('/scheduler');
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  await expect(panel.getByRole('status')).toHaveText('Latest detail read succeeded. Evidence completeness is partial.');
  mode='fail';await page.getByRole('button',{name:'Refresh selected mentor job'}).click();
  await expect(page.locator('.mentor-detail').getByText('Mentor snapshot is stale',{exact:true})).toBeVisible();
  await expect(panel.getByRole('status')).toHaveText(/Retained stale snapshot/);
  await expect(page.getByText('RESILIENCE_PRIVATE_CANARY')).toHaveCount(0);
  mode='pending';await page.getByRole('button',{name:'Retry details'}).click();
  await expect(panel.getByRole('status')).toHaveText(/Updating retained stale snapshot/);
  await expect(panel.getByText('Current',{exact:true})).toHaveCount(0);
  release();
  await expect(panel.getByRole('status')).toHaveText('Latest detail read succeeded. Evidence completeness is partial.');
  await expect(page.locator('.mentor-detail').getByText('Mentor snapshot is stale',{exact:true})).toHaveCount(0);
});

test('resilience remains readable at 200 percent zoom and in forced colors without unsafe requests',async({page})=>{
  const requests=[];page.on('request',request=>requests.push({method:request.method(),url:request.url()}));
  await fixtures(page,async()=>packet([mentor()]));
  await page.setViewportSize({width:640,height:900});
  await page.emulateMedia({forcedColors:'active',reducedMotion:'reduce'});
  await page.goto('/scheduler');
  await rowFor(page,'Mentor scheduler acceptance').click();
  await page.evaluate(()=>{document.documentElement.style.zoom='2';});
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  for(const heading of ['Snapshot','Active work','Recovery','Host timing'])await expect(panel.getByRole('heading',{name:heading,exact:true})).toBeVisible();
  await expect(panel.locator('button, form, input, select, textarea')).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  expect(await panel.evaluate(node=>getComputedStyle(node).borderTopStyle)).not.toBe('none');
  expect(requests.every(request=>request.method==='GET')).toBe(true);
  expect(requests.every(request=>new URL(request.url).hostname==='localhost')).toBe(true);
});

test('resilience 26rem container rule applies inside a narrow desktop detail pane',async({page})=>{
  await fixtures(page,async()=>packet([mentor()]));
  await page.setViewportSize({width:1200,height:900});await page.goto('/scheduler');
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  await panel.evaluate(node=>{node.parentElement.style.inlineSize='380px';});
  await expect.poll(()=>panel.evaluate(node=>getComputedStyle(node.parentElement).inlineSize)).toBe('380px');
  await expect.poll(()=>panel.evaluate(node=>getComputedStyle(node).paddingInlineStart)).toBe('16px');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('mentor outer stale overrides inner current while partial remains separate',async({page})=>{
  let incomplete=false;
  await fixtures(page,async p=>p.get('job')?{...packet([mentor()]),...(incomplete?{status:'partial'}:{projection_state:'stale'})}:packet([mentor()]));
  await page.goto('/scheduler');
  const detail=page.locator('.mentor-detail');
  const panel=page.getByRole('region',{name:'Scheduler resilience evidence'});
  const freshness=panel.locator('dt').filter({hasText:/^Effective freshness$/}).locator('..').locator('dd');
  await expect(detail.getByText('Mentor snapshot is stale',{exact:true})).toBeVisible();
  await expect(freshness).toHaveText(/Retained stale snapshot/);
  await expect(freshness).not.toHaveText(/^Current$/);
  await expect(panel.getByRole('status')).toHaveText(/Retained stale snapshot/);
  incomplete=true;await page.getByRole('button',{name:'Refresh selected mentor job',exact:true}).click();
  await expect(detail.getByText('Mentor snapshot is incomplete',{exact:true})).toBeVisible();
  await expect(detail.getByText('Mentor snapshot is stale',{exact:true})).toHaveCount(0);
  await expect(panel.locator('dt').filter({hasText:/^Snapshot completeness$/}).locator('..').locator('dd')).toHaveText('Partial');
  await expect(freshness).toHaveText(/Current/);
});


test('mobile keyboard selection moves to job detail and back restores the selected row focus',async({page})=>{
  await fixtures(page,async p=>packet(p.get('job')?[p.get('job')==='beta'?beta:alpha]:[alpha,beta]));
  await page.setViewportSize({width:360,height:800});await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/scheduler');
  const row=rowFor(page,'Beta report');await row.focus();await page.keyboard.press('Enter');
  const heading=page.getByRole('heading',{name:'Beta report',exact:true});await expect(heading).toBeVisible();await expect(heading).toBeFocused();
  await expect(page.getByRole('region',{name:'Scheduled jobs'})).toBeHidden();
  await expect(standardViews(page).getByRole('button',{name:'Overview',exact:true})).toHaveAttribute('aria-pressed','true');
  await standardViews(page).getByRole('button',{name:'Prompt custody',exact:true}).focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('heading',{name:'Prompt custody',exact:true})).toBeVisible();
  const back=page.getByRole('button',{name:'Back to jobs',exact:true});await back.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('region',{name:'Scheduled jobs'})).toBeVisible();await expect(row).toBeFocused();await expect(row).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('mentor row and header prioritize unknown effects and failed sessions consistently while preserving independent outcomes',async({page})=>{
  const unknown=mentor({id:'mentor-unknown-alignment',title:'Unknown mentor outcome',mentor:{...mentorTruth,progress:{...mentorTruth.progress,pending_effects:1},runtime_acceptance:{execution:'failed',acceptance:'failed',model_turn:'unknown',email:'unknown'}}});
  const failedSession=mentor({id:'mentor-failed-session',title:'Failed mentor session',mentor:{...mentorTruth,work_order:{...mentorTruth.work_order,starts_at:'2026-11-02T15:00:00+00:00',ends_at:'2026-11-02T18:00:00+00:00',window_state:'open'},scheduler:{status:'ready',code:'MENTOR_JOB_CYCLE_BLOCKED',attempts:0,dispatch:'not_attempted'},session:{status:'failed',revision:0},gates:{...mentorTruth.gates,no_duplicate_dispatch:'not_verified',model_turn:'not_verified'},runtime_acceptance:{execution:'pending',acceptance:'pending',model_turn:'not_started',email:'pending'},recovery_timeline:[]}});
  const jobs=[unknown,failedSession];
  await fixtures(page,async p=>packet(p.get('job')?jobs.filter(item=>item.id===p.get('job')):jobs));
  const outcome=label=>page.locator('.mentor-detail .scheduler-outcomes dt').filter({hasText:new RegExp(`^${label}$`)}).locator('..').locator('dd .badge');
  const headerBadge=page.locator('.mentor-detail .scheduler-job-actions .badge');
  await page.goto('/scheduler');
  await expect(rowFor(page,'Unknown mentor outcome').locator('.scheduler-row-meta .badge')).toHaveText('Outcome unknown');
  await rowFor(page,'Unknown mentor outcome').click();await expect(headerBadge).toHaveText('Outcome unknown');
  for(const [label,state] of [['Execution','failed'],['Acceptance','failed'],['Model turn','unknown'],['Email','unknown']])await expect(outcome(label)).toHaveText(state);
  await expect(detailFact(page,'Pending effects')).toHaveText('1');
  await expect(rowFor(page,'Failed mentor session').locator('.scheduler-row-meta .badge')).toHaveText('Needs attention');
  await rowFor(page,'Failed mentor session').click();await expect(headerBadge).toHaveText('Needs attention');
  for(const [label,state] of [['Execution','pending'],['Acceptance','pending'],['Model turn','not started'],['Email','pending']])await expect(outcome(label)).toHaveText(state);
  await expect(detailFact(page,'Scheduler status').locator('.badge')).toHaveText('ready');
  await mentorViews(page).getByRole('button',{name:'Evidence and safeguards',exact:true}).click();
  await expect(detailFact(page,'Session').locator('.badge')).toHaveText('failed');await expect(headerBadge).toHaveText('Needs attention');
});
