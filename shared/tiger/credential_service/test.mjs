import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,mkdtempSync,rmSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import worker from './worker.js';
import rollback from './rollback-v1.js';
import {createHash} from 'node:crypto';

const tmpRoot=resolve('.niulai-state/tmp/credential-history-tests');mkdirSync(tmpRoot,{recursive:true,mode:0o700});
class Bucket {
 data=null; serial=0; puts=0;
 async get(){const data=this.data,etag=String(this.serial);return data?{etag,json:async()=>JSON.parse(data)}:null}
 async put(key,data,{onlyIf}){this.puts++;if(onlyIf.etagMatches && onlyIf.etagMatches!==String(this.serial))return null;if(onlyIf.etagDoesNotMatch==='*' && this.data)return null;this.data=data;this.serial++;return {etag:String(this.serial)}}
}
class DB {
 constructor(path=':memory:'){this.raw=new DatabaseSync(path);this.raw.exec(readFileSync(new URL('./drizzle/0000_credential_history.sql',import.meta.url),'utf8'));this.failBatch=false;this.corrupt=false}
 prepare(sql){const db=this;return {sql,args:[],bind(...args){this.args=args;return this},async first(){return db.raw.prepare(sql).get(...this.args)||null},async run(){return {success:true,meta:db.raw.prepare(sql).run(...this.args)}},async all(){return {results:db.raw.prepare(sql).all(...this.args)}}}}
 async batch(stmts){if(this.failBatch)throw new Error('SYNTHETIC-D1-SECRET');this.raw.exec('BEGIN IMMEDIATE');try{const values=stmts.map(s=>/^SELECT/.test(s.sql)?{results:this.raw.prepare(s.sql).all(...s.args)}:{success:true,meta:this.raw.prepare(s.sql).run(...s.args)});this.raw.exec('COMMIT');if(this.corrupt && values[1]?.results[0])values[1].results[0].profile_sha256='0'.repeat(64);return values}catch(e){this.raw.exec('ROLLBACK');throw e}}
 close(){this.raw.close()}
}
const profile=value=>({files:{'tokens/test.json':JSON.stringify({issuer:'https://openapi-oauth2.tigerfintech.com',access_token:value,refresh_token:'SYNTHETIC-REFRESH',scope:'api.basic:read api.account:read api.trade:read'})}});
function env(){return {BUCKET:new Bucket(),DB:new DB(),VAULT_KEY:btoa(String.fromCharCode(...new Uint8Array(32).fill(17)))}}
async function call(e,path,body,ctx){return worker.fetch(new Request('https://owner.test'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)}),e,ctx)}
async function acquired(e){const id=crypto.randomUUID();assert.equal((await call(e,'/lease/acquire',{request_id:id})).status,200);return id}
function context(){const jobs=[];return {jobs,waitUntil(p){jobs.push(p)},async complete(){await Promise.all(jobs)}}}
async function committed(e,lease=undefined,value='SYNTHETIC-ACCESS',release=true){lease=lease||await acquired(e);const id=crypto.randomUUID(),body={lease_id:lease,commit_id:id,profile:profile(value),release},ctx=context();const response=await call(e,'/lease/checkpoint',body,ctx);return {lease,id,body,ctx,response}}

