// Same owner-private R2 profile. D1 contains immutable metadata only.
const OBJECT='niulai-readonly-profile-v1', TTL=600000, MAX_PENDING=256;
const ISSUER='https://openapi-oauth2.tigerfintech.com';
const SCOPES=new Set(['api.basic:read','api.account:read','api.trade:read','api.quote:read']);
const UUID=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const HEX=/^[a-f0-9]{64}$/;
const enc=new TextEncoder(),dec=new TextDecoder();
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b)));
const un64=s=>Uint8Array.from(atob(s),x=>x.charCodeAt(0));
class Failure extends Error{constructor(code,status=400){super(code);this.status=status}}
function require(ok,code,status=400){if(!ok)throw new Failure(code,status)}
const reply=(x,status=200)=>Response.json(x,{status,headers:{'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}});
const digest=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',enc.encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
const canonicalProfile=profile=>JSON.stringify({files:Object.fromEntries(Object.entries(profile.files).sort(([a],[b])=>a<b?-1:a>b?1:0))});
async function key(env){return crypto.subtle.importKey('raw',un64(env.VAULT_KEY),'AES-GCM',false,['encrypt','decrypt'])}
async function seal(profile,env){const iv=crypto.getRandomValues(new Uint8Array(12));return {iv:b64(iv),data:b64(await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(OBJECT)},await key(env),enc.encode(JSON.stringify(profile))))}}
async function open(value,env){if(!value)return null;return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:un64(value.iv),additionalData:enc.encode(OBJECT)},await key(env),un64(value.data))))}
function validateProfile(profile){
 require(profile && Object.keys(profile).length===1 && Object.hasOwn(profile,'files') && typeof profile.files==='object' && !Array.isArray(profile.files),'INVALID_PROFILE');
 const entries=Object.entries(profile.files);require(entries.length>0 && entries.length<=20,'INVALID_FILE_COUNT');let tokens=0,total=0;
 for(const [path,content] of entries){
  require(/^[a-zA-Z0-9_.\/-]+\.json$/.test(path) && !path.startsWith('/') && !path.split('/').includes('..'),'INVALID_PATH');
  require(typeof content==='string','INVALID_CONTENT');total+=content.length;require(total<=100000,'PROFILE_TOO_LARGE');const item=JSON.parse(content);
  if(item.access_token){tokens++;require(item.issuer===ISSUER,'ISSUER_REJECTED');const scopes=new Set(String(item.scope||'').split(/\s+/));require(scopes.size>=3 && [...scopes].every(x=>SCOPES.has(x)) && ['api.basic:read','api.account:read','api.trade:read'].every(x=>scopes.has(x)),'SCOPE_REJECTED')}
 }
 require(tokens===1,'EXACTLY_ONE_AUTHORIZATION_REQUIRED');
}
async function read(env){const object=await env.BUCKET.get(OBJECT);return {etag:object?.etag,row:object?await object.json():{schema:1,revision:0,cipher:null,lease:null,last_commit:null}}}
async function write(env,state,row){const object=await env.BUCKET.put(OBJECT,JSON.stringify(row),{onlyIf:state.etag?{etagMatches:state.etag}:{etagDoesNotMatch:'*'},httpMetadata:{contentType:'application/json'}});require(!!object,'STATE_CONFLICT',409)}
const FIELDS=['commit_id','lease_id','profile_sha256','request_sha256','revision','committed_at','release_requested','protocol'];
function receipt(value){
 require(value && Object.keys(value).sort().join('|')===[...FIELDS].sort().join('|'),'HISTORY_RECEIPT_INVALID',503);
 require(UUID.test(value.commit_id) && UUID.test(value.lease_id) && HEX.test(value.profile_sha256) && HEX.test(value.request_sha256)
  && Number.isSafeInteger(value.revision) && value.revision>=0 && typeof value.committed_at==='string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value.committed_at)
  && typeof value.release_requested==='boolean' && value.protocol===2,'HISTORY_RECEIPT_INVALID',503);
 return Object.fromEntries(FIELDS.map(k=>[k,value[k]]));
}
function fromDatabase(row){if(!row)return null;require(row.release_requested===0 || row.release_requested===1,'HISTORY_RECEIPT_INVALID',503);return receipt({...row,release_requested:row.release_requested===1})}
function same(a,b){return FIELDS.every(k=>a[k]===b[k])}
function pending(row){require(!row.history_pending || Array.isArray(row.history_pending),'HISTORY_PENDING_INVALID',503);const values=(row.history_pending||[]).map(receipt);require(values.length<=MAX_PENDING && new Set(values.map(x=>x.commit_id)).size===values.length,'HISTORY_PENDING_INVALID',503);return values}
async function lookup(env,row,id){
 const p=pending(row).find(x=>x.commit_id===id);if(p)return {value:p,projection:'pending'};
 require(env.DB,'HISTORY_DATABASE_NOT_CONFIGURED',503);
 const value=fromDatabase(await env.DB.prepare('SELECT commit_id,lease_id,profile_sha256,request_sha256,revision,committed_at,release_requested,protocol FROM credential_commit_receipts WHERE commit_id=?').bind(id).first());
 return value?{value,projection:'database'}:null;
}
async function project(env){
 require(env.DB,'HISTORY_DATABASE_NOT_CONFIGURED',503);
 const before=await read(env),values=pending(before.row).slice(0,32);
 if(!values.length)return {projected:0,pending:0};
 const statements=[];
 for(const e of values){
  statements.push(env.DB.prepare('INSERT OR IGNORE INTO credential_commit_receipts(commit_id,lease_id,profile_sha256,request_sha256,revision,committed_at,release_requested,protocol) VALUES(?,?,?,?,?,?,?,?)').bind(e.commit_id,e.lease_id,e.profile_sha256,e.request_sha256,e.revision,e.committed_at,e.release_requested?1:0,e.protocol));
  statements.push(env.DB.prepare('SELECT commit_id,lease_id,profile_sha256,request_sha256,revision,committed_at,release_requested,protocol FROM credential_commit_receipts WHERE commit_id=?').bind(e.commit_id));
 }
 const results=await env.DB.batch(statements);
 require(Array.isArray(results) && results.length===statements.length,'HISTORY_PROJECTION_UNCONFIRMED',503);
 for(let i=0;i<values.length;i++){const stored=fromDatabase(results[i*2+1]?.results?.[0]);require(stored && same(values[i],stored),'HISTORY_PROJECTION_MISMATCH',503)}
 // Never prune a state observed after our DB batch, or an unconfirmed batch.
 const ids=new Set(values.map(x=>x.commit_id));
 await write(env,before,{...before.row,revision:before.row.revision+1,history_pending:pending(before.row).filter(x=>!ids.has(x.commit_id))});
 return {projected:values.length,pending:pending(before.row).length-values.length};
}
function scheduleProjection(env,ctx){const job=project(env).catch(()=>null);if(ctx?.waitUntil)ctx.waitUntil(job);return job}
function acknowledgement(e,idempotent){return {committed:true,revision:e.revision,idempotent,released:e.release_requested,history_protocol:2}}
async function activate(env,body,row){
 require(env.DB,'HISTORY_DATABASE_NOT_CONFIGURED',503);require(Object.keys(body).length===1 && UUID.test(body.activation_id),'INVALID_ACTIVATION_ID');
 const existing=await env.DB.prepare('SELECT activation_id,observed_revision,observed_at,record_type FROM credential_history_activation WHERE activation_id=?').bind(body.activation_id).first();
 if(existing)return {activated:true,...existing,idempotent:true,legacy_history_verified:false};
 const at=new Date().toISOString(),cipherHash=await digest(JSON.stringify(row.cipher||null));
 await env.DB.prepare('INSERT OR IGNORE INTO credential_history_activation(activation_id,observed_revision,observed_at,record_type,legacy_head_commit_id,cipher_sha256,protocol) VALUES(?,?,?,?,?,?,2)').bind(body.activation_id,row.revision,at,'observed_legacy_baseline',row.last_commit||null,cipherHash).run();
 const stored=await env.DB.prepare('SELECT activation_id,observed_revision,observed_at,record_type FROM credential_history_activation WHERE activation_id=?').bind(body.activation_id).first();
 require(stored,'HISTORY_ACTIVATION_UNCONFIRMED',503);return {activated:true,...stored,idempotent:false,legacy_history_verified:false};
}
async function handler(request,env,ctx){
 require(env.BUCKET && env.VAULT_KEY,'STORE_NOT_CONFIGURED',503);const url=new URL(request.url),origin=request.headers.get('Origin');require(!origin || origin===url.origin,'CROSS_ORIGIN_REJECTED',403);require(!url.search,'QUERY_REJECTED');
 if(request.method==='GET'){
  const {row}=await read(env);
  if(url.pathname==='/health')return reply({schema:1,initialized:!!row.cipher,revision:row.revision,lease_busy:!!(row.lease && row.lease.until>Date.now()),last_committed_at:row.committed_at||null,history_protocol:2,history_pending:pending(row).length,database_configured:!!env.DB});
  const match=url.pathname.match(/^\/history\/commits\/([a-f0-9-]+)$/);
  if(match){require(UUID.test(match[1]),'INVALID_COMMIT_ID');const found=await lookup(env,row,match[1]);return found?reply({status:'found',receipt:found.value,projection:found.projection}):reply({status:'not_recorded',legacy_history_verified:false},404)}
  if(url.pathname==='/history/summary'){
   require(env.DB,'HISTORY_DATABASE_NOT_CONFIGURED',503);
   const count=await env.DB.prepare('SELECT COUNT(*) AS count FROM credential_commit_receipts').first();
   const activation=await env.DB.prepare('SELECT COUNT(*) AS count FROM credential_history_activation').first();
   require(Number.isSafeInteger(count?.count) && Number.isSafeInteger(activation?.count),'HISTORY_DATABASE_INVALID',503);
   return reply({protocol:2,receipt_count:count.count,activation_count:activation.count,pending_count:pending(row).length,legacy_history_verified:false});
  }
  throw new Failure('NOT_FOUND',404);
 }
 require(request.method==='POST','METHOD_NOT_ALLOWED',405);const text=await request.text();require(text.length<=120000,'REQUEST_TOO_LARGE',413);let body;try{body=JSON.parse(text)}catch{throw new Failure('INVALID_JSON')}
 require(body && typeof body==='object' && !Array.isArray(body),'INVALID_BODY');
 const state=await read(env),row=state.row,now=Date.now();
 if(url.pathname==='/history/activate')return reply(await activate(env,body,row));
 if(url.pathname==='/history/flush'){require(Object.keys(body).length===0,'INVALID_BODY');return reply(await project(env))}
 if(url.pathname==='/lease/acquire'){
  require(Object.keys(body).length===1 && UUID.test(body.request_id),'INVALID_REQUEST_ID');
  if(row.lease && row.lease.until>now){require(row.lease.id===body.request_id,'PROFILE_BUSY',409);return reply({lease_id:row.lease.id,expires_at:row.lease.until,revision:row.revision,profile:await open(row.cipher,env)})}
  const next={...row,revision:row.revision+1,lease:{id:body.request_id,until:now+TTL}};await write(env,state,next);return reply({lease_id:next.lease.id,expires_at:next.lease.until,revision:next.revision,profile:await open(next.cipher,env)});
 }
 if(url.pathname==='/lease/checkpoint'){
  require(UUID.test(body.commit_id) && UUID.test(body.lease_id),'INVALID_COMMIT_ID');
  require(Object.keys(body).every(k=>['commit_id','lease_id','profile','release'].includes(k)) && (body.release===undefined || typeof body.release==='boolean'),'INVALID_BODY');
  validateProfile(body.profile);const profileHash=await digest(canonicalProfile(body.profile));
  const requestHash=await digest(JSON.stringify({commit_id:body.commit_id,lease_id:body.lease_id,profile_sha256:profileHash,release:!!body.release}));
  const old=await lookup(env,row,body.commit_id);
  if(old){require(old.value.lease_id===body.lease_id && old.value.request_sha256===requestHash,'COMMIT_IDENTITY_CONFLICT',409);return reply(acknowledgement(old.value,true))}
  require(row.last_commit!==body.commit_id,'LEGACY_COMMIT_HISTORY_UNAVAILABLE',409);
  require(row.lease && row.lease.id===body.lease_id && row.lease.until>now,'LEASE_REJECTED',409);
  const queue=pending(row);require(queue.length<MAX_PENDING,'HISTORY_BACKPRESSURE',503);
  const e=receipt({commit_id:body.commit_id,lease_id:body.lease_id,profile_sha256:profileHash,request_sha256:requestHash,revision:row.revision+1,committed_at:new Date(now).toISOString(),release_requested:!!body.release,protocol:2});
  const next={...row,revision:e.revision,cipher:await seal(body.profile,env),committed_at:e.committed_at,last_commit:e.commit_id,lease:body.release?null:{id:row.lease.id,until:now+TTL},history_protocol:2,history_pending:[...queue,e]};
  await write(env,state,next);scheduleProjection(env,ctx);return reply(acknowledgement(e,false));
 }
 if(url.pathname==='/lease/release'){require(Object.keys(body).length===1 && row.lease && row.lease.id===body.lease_id,'LEASE_REJECTED',409);await write(env,state,{...row,revision:row.revision+1,lease:null});return reply({released:true})}
 throw new Failure('NOT_FOUND',404);
}
export default {async fetch(request,env,ctx){try{return await handler(request,env,ctx)}catch(e){return reply({error:e instanceof Failure?e.message:'STORE_OPERATION_FAILED'},e instanceof Failure?e.status:503)}}};
