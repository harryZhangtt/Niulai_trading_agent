// Owner-private service. Platform dispatch enforces access; never publish publicly.
const OBJECT='niulai-readonly-profile-v1', TTL=600000, ISSUER='https://openapi-oauth2.tigerfintech.com';
const SCOPES=new Set(['api.basic:read','api.account:read','api.trade:read','api.quote:read']);
const enc=new TextEncoder(),dec=new TextDecoder();
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b)));
const un64=s=>Uint8Array.from(atob(s),x=>x.charCodeAt(0));
const reply=(x,status=200)=>Response.json(x,{status,headers:{'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}});
class Failure extends Error {constructor(code,status=400){super(code);this.status=status}}
function require(ok,code,status=400){if(!ok)throw new Failure(code,status)}
async function key(env){return crypto.subtle.importKey('raw',un64(env.VAULT_KEY),'AES-GCM',false,['encrypt','decrypt'])}
async function seal(profile,env){const iv=crypto.getRandomValues(new Uint8Array(12));return {iv:b64(iv),data:b64(await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:enc.encode(OBJECT)},await key(env),enc.encode(JSON.stringify(profile))))}}
async function open(value,env){if(!value)return null;return JSON.parse(dec.decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:un64(value.iv),additionalData:enc.encode(OBJECT)},await key(env),un64(value.data))))}
function validateProfile(profile){
 require(profile && typeof profile.files==='object' && !Array.isArray(profile.files),'INVALID_PROFILE');
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
async function handler(request,env){
 require(env.BUCKET && env.VAULT_KEY,'STORE_NOT_CONFIGURED',503);const url=new URL(request.url),origin=request.headers.get('Origin');require(!origin || origin===url.origin,'CROSS_ORIGIN_REJECTED',403);
 if(request.method==='GET' && url.pathname==='/health'){const {row}=await read(env);return reply({schema:1,initialized:!!row.cipher,revision:row.revision,lease_busy:!!(row.lease && row.lease.until>Date.now()),last_committed_at:row.committed_at||null})}
 require(request.method==='POST','METHOD_NOT_ALLOWED',405);const text=await request.text();require(text.length<=120000,'REQUEST_TOO_LARGE',413);let body;try{body=JSON.parse(text)}catch{throw new Failure('INVALID_JSON')}
 const state=await read(env),row=state.row,now=Date.now();
 if(url.pathname==='/lease/acquire'){
  require(typeof body.request_id==='string' && /^[a-f0-9-]{36}$/.test(body.request_id),'INVALID_REQUEST_ID');
  if(row.lease && row.lease.until>now){require(row.lease.id===body.request_id,'PROFILE_BUSY',409);return reply({lease_id:row.lease.id,expires_at:row.lease.until,revision:row.revision,profile:await open(row.cipher,env)})}
  const next={...row,revision:row.revision+1,lease:{id:body.request_id,until:now+TTL}};await write(env,state,next);return reply({lease_id:next.lease.id,expires_at:next.lease.until,revision:next.revision,profile:await open(next.cipher,env)});
 }
 if(url.pathname==='/lease/checkpoint'){
  require(typeof body.commit_id==='string' && /^[a-f0-9-]{36}$/.test(body.commit_id),'INVALID_COMMIT_ID');if(row.last_commit===body.commit_id)return reply({committed:true,revision:row.revision,idempotent:true,released:!row.lease});
  require(row.lease && row.lease.id===body.lease_id && row.lease.until>now,'LEASE_REJECTED',409);validateProfile(body.profile);
  const next={...row,revision:row.revision+1,cipher:await seal(body.profile,env),committed_at:new Date(now).toISOString(),last_commit:body.commit_id,lease:body.release?null:{id:row.lease.id,until:now+TTL}};await write(env,state,next);return reply({committed:true,revision:next.revision,released:!next.lease});
 }
 if(url.pathname==='/lease/release'){require(row.lease && row.lease.id===body.lease_id,'LEASE_REJECTED',409);await write(env,state,{...row,revision:row.revision+1,lease:null});return reply({released:true})}
 throw new Failure('NOT_FOUND',404);
}
export default {async fetch(request,env){try{return await handler(request,env)}catch(e){return reply({error:e instanceof Failure?e.message:'STORE_OPERATION_FAILED'},e instanceof Failure?e.status:503)}}};