test('CH-01 profile and pending receipt share one durable checkpoint before DB projection',async()=>{
 const e=env();e.DB.failBatch=true;const c=await committed(e);assert.equal(c.response.status,200);await c.ctx.complete();
 const row=JSON.parse(e.BUCKET.data);assert.equal(row.last_commit,c.id);assert.equal(row.history_pending[0].commit_id,c.id);assert.equal(row.history_pending[0].lease_id,c.lease);assert.ok(!e.BUCKET.data.includes('SYNTHETIC-ACCESS'));
 const h=await (await call(e,'/history/commits/'+c.id)).json();assert.equal(h.projection,'pending');assert.equal(h.receipt.profile_sha256.length,64);e.DB.close();
});
test('CH-02 historical replay survives later commits; changed lease/profile/release reject',async()=>{
 const e=env(),one=await committed(e);await one.ctx.complete();const two=await committed(e,undefined,'SYNTHETIC-SECOND');await two.ctx.complete();
 const serial=e.BUCKET.serial;const again=await call(e,'/lease/checkpoint',one.body);assert.equal(again.status,200);assert.equal((await again.json()).idempotent,true);
 for(const wrong of [{...one.body,lease_id:crypto.randomUUID()},{...one.body,profile:profile('SYNTHETIC-DIFFERENT')},{...one.body,release:false}])assert.equal((await call(e,'/lease/checkpoint',wrong)).status,409);
 assert.equal(e.BUCKET.serial,serial);e.DB.close();
});
test('CH-03 SQLite projection verified before CAS prune; no tokens enter database',async()=>{
 const e=env(),c=await committed(e);await c.ctx.complete();assert.equal(JSON.parse(e.BUCKET.data).history_pending.length,0);
 const h=await (await call(e,'/history/commits/'+c.id)).json();assert.equal(h.projection,'database');assert.equal(h.receipt.lease_id,c.lease);
 const all=JSON.stringify(e.DB.raw.prepare('SELECT * FROM credential_commit_receipts').all());assert.ok(!all.includes('SYNTHETIC'));assert.ok(!all.includes('access_token'));e.DB.close();
});
test('CH-03 mismatch and lost projection response preserve pending; fresh flush recovers',async()=>{
 for(const mode of ['failBatch','corrupt']){const e=env();e.DB[mode]=true;const c=await committed(e);await c.ctx.complete();assert.equal(JSON.parse(e.BUCKET.data).history_pending.length,1);e.DB[mode]=false;assert.equal((await call(e,'/history/flush',{})).status,200);assert.equal(JSON.parse(e.BUCKET.data).history_pending.length,0);assert.equal(e.DB.raw.prepare('SELECT COUNT(*) AS n FROM credential_commit_receipts').get().n,1);e.DB.close()}
});
test('CH-03 concurrent R2 change while projecting prevents stale prune',async()=>{
 const e=env();e.DB.failBatch=true;const c=await committed(e);await c.ctx.complete();e.DB.failBatch=false;
 const batch=e.DB.batch.bind(e.DB);e.DB.batch=async statements=>{const result=await batch(statements);const row=JSON.parse(e.BUCKET.data);row.revision++;e.BUCKET.data=JSON.stringify(row);e.BUCKET.serial++;return result};
 assert.equal((await call(e,'/history/flush',{})).status,409);assert.equal(JSON.parse(e.BUCKET.data).history_pending.length,1);e.DB.close();
});
test('CH-04 bounded backlog denies before another credential write',async()=>{
 const e=env();e.DB.failBatch=true;const c=await committed(e,undefined,'SYNTHETIC-ONE',false);await c.ctx.complete();
 const row=JSON.parse(e.BUCKET.data),base=row.history_pending[0];row.history_pending=Array.from({length:256},(_,i)=>({...base,commit_id:crypto.randomUUID(),revision:i+1}));e.BUCKET.data=JSON.stringify(row);const serial=e.BUCKET.serial;
 const next={...c.body,commit_id:crypto.randomUUID(),profile:profile('SYNTHETIC-NEW')};const response=await call(e,'/lease/checkpoint',next);assert.equal(response.status,503);assert.equal((await response.json()).error,'HISTORY_BACKPRESSURE');assert.equal(e.BUCKET.serial,serial);e.DB.close();
});
test('CH-05 health/history/summary reads do not mutate R2 or SQLite',async()=>{
 const e=env(),c=await committed(e);await c.ctx.complete();const serial=e.BUCKET.serial,changes=e.DB.raw.prepare('SELECT total_changes() AS n').get().n;
 for(const path of ['/health','/history/summary','/history/commits/'+c.id,'/history/commits/'+crypto.randomUUID()]){const response=await call(e,path);const text=await response.text();assert.ok(!text.includes('SYNTHETIC'));assert.ok(!text.includes('cipher'));assert.ok([200,404].includes(response.status))}
 assert.equal(e.BUCKET.serial,serial);assert.equal(e.DB.raw.prepare('SELECT total_changes() AS n').get().n,changes);e.DB.close();
});
test('CH-06 activation is immutable unverified baseline with no credential change',async()=>{
 const e=env(),id=crypto.randomUUID(),before=e.BUCKET.data;let response=await call(e,'/history/activate',{activation_id:id});assert.equal(response.status,200);assert.equal((await response.json()).legacy_history_verified,false);
 response=await call(e,'/history/activate',{activation_id:id});assert.equal((await response.json()).idempotent,true);assert.equal(e.BUCKET.data,before);assert.equal(e.DB.raw.prepare('SELECT COUNT(*) AS n FROM credential_history_activation').get().n,1);e.DB.close();
});
test('CH-07 unknown legacy commit is not invented; acquire concurrency has one winner',async()=>{
 const e=env(),lease=await acquired(e),old=crypto.randomUUID();const row=JSON.parse(e.BUCKET.data);row.last_commit=old;e.BUCKET.data=JSON.stringify(row);
 const response=await call(e,'/lease/checkpoint',{lease_id:lease,commit_id:old,profile:profile('SYNTHETIC'),release:true});assert.equal(response.status,409);assert.equal((await response.json()).error,'LEGACY_COMMIT_HISTORY_UNAVAILABLE');
 const f=env(),results=await Promise.all(Array.from({length:10},()=>call(f,'/lease/acquire',{request_id:crypto.randomUUID()})));assert.equal(results.filter(x=>x.status===200).length,1);e.DB.close();f.DB.close();
});
test('CH-08 SQLite file persists metadata after fresh connection restart',async()=>{
 const folder=mkdtempSync(resolve(tmpRoot,'run-'));try{const path=resolve(folder,'history.sqlite'),e=env();e.DB.close();e.DB=new DB(path);const c=await committed(e);await c.ctx.complete();e.DB.close();
 const fresh=new DatabaseSync(path),row=fresh.prepare('SELECT * FROM credential_commit_receipts WHERE commit_id=?').get(c.id);assert.equal(row.lease_id,c.lease);fresh.close();
 }finally{rmSync(folder,{recursive:true,force:true})}
});
test('CH-07 exact rollback owner still decrypts profile and preserves pending journal',async()=>{
 assert.equal(createHash('sha256').update(readFileSync(new URL('./rollback-v1.js',import.meta.url))).digest('hex'),'ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0');
 const e=env();e.DB.failBatch=true;const c=await committed(e);await c.ctx.complete();
 const response=await rollback.fetch(new Request('https://owner.test/lease/acquire',{method:'POST',body:JSON.stringify({request_id:crypto.randomUUID()})}),e);
 assert.equal(response.status,200);assert.deepEqual((await response.json()).profile,profile('SYNTHETIC-ACCESS'));
 assert.equal(JSON.parse(e.BUCKET.data).history_pending[0].commit_id,c.id);e.DB.close();
});
