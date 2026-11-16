import http from 'node:http';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const APP = path.join(ROOT, 'ui/datasource');
const MAX_BYTES = 2 * 1024 * 1024;

function codeError(code) { return Object.assign(new Error(code), { code }); }
const TRACE_FORBIDDEN_KEYS = /^(?:raw|raw_result|path|private_path|prompt|credentials?|token|secret|exception)$/i;
function safeTraceValue(value, depth = 0) {
  if (depth > 8) return false;
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return typeof value !== 'number' || Number.isFinite(value);
  if (Array.isArray(value)) return value.length <= 64 && value.every(item => safeTraceValue(item, depth + 1));
  if (!value || typeof value !== 'object' || Object.keys(value).length > 64) return false;
  return Object.entries(value).every(([key, item]) => !TRACE_FORBIDDEN_KEYS.test(key) && safeTraceValue(item, depth + 1));
}
export function validateDatasourceProjection(data) {
  if (!data || typeof data !== 'object' || data.schema_version !== 1 || !Array.isArray(data.sources) || data.status === 'unavailable') return false;
  if (!Array.isArray(data.comparisons)) return true;
  for (const comparison of data.comparisons) {
    const trace = comparison?.driver_trace;
    if (!trace) continue;
    if (!safeTraceValue(trace) || trace.checker_verdict !== 'pass' || !/^[a-f0-9]{64}$/.test(trace.checker_verdict_sha256 || '') ||
        !Array.isArray(trace.operations) || trace.operations.length < 1 || trace.operations.length > 8 ||
        !Array.isArray(trace.units) || trace.units.length !== 1 || trace.units[0]?.review_disposition !== 'approve' ||
        !Array.isArray(trace.missing_links) || trace.missing_links.length !== 0 ||
        trace.accounting?.complete_chains !== 1 || trace.accounting?.credited_units !== 1) return false;
  }
  return true;
}
function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' });
  res.end(JSON.stringify(data));
}

export function queryOptions(url) {
  const subject = (url.searchParams.get('subject') || 'NOW').trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9_.-]{0,31}$/.test(subject)) throw codeError('INVALID_SUBJECT');
  const limit = Number(url.searchParams.get('limit') || 100);
  const offset = Number(url.searchParams.get('offset') || 0);
  const snapshot = url.searchParams.get('snapshot_id');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0 || offset > 10000 ||
      (snapshot !== null && !/^[a-f0-9]{64}$/.test(snapshot))) throw codeError('INVALID_PAGINATION');
  return { subject, limit, offset, snapshot };
}

export class ProjectionBridge {
  constructor({ loader = null, ttl = 2000, timeout = 8000 } = {}) {
    this.loader = loader; this.ttl = ttl; this.timeout = timeout;
    this.cache = new Map(); this.pending = new Map(); this.children = new Set(); this.closed = false;
  }
  async load(options) {
    if (this.loader) return this.loader(options);
    const args = ['-B', '-m', 'investment.research.datasource', '--subject', options.subject,
      '--limit', String(options.limit), '--offset', String(options.offset)];
    if (options.snapshot) args.push('--snapshot-id', options.snapshot);
    return new Promise((resolve, reject) => {
      const child = execFile(path.join(ROOT, '.research-sources/.venv/bin/python'), args, {
        cwd: ROOT, timeout: this.timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES,
        env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', PYTHONPATH: ROOT, PYTHONDONTWRITEBYTECODE: '1',
          TMPDIR: path.join(ROOT, 'ui/runtime/tmp'), LANG: 'en_US.UTF-8' },
      }, (error, stdout) => {
        this.children.delete(child);
        let data;
        try { data = JSON.parse(stdout); } catch { reject(codeError('PROJECTION_UNAVAILABLE')); return; }
        if (data?.warnings?.some(w => w.code === 'PROJECTION_SNAPSHOT_CHANGED')) {
          reject(codeError('PROJECTION_SNAPSHOT_CHANGED')); return;
        }
        if (error || !validateDatasourceProjection(data)) {
          reject(codeError('PROJECTION_UNAVAILABLE')); return;
        }
        resolve(data);
      });
      this.children.add(child);
    });
  }
  async get(options, { force = false } = {}) {
    if (this.closed) throw codeError('SERVER_CLOSING');
    const key = JSON.stringify(options); const previous = this.cache.get(key);
    if (!force && previous && Date.now() - previous.at < this.ttl) return previous.data;
    if (this.pending.has(key)) return this.pending.get(key);
    if (this.pending.size >= 8) throw codeError('PROJECTION_BUSY');
    const promise = this.load(options).then(data => {
      if (this.cache.size >= 16 && !this.cache.has(key)) this.cache.delete(this.cache.keys().next().value);
      this.cache.set(key, { data, at: Date.now() }); return data;
    }).catch(error => {
      if (error.code === 'PROJECTION_SNAPSHOT_CHANGED' || error.code === 'SCHEDULER_PACKET_REJECTED' || !previous) throw error;
      return { ...previous.data, status: 'partial', projection_state: 'stale',
        warnings: [...previous.data.warnings, { code: 'PROJECTION_REFRESH_FAILED', count: 1 }] };
    }).finally(() => this.pending.delete(key));
    this.pending.set(key, promise); return promise;
  }
  close() { this.closed = true; for (const child of this.children) child.kill('SIGKILL'); this.children.clear(); }
}

export class FactorMiningBridge extends ProjectionBridge {
  constructor(options = {}) { super({ ttl: 3000, ...options }); }
  async load(options) {
    if (this.loader) return this.loader(options);
    const args = ['-B', '-m', 'shared.factor_mining.projection'];
    if (options.run) args.push('--run-id', options.run);
    if (options.manifest) args.push('--manifest-sha256', options.manifest);
    return new Promise((resolve, reject) => {
      const child = execFile(path.join(ROOT, '.job-runtime/.venv/bin/python'), args, {
        cwd: ROOT, timeout: this.timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES,
        env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', PYTHONPATH: ROOT,
          PYTHONDONTWRITEBYTECODE: '1', TMPDIR: path.join(ROOT, 'ui/runtime/tmp'), LANG: 'en_US.UTF-8' },
      }, (error, stdout) => {
        this.children.delete(child);
        let data;
        try { data = JSON.parse(stdout); } catch { reject(codeError('FACTOR_MINING_UNAVAILABLE')); return; }
        if (error || data?.schema_version !== 1 || data?.scope !== 'factor_mining' ||
            !Array.isArray(data.runs) || data.status === 'unavailable') {
          reject(codeError('FACTOR_MINING_UNAVAILABLE')); return;
        }
        resolve(data);
      });
      this.children.add(child);
    });
  }
}

export function informationYieldOptions(url) {
  const allowed = new Set(['evaluation', 'case', 'arm', 'run', 'source', 'refresh']);
  if ([...url.searchParams.keys()].some(key => !allowed.has(key))) throw codeError('INVALID_INFORMATION_YIELD_QUERY');
  const evaluation = url.searchParams.get('evaluation'); const caseId = url.searchParams.get('case');
  const arm = url.searchParams.get('arm'); const run = url.searchParams.get('run'); const source = url.searchParams.get('source');
  const safe = value => value === null || /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value);
  if (!evaluation || !safe(evaluation) || !safe(caseId) || !safe(run) || !safe(source) ||
      (arm !== null && !['B0', 'F'].includes(arm)) || (arm !== null && caseId === null) ||
      (run !== null && arm === null) || (source !== null && run === null)) throw codeError('INVALID_INFORMATION_YIELD_QUERY');
  return { evaluation, caseId, arm, run, source };
}
function canonicalInformationYield(value) {
  if (Array.isArray(value)) return value.map(canonicalInformationYield);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalInformationYield(value[key])]));
  return value;
}
function sameInformationYieldValue(left, right) { return JSON.stringify(canonicalInformationYield(left)) === JSON.stringify(canonicalInformationYield(right)); }
function reconciledInformationYieldFailures(data) {
  const visible = data.view === 'summary' ? data.cases : data.case ? [data.case] : [];
  const expected = []; const seen = new Set();
  for (const item of visible) for (const failure of item?.hard_failures || []) {
    if (!failure || typeof failure.code !== 'string' || !Array.isArray(failure.chain_ids) || failure.chain_ids.some(value => !/^[a-f0-9]{64}$/.test(value))) return null;
    const chain_ids = [...failure.chain_ids].sort(); if (new Set(chain_ids).size !== chain_ids.length) return null;
    const row = { case_id: item.case_id, code: failure.code, chain_ids }; const key = JSON.stringify(row); if (seen.has(key)) return null; seen.add(key); expected.push(row);
  }
  expected.sort((a,b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  if (new Set(data.hard_failures.map(row => JSON.stringify(row))).size !== data.hard_failures.length) return null;
  return sameInformationYieldValue(data.hard_failures, expected) ? expected : null;
}
function validateInformationYieldProjection(data, options) {
  if (!data || typeof data !== 'object' || data.schema_version !== 1 || data.read_only !== true ||
      data.evaluation_id !== options.evaluation || !['pass', 'reject', 'inconclusive'].includes(data.verdict) ||
      !data.outcomes || !Array.isArray(data.policy_gates) || !Array.isArray(data.hard_failures) || !Array.isArray(data.cases)) return false;
  const selection = data.selection; const failures = reconciledInformationYieldFailures(data);
  if (failures === null || (failures.length && data.verdict !== 'reject') || !selection || Object.keys(selection).length !== 4 ||
      selection.case_id !== options.caseId || selection.arm !== options.arm || selection.run !== options.run || selection.source !== options.source) return false;
  if (options.caseId === null) return data.view === 'summary' && data.case === null && data.selected_arm === null;
  if (data.view !== 'detail' || data.case?.case_id !== options.caseId) return false;
  if (options.arm === null) return data.selected_arm === null;
  return Boolean(data.case?.arms?.[options.arm]) && sameInformationYieldValue(data.selected_arm, data.case.arms[options.arm]);
}
const INFORMATION_YIELD_V5_GATE_NAMES = [
  'confirmation_cohort','richness_mean','richness_positive_cases','depth_mean','depth_positive_cases','case_delta_floor','issuer_loo','precision_delta','arm_wall_limit','case_wall_ratio','aggregate_wall_ratio','complete_trace_ratio','complete_pooled_review','zero_critical_unsupported','lineage','execution_custody','zero_hard_failures','unknown_semantics',
];
const INFORMATION_YIELD_V5_POLICY_SHA256='b25d0e9dd7fd5d1db6f95c1114a179d0963d2bc55b7ef839227364e300df887f';
const INFORMATION_YIELD_V5_GATE_AUTHORITY_SHA256='558c4add60096842836aa67472731785f869897bc662dcd873b740b08de16878';
const INFORMATION_YIELD_V5_CONFLICTS = new Set([
  'EIY_PROJECTION_V5_INDEX_INVALID','EIY_PROJECTION_V5_CUSTODY_INVALID','EIY_PROJECTION_V5_POLICY_MISMATCH',
  'EIY_PROJECTION_V5_CONTEXT_MISMATCH','EIY_PROJECTION_V5_RESULT_DRIFT','EIY_PROJECTION_V5_AUTHORITY_MISMATCH',
  'EIY_PROJECTION_V5_IDENTITY_CONFLICT','EIY_PROJECTION_V5_PRIVATE_FIELD','EIY_PROJECTION_V5_OUTPUT_LIMIT','INFORMATION_YIELD_V5_CONFLICT',
]);
export function informationYieldV5Options(url) {
  const allowed = new Set(['evaluation','case','arm','refresh']);
  if ([...url.searchParams.keys()].some(key => !allowed.has(key))) throw codeError('INVALID_INFORMATION_YIELD_V5_QUERY');
  const evaluation=url.searchParams.get('evaluation');const caseId=url.searchParams.get('case');const arm=url.searchParams.get('arm');
  const safe=value=>value===null||/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value);
  if(!evaluation||!safe(evaluation)||!safe(caseId)||(arm!==null&&!['B0','F'].includes(arm))||(arm!==null&&caseId===null)) throw codeError('INVALID_INFORMATION_YIELD_V5_QUERY');
  return {evaluation,caseId,arm};
}
function informationYieldV5Exact(value,keys){return value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));}
function informationYieldV5PrivateSafe(value,depth=0){
  if(depth>8)return false;if(value===null||['string','boolean'].includes(typeof value))return typeof value!=='string'||value.length<=512;
  if(typeof value==='number')return Number.isFinite(value);if(Array.isArray(value))return value.length<=256&&value.every(item=>informationYieldV5PrivateSafe(item,depth+1));
  if(!value||typeof value!=='object'||Object.keys(value).length>128)return false;
  const forbidden=/(?:^|_)(?:raw(?:_result)?|payload|prompt|credentials?|auth(?:entication|orization)?|token|secret|private|path|quote|exception|password|api_?key|access_?key)(?:$|_)/i;
  return Object.entries(value).every(([key,item])=>!forbidden.test(key)&&informationYieldV5PrivateSafe(item,depth+1));
}
export function validateInformationYieldV5Projection(data,options){
  const top=['wire_version','publication','view','evaluation_id','index_sha256','custody_sha256','result_sha256','verdict','counts','evidence','outcomes','populations','policy_gates','hard_failures','cases','selection','case','selected_arm','projection_state','read_only'];
  if(!informationYieldV5Exact(data,top)||!informationYieldV5PrivateSafe(data)||data.wire_version!=='information-yield-wire-5'||data.publication!=='information-yield-v5'||data.read_only!==true||data.evaluation_id!==options.evaluation)return false;
  if(!/^[a-f0-9]{64}$/.test(data.index_sha256)||!/^[a-f0-9]{64}$/.test(data.custody_sha256)||!/^[a-f0-9]{64}$/.test(data.result_sha256)||!['fresh','stale'].includes(data.projection_state))return false;
  const selection=data.selection;if(!informationYieldV5Exact(selection,['case_id','arm'])||selection.case_id!==options.caseId||selection.arm!==options.arm)return false;
  const counts=data.counts;if(!informationYieldV5Exact(counts,['planned','confirmation','development'])||counts.confirmation!==6||counts.planned!==counts.confirmation+counts.development)return false;
  const evidence=data.evidence;if(!informationYieldV5Exact(evidence,['context_sha256','fact_set_sha256','policy_sha256','gate_authority_sha256','source_closure_sha256','claim_limits','same_user_trust','same_user_limitations'])||evidence.policy_sha256!==INFORMATION_YIELD_V5_POLICY_SHA256||evidence.gate_authority_sha256!==INFORMATION_YIELD_V5_GATE_AUTHORITY_SHA256)return false;
  const populations=data.populations;if(!informationYieldV5Exact(populations,['C','D','E','N'])||!['C','D','E','N'].every(key=>Array.isArray(populations[key]))||populations.N.length||populations.C.length!==counts.confirmation||populations.D.length!==counts.development||JSON.stringify(populations.E)!==JSON.stringify([...populations.C,...populations.D]))return false;
  if(!Array.isArray(data.policy_gates)||data.policy_gates.length!==18)return false;
  for(let index=0;index<18;index++){
    const gate=data.policy_gates[index],population=index<8?'C':'E',decisive=index>=11&&index<=16;
    if(!informationYieldV5Exact(gate,['ordinal','name','population','decisive','population_case_ids','status','observed','threshold','numerator','denominator','case_results','reason_codes'])||gate.ordinal!==index+1||gate.name!==INFORMATION_YIELD_V5_GATE_NAMES[index]||gate.population!==population||gate.decisive!==decisive||JSON.stringify(gate.population_case_ids)!==JSON.stringify(populations[population])||!['pass','fail','unknown','not_applicable'].includes(gate.status))return false;
  }
  const decisiveFail=data.policy_gates.some(g=>g.decisive&&g.status==='fail');const unknown=data.policy_gates.some(g=>g.status==='unknown');const nondecisiveFail=data.policy_gates.some(g=>!g.decisive&&g.status==='fail');
  const verdict=decisiveFail?'reject':unknown||nondecisiveFail?'inconclusive':populations.C.length===6&&data.policy_gates.every(g=>g.status==='pass')?'pass':'inconclusive';if(data.verdict!==verdict)return false;
  if(options.caseId===null)return data.view==='summary'&&data.case===null&&data.selected_arm===null&&Array.isArray(data.cases)&&JSON.stringify(data.cases.map(row=>row.case_id))===JSON.stringify(populations.E);
  if(data.view!=='detail'||!data.case||data.case.case_id!==options.caseId||!Array.isArray(data.cases)||data.cases.length)return false;
  return options.arm===null?data.selected_arm===null:Boolean(data.case.arms?.[options.arm])&&sameInformationYieldValue(data.selected_arm,data.case.arms[options.arm]);
}
export class InformationYieldV5Bridge extends ProjectionBridge {
  constructor({enabled=process.env.INFORMATION_YIELD_V5_ENABLED==='1',...options}={}){super({ttl:3000,...options});this.enabled=enabled;}
  async load(options){
    if(!this.enabled)throw codeError('INFORMATION_YIELD_V5_DISABLED');
    if(this.loader){const data=await this.loader(options);if(!validateInformationYieldV5Projection(data,options))throw codeError('EIY_PROJECTION_V5_IDENTITY_CONFLICT');return data;}
    const args=['-B','-m','investment.research.information_yield_projection_v5','--evaluation-id',options.evaluation];if(options.caseId)args.push('--case-id',options.caseId);if(options.arm)args.push('--arm',options.arm);
    return new Promise((resolve,reject)=>{const child=execFile(path.join(ROOT,'.research-sources/.venv/bin/python'),args,{cwd:ROOT,timeout:this.timeout,killSignal:'SIGKILL',maxBuffer:MAX_BYTES,env:{PATH:'/usr/bin:/bin:/usr/sbin:/sbin',PYTHONPATH:ROOT,PYTHONDONTWRITEBYTECODE:'1',TMPDIR:path.join(ROOT,'ui/runtime/tmp'),LANG:'en_US.UTF-8'}},(error,stdout)=>{
      this.children.delete(child);let data;try{data=JSON.parse(stdout);}catch{reject(codeError('INFORMATION_YIELD_V5_UNAVAILABLE'));return;}
      if(error||data?.error){reject(codeError(data?.error?.code||'INFORMATION_YIELD_V5_UNAVAILABLE'));return;}if(!validateInformationYieldV5Projection(data,options)){reject(codeError('EIY_PROJECTION_V5_IDENTITY_CONFLICT'));return;}resolve(data);
    });this.children.add(child);});
  }
  async get(options,{force=false}={}){
    if(this.closed)throw codeError('SERVER_CLOSING');const key=JSON.stringify(options),previous=this.cache.get(key);if(!force&&previous&&Date.now()-previous.at<this.ttl)return previous.data;
    if(this.pending.has(key))return this.pending.get(key);if(this.pending.size>=8)throw codeError('PROJECTION_BUSY');
    const promise=this.load(options).then(data=>{if(this.cache.size>=16&&!this.cache.has(key))this.cache.delete(this.cache.keys().next().value);this.cache.set(key,{data,at:Date.now()});return data;}).catch(error=>{
      if(!previous||error.code==='INFORMATION_YIELD_V5_DISABLED'||error.code==='EIY_PROJECTION_V5_NOT_FOUND'||INFORMATION_YIELD_V5_CONFLICTS.has(error.code))throw error;
      return {...previous.data,projection_state:'stale'};
    }).finally(()=>this.pending.delete(key));this.pending.set(key,promise);return promise;
  }
}

export class InformationYieldBridge extends ProjectionBridge {
  constructor({ registryRef = process.env.INFORMATION_YIELD_REGISTRY_REF || null, ...options } = {}) {
    super({ ttl: 3000, ...options }); this.registryRef = registryRef;
  }
  async load(options) {
    if (this.loader) {
      const data = await this.loader(options);
      if (!validateInformationYieldProjection(data, options)) throw codeError('INFORMATION_YIELD_IDENTITY_CONFLICT');
      return data;
    }
    if (!this.registryRef) throw codeError('INFORMATION_YIELD_NOT_FOUND');
    const args = ['-B', '-m', 'investment.research.information_yield_projection', '--registry-ref', this.registryRef,
      '--evaluation-id', options.evaluation];
    if (options.caseId) args.push('--case-id', options.caseId); if (options.arm) args.push('--arm', options.arm);
    if (options.run) args.push('--run-id', options.run); if (options.source) args.push('--source-id', options.source);
    return new Promise((resolve, reject) => {
      const child = execFile(path.join(ROOT, '.research-sources/.venv/bin/python'), args, {
        cwd: ROOT, timeout: this.timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES,
        env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', PYTHONPATH: ROOT, PYTHONDONTWRITEBYTECODE: '1',
          TMPDIR: path.join(ROOT, 'ui/runtime/tmp'), LANG: 'en_US.UTF-8' },
      }, (error, stdout) => {
        this.children.delete(child); let data;
        try { data = JSON.parse(stdout); } catch { reject(codeError('INFORMATION_YIELD_UNAVAILABLE')); return; }
        if (error || data?.error) { reject(codeError(data?.error?.code || 'INFORMATION_YIELD_UNAVAILABLE')); return; }
        if (!validateInformationYieldProjection(data, options)) { reject(codeError('INFORMATION_YIELD_IDENTITY_CONFLICT')); return; }
        resolve(data);
      }); this.children.add(child);
    });
  }
  async get(options, { force = false } = {}) {
    if (this.closed) throw codeError('SERVER_CLOSING');
    const key = JSON.stringify(options); const previous = this.cache.get(key);
    if (!force && previous && Date.now() - previous.at < this.ttl) return previous.data;
    if (this.pending.has(key)) return this.pending.get(key); if (this.pending.size >= 8) throw codeError('PROJECTION_BUSY');
    const promise = this.load(options).then(data => {
      if (this.cache.size >= 16 && !this.cache.has(key)) this.cache.delete(this.cache.keys().next().value);
      this.cache.set(key, { data, at: Date.now() }); return data;
    }).catch(error => {
      if (!previous || ['EIY_PROJECTION_NOT_FOUND', 'EIY_PROJECTION_IDENTITY_CONFLICT', 'INFORMATION_YIELD_IDENTITY_CONFLICT', 'INFORMATION_YIELD_NOT_FOUND'].includes(error.code)) throw error;
      return { ...previous.data, projection_state: 'stale' };
    }).finally(() => this.pending.delete(key));
    this.pending.set(key, promise); return promise;
  }
}

const SCHEDULER_SECRET_KEY = /^(?:credentials?|password|passwd|secret|token|api[_-]?key|private[_-]?key|authorization|cookie)$/i;
const SCHEDULER_PAYLOAD_KEY = /^(?:prompt|artifact|artifact_ref|source|source_identity|binding|binding_hash|prompt_sha256)$/i;
const record = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, required, optional = []) => record(value) && required.every(key => key in value) &&
  Object.keys(value).every(key => required.includes(key) || optional.includes(key));
const member = (value, values) => typeof value === 'string' && values.includes(value);
const schedulerKeySafe = key => !SCHEDULER_SECRET_KEY.test(key) && !SCHEDULER_PAYLOAD_KEY.test(key);
function schedulerKeysSafe(value, depth = 0) {
  if (depth > 12) return false;
  if (value === null || ['string','boolean'].includes(typeof value)) return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.length <= 1000 && value.every(item => schedulerKeysSafe(item, depth + 1));
  if (!record(value) || Object.keys(value).length > 128) return false;
  return Object.entries(value).every(([key, item]) => schedulerKeySafe(key) && schedulerKeysSafe(item, depth + 1));
}
function validSchedule(value) {
  if (!record(value) || typeof value.kind !== 'string') return false;
  const keys = value.kind === 'daily' ? ['kind','timezone','times','grace_seconds'] : value.kind === 'interval' ? ['kind','seconds'] :
    value.kind === 'once' ? ['kind','at','grace_seconds'] : value.kind === 'sequence' ? ['kind','timestamps','grace_seconds'] : null;
  return Boolean(keys) && exactKeys(value, keys, value.kind === 'interval' ? ['grace_seconds'] : []);
}
const validDelivery = value => exactKeys(value, ['mode','next_send_at','note'], ['calendar']);
const validHistory = value => Array.isArray(value) && value.every(item => exactKeys(item, ['id','scheduled_at','updated_at','status','attempts','code']));
const validOutputs = value => Array.isArray(value) && value.every(item => exactKeys(item, ['id','subject','status','verified','created_at','verified_at','kind']));
function validProviderSafety(value) {
  if (!record(value)) return false;
  if (exactKeys(value, ['status'])) return value.status === 'unavailable';
  if (!exactKeys(value, ['status','provider','latest_attempt','delayed_until','delay_source','retry_reason','replay_authorization','circuit','unknown_fence','queue'])) return false;
  return value.status === 'available' && member(value.provider, ['codex_cli','claude_host']) &&
    (value.delay_source === null || member(value.delay_source, ['retry_after','backoff','circuit'])) &&
    member(value.replay_authorization, ['authorized','reconciliation_required','not_authorized','not_applicable','unavailable']) &&
    typeof value.unknown_fence === 'boolean' &&
    (value.latest_attempt === null || exactKeys(value.latest_attempt, ['phase','submission','terminal_proof','status','failure'])) &&
    exactKeys(value.circuit, ['state','open_until','probe_until','probe_eligible']) && exactKeys(value.queue, ['depth','oldest_delayed_at']);
}
function validCommonJob(job) {
  return validSchedule(job.schedule) && validDelivery(job.delivery) && validHistory(job.history) && validOutputs(job.outputs) &&
    (job.provider_safety === undefined || validProviderSafety(job.provider_safety));
}
function validStandardJob(job) {
  const required = ['id','title','description','enabled','schedule','next_run_at','replay_safe','model','effort','delivery','history','outputs','prompt_custody'];
  if (!exactKeys(job, required, ['output','provider_safety']) || !validCommonJob(job)) return false;
  const custody = job.prompt_custody;
  if (!exactKeys(custody, ['status','attempts_bound']) || !['bound','backfilled','legacy_unbound','unavailable'].includes(custody.status) ||
      !Number.isInteger(custody.attempts_bound) || custody.attempts_bound < 0) return false;
  if (job.output !== undefined && (!exactKeys(job.output, ['id','subject','html','attachments']) || !Array.isArray(job.output.attachments) ||
      !job.output.attachments.every(item => exactKeys(item, ['name','type'])))) return false;
  return true;
}
const boundedSchedulerCount = value => Number.isInteger(value) && value >= 0 && value <= 1000000;
function utcSchedulerInstant(value) {
  if (typeof value !== 'string') return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
  if (!match) return null;
  const year=Number(match[1]),month=Number(match[2]),day=Number(match[3]);
  const hour=Number(match[4]),minute=Number(match[5]),second=Number(match[6]);
  if (year < 1 || year > 9999 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return null;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
  if (day < 1 || day > days[month - 1]) return null;
  const microseconds=Number((match[7] || '').padEnd(6,'0'));
  return [year,month,day,hour,minute,second,microseconds];
}
function compareSchedulerInstants(left, right) {
  for (let index=0;index<left.length;index++) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}
function validResilience(value, packetGeneratedAt) {
  if (!exactKeys(value, ['generated_at','status','projection_state','scheduler','provider_safety','mentor','health']) ||
      value.generated_at !== packetGeneratedAt || utcSchedulerInstant(value.generated_at) === null ||
      !member(value.status, ['ok','partial']) || !member(value.projection_state, ['current','stale','unknown']) ||
      !exactKeys(value.scheduler, ['status','attempts']) ||
      !member(value.scheduler.status, ['ready','running','retry_wait','succeeded','failed','unknown','missed','coalesced']) ||
      !boundedSchedulerCount(value.scheduler.attempts)) return false;
  const provider = value.provider_safety;
  if (!exactKeys(provider, ['latest_attempt','delayed_until','delay_source','unknown_fence','replay_authorization']) ||
      (provider.latest_attempt !== null && (!exactKeys(provider.latest_attempt, ['phase','status']) ||
        !member(provider.latest_attempt.phase, ['not_started','connecting','submitted','streaming','terminal','unavailable']) ||
        !member(provider.latest_attempt.status, ['running','succeeded','retryable','failed','unknown']))) ||
      (provider.delay_source !== null && !member(provider.delay_source, ['retry_after','backoff','circuit'])) ||
      typeof provider.unknown_fence !== 'boolean' ||
      !member(provider.replay_authorization, ['authorized','reconciliation_required','not_authorized','not_applicable','unavailable'])) return false;
  const generatedAt = utcSchedulerInstant(value.generated_at);
  const delayedUntil = provider.delayed_until === null ? null : utcSchedulerInstant(provider.delayed_until);
  if ((provider.delayed_until === null) !== (provider.delay_source === null) ||
      (provider.delayed_until !== null && (delayedUntil === null || compareSchedulerInstants(delayedUntil,generatedAt) <= 0)) ||
      (provider.unknown_fence && ((provider.latest_attempt !== null && provider.latest_attempt.status !== 'unknown') ||
        !member(provider.replay_authorization, ['reconciliation_required','not_authorized']))) ||
      (!provider.unknown_fence && provider.replay_authorization === 'reconciliation_required')) return false;
  const mentor = value.mentor;
  if (!exactKeys(mentor, ['cycles','no_progress','repeated','evidence_reset']) || !boundedSchedulerCount(mentor.cycles) ||
      typeof mentor.evidence_reset !== 'boolean' || !exactKeys(mentor.no_progress, ['used','limit']) ||
      !exactKeys(mentor.repeated, ['used','limit']) ||
      !boundedSchedulerCount(mentor.no_progress.used) || !boundedSchedulerCount(mentor.no_progress.limit) ||
      !boundedSchedulerCount(mentor.repeated.used) || !boundedSchedulerCount(mentor.repeated.limit) ||
      mentor.no_progress.used > mentor.no_progress.limit || mentor.repeated.used > mentor.repeated.limit) return false;
  const health = value.health;
  return exactKeys(health, ['heartbeat_age_seconds','watchdog_healthy']) &&
    (health.heartbeat_age_seconds === null || typeof health.heartbeat_age_seconds === 'number' &&
      Number.isFinite(health.heartbeat_age_seconds) && health.heartbeat_age_seconds >= 0) &&
    (health.watchdog_healthy === null || typeof health.watchdog_healthy === 'boolean');
}

function validMentor(value, packetGeneratedAt) {
  if (!record(value)) return false;
  if (exactKeys(value, ['status'])) return value.status === 'unavailable';
  if (!exactKeys(value, ['work_order','scheduler','session','progress','safeguards','gates','evaluation','runtime_acceptance','recovery_timeline','resilience'])) return false;
  const p=value.progress;
  return exactKeys(value.work_order, ['id','logical_session_id','starts_at','ends_at','window_state','acceptance_criteria_total','required_event_kinds']) &&
    exactKeys(value.scheduler, ['status','code','attempts','dispatch']) && exactKeys(value.session, ['status','revision']) &&
    exactKeys(p, ['cycles','provider_threads','variants','interventions','reused_evaluations','pending_effects']) &&
    ['cycles','provider_threads','variants','interventions','reused_evaluations'].every(key => exactKeys(p[key], ['used','limit'])) &&
    exactKeys(value.safeguards, ['provider_thread_mode','record_all_variants','worker_holdout_access','require_no_pending_effects','configured_replay_safe','replay_authorization']) &&
    value.safeguards.replay_authorization === 'not_authorized' &&
    exactKeys(value.gates, ['future_wake','profile_binding','stop_propagation','model_turn','journal_cycle_postcondition','no_duplicate_dispatch']) &&
    ['future_wake','profile_binding','stop_propagation','model_turn','journal_cycle_postcondition','no_duplicate_dispatch']
      .every(key => member(value.gates[key], ['verified','failed','not_verified'])) &&
    exactKeys(value.evaluation, ['attempt_ledger_preserved','baseline','ablation','holdout','promotion']) &&
    exactKeys(value.runtime_acceptance, ['execution','acceptance','model_turn','email']) && Array.isArray(value.recovery_timeline) &&
    value.recovery_timeline.every(item => exactKeys(item, ['event','status','at'])) && validResilience(value.resilience, packetGeneratedAt);
}
function validMentorJob(job, packetGeneratedAt) {
  const required = ['id','title','description','enabled','schedule','next_run_at','replay_safe','model','effort','delivery','history','outputs','job_type','mentor'];
  return exactKeys(job, required, ['provider_safety']) && job.job_type === 'mentor' && validCommonJob(job) && validMentor(job.mentor, packetGeneratedAt);
}
export function validateSchedulerPacket(data) {
  const required = ['generated_at','health','jobs','provider_safety','read_only','schema_version','scope','status','warnings'];
  if (!exactKeys(data, required, ['projection_state']) || data.schema_version !== 1 || data.scope !== 'local_codex_scheduler' || data.read_only !== true ||
      !['ok','partial'].includes(data.status) || utcSchedulerInstant(data.generated_at) === null || !Array.isArray(data.jobs) || !Array.isArray(data.warnings) ||
      (data.projection_state !== undefined && data.projection_state !== 'stale') ||
      !exactKeys(data.health, ['state','heartbeat_at','watchdog_healthy'], ['heartbeat_age_seconds']) ||
      !exactKeys(data.provider_safety, ['status','jobs','available_jobs','unknown_fences','delayed_jobs','queue_depth','circuits']) ||
      !exactKeys(data.provider_safety.circuits, ['closed','open','half_open','unavailable']) ||
      !data.warnings.every(item => exactKeys(item, ['code'], ['job_id'])) || !schedulerKeysSafe(data)) return false;
  return data.jobs.every(job => record(job) && (job.job_type === 'mentor' ? validMentorJob(job, data.generated_at) : job.job_type === undefined && validStandardJob(job)));
}

export class SchedulerBridge extends ProjectionBridge {
  constructor(options = {}) { super({ ttl: 5000, ...options }); }
  async load(options) {
    if (this.loader) {
      const data = await this.loader(options);
      if (!validateSchedulerPacket(data)) throw codeError('SCHEDULER_PACKET_REJECTED');
      return data;
    }
    const args = ['-B', '-m', 'shared.job_runtime.dashboard'];
    if (options.job) args.push('--job-id', options.job);
    if (options.output) args.push('--output-id', options.output);
    return new Promise((resolve, reject) => {
      const child = execFile(path.join(ROOT, '.niulai-state/.venv/bin/python'), args, {
        cwd: ROOT, timeout: this.timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES,
        env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', PYTHONPATH: [ROOT, path.join(ROOT, 'niulai-runtime')].join(path.delimiter),
          PYTHONDONTWRITEBYTECODE: '1', TMPDIR: path.join(ROOT, 'ui/runtime/tmp'), LANG: 'en_US.UTF-8' },
      }, (error, stdout) => {
        this.children.delete(child);
        let data;
        try { data = JSON.parse(stdout); } catch { reject(codeError('SCHEDULER_UNAVAILABLE')); return; }
        if (error || !validateSchedulerPacket(data)) {
          reject(codeError(error ? 'SCHEDULER_UNAVAILABLE' : 'SCHEDULER_PACKET_REJECTED')); return;
        }
        resolve(data);
      });
      this.children.add(child);
    });
  }
}

export function factorMiningOptions(url) {
  const run = url.searchParams.get('run'); const manifest = url.searchParams.get('manifest');
  if ((run !== null && !/^[a-z0-9][a-z0-9_.-]{0,95}$/.test(run)) ||
      (manifest !== null && (!run || !/^[a-f0-9]{64}$/.test(manifest))) ||
      [...url.searchParams.keys()].some(key => !['run', 'manifest', 'refresh'].includes(key))) {
    throw codeError('INVALID_FACTOR_MINING_QUERY');
  }
  return { run, manifest };
}

export function schedulerOptions(url) {
  const job = url.searchParams.get('job'); const output = url.searchParams.get('output');
  if ((job !== null && !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$/.test(job)) ||
      (output !== null && (!job || !/^[a-f0-9]{64}$/.test(output))) ||
      [...url.searchParams.keys()].some(key => !['job', 'output', 'refresh'].includes(key))) throw codeError('INVALID_SCHEDULER_QUERY');
  return { job, output };
}

export async function identity() {
  const workspace = await realpath(ROOT);
  const files = await Promise.all(['server.mjs', 'dev.mjs'].map(name => readFile(path.join(APP, name))));
  return { app: 'trading-agent-datasource', workspace_id: createHash('sha256').update(workspace).digest('hex').slice(0, 16),
    server_fingerprint: createHash('sha256').update(Buffer.concat(files)).digest('hex') };
}

export async function health(port, host = '127.0.0.1') {
  return new Promise(resolve => {
    let req; let settled = false;
    const finish = value => { if (settled) return; settled = true; clearTimeout(timer); req?.destroy(); resolve(value); };
    const timer = setTimeout(() => finish(null), 700);
    try {
      req = http.get({ host, port, path: '/api/datasource/health', timeout: 700 }, res => {
        let data = '';
        res.on('data', chunk => { data += chunk; if (data.length > 8192) finish(null); });
        res.on('aborted', () => finish(null)); res.on('error', () => finish(null));
        res.on('end', () => { try { finish(JSON.parse(data)); } catch { finish(null); } });
      });
      req.on('timeout', () => finish(null)); req.on('error', () => finish(null));
    } catch { finish(null); }
  });
}

async function listen(server, port, host) {
  return new Promise((resolve, reject) => {
    const fail = error => { server.off('listening', ready); reject(error); };
    const ready = () => { server.off('error', fail); resolve(); };
    server.once('error', fail); server.once('listening', ready); server.listen({ host, port, exclusive: true });
  });
}

export async function start({ port = 7270, bridge = new ProjectionBridge(), scheduler = new SchedulerBridge(), factorMining = new FactorMiningBridge(), informationYield = new InformationYieldBridge(), informationYieldV5 = new InformationYieldV5Bridge(), viteFactory = null } = {}) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw codeError('INVALID_PORT');
  await mkdir(path.join(ROOT, 'ui/runtime/tmp'), { recursive: true });
  const owner = await identity(); let ready = false; let vite; let closing = false;
  const handler = (req, res) => {
    const host = req.headers.host || '';
    if (![ `localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}` ].includes(host)) {
      json(res, 403, { error: { code: 'LOCALHOST_ONLY' } }); return;
    }
    if (req.headers.origin && ![`http://localhost:${port}`, `http://127.0.0.1:${port}`, `http://[::1]:${port}`].includes(req.headers.origin)) {
      json(res, 403, { error: { code: 'ORIGIN_REJECTED' } }); return;
    }
    if (!['GET', 'HEAD'].includes(req.method)) { json(res, 405, { error: { code: 'READ_ONLY' } }); return; }
    let url; try { url = new URL(req.url, `http://localhost:${port}`); } catch { json(res, 400, { error: { code: 'INVALID_URL' } }); return; }
    if (url.pathname === '/api/datasource/health') {
      json(res, 200, { ...owner, status: ready ? 'ready' : 'starting', port, read_only: true }); return;
    }
    if (url.pathname === '/api/scheduler') {
      let options; try { options = schedulerOptions(url); } catch { json(res, 400, { error: { code: 'INVALID_SCHEDULER_QUERY' } }); return; }
      scheduler.get(options, { force: url.searchParams.get('refresh') === '1' })
        .then(data => json(res, 200, data))
        .catch(() => json(res, 503, { error: { code: 'SCHEDULER_UNAVAILABLE' } }));
      return;
    }
    if (url.pathname === '/api/information-yield/v5') {
      let options; try { options = informationYieldV5Options(url); } catch { json(res, 400, { error: { code: 'INVALID_INFORMATION_YIELD_V5_QUERY' } }); return; }
      informationYieldV5.get(options, { force: url.searchParams.get('refresh') === '1' }).then(data => json(res, 200, data)).catch(error => {
        const code=error.code;
        if(code==='INFORMATION_YIELD_V5_DISABLED')json(res,503,{error:{code:'INFORMATION_YIELD_V5_DISABLED'}});
        else if(code==='EIY_PROJECTION_V5_NOT_FOUND')json(res,404,{error:{code:'INFORMATION_YIELD_V5_NOT_FOUND'}});
        else if(INFORMATION_YIELD_V5_CONFLICTS.has(code))json(res,409,{error:{code:'INFORMATION_YIELD_V5_CONFLICT'}});
        else json(res,503,{error:{code:'INFORMATION_YIELD_V5_UNAVAILABLE'}});
      }); return;
    }
    if (url.pathname === '/api/information-yield') {
      let options; try { options = informationYieldOptions(url); } catch { json(res, 400, { error: { code: 'INVALID_INFORMATION_YIELD_QUERY' } }); return; }
      informationYield.get(options, { force: url.searchParams.get('refresh') === '1' }).then(data => json(res, 200, data)).catch(error => {
        const code = error.code;
        if (['EIY_PROJECTION_NOT_FOUND', 'INFORMATION_YIELD_NOT_FOUND'].includes(code)) json(res, 404, { error: { code: 'INFORMATION_YIELD_NOT_FOUND' } });
        else if (['EIY_PROJECTION_IDENTITY_CONFLICT', 'INFORMATION_YIELD_IDENTITY_CONFLICT'].includes(code)) json(res, 409, { error: { code: 'INFORMATION_YIELD_CONFLICT' } });
        else json(res, 503, { error: { code: 'INFORMATION_YIELD_UNAVAILABLE' } });
      }); return;
    }
    if (url.pathname === '/api/factor-mining') {
      let options; try { options = factorMiningOptions(url); } catch { json(res, 400, { error: { code: 'INVALID_FACTOR_MINING_QUERY' } }); return; }
      factorMining.get(options, { force: url.searchParams.get('refresh') === '1' })
        .then(data => json(res, 200, data))
        .catch(() => json(res, 503, { error: { code: 'FACTOR_MINING_UNAVAILABLE' } }));
      return;
    }
    if (url.pathname === '/api/datasource') {
      let options; try { options = queryOptions(url); } catch (error) { json(res, 400, { error: { code: error.code } }); return; }
      bridge.get(options, { force: url.searchParams.get('refresh') === '1' }).then(data => json(res, 200, data)).catch(error => {
        const changed = error.code === 'PROJECTION_SNAPSHOT_CHANGED';
        json(res, changed ? 409 : 503, { error: { code: changed ? error.code : 'PROJECTION_UNAVAILABLE' } });
      }); return;
    }
    if (url.pathname.startsWith('/api/')) { json(res, 404, { error: { code: 'NOT_FOUND' } }); return; }
    if (url.pathname === '/datasouce') { res.writeHead(308, { Location: `/datasource${url.search}` }); res.end(); return; }
    if (!ready) { json(res, 503, { error: { code: 'STARTING' } }); return; }
    if (url.pathname === '/') { res.writeHead(302, { Location: '/datasource' }); res.end(); return; }
    vite.middlewares(req, res, () => { res.writeHead(404); res.end('Not found'); });
  };
  const server = http.createServer(handler); const ipv6 = http.createServer(handler); const sockets = new Set();
  for (const listener of [server, ipv6]) {
    listener.maxConnections = 256;
    listener.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  }
  server.on('upgrade', (req, socket) => {
    const host = req.headers.host;
    const allowedHost = [`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`].includes(host);
    const allowedOrigin = !req.headers.origin || [`http://localhost:${port}`, `http://127.0.0.1:${port}`, `http://[::1]:${port}`].includes(req.headers.origin);
    if (!allowedHost || !allowedOrigin || req.headers['sec-websocket-protocol'] !== 'vite-hmr') socket.destroy();
  });
  server.requestTimeout = ipv6.requestTimeout = 15000;
  async function close() {
    if (closing) return; closing = true; ready = false; bridge.close(); scheduler.close(); factorMining.close(); informationYield.close(); informationYieldV5.close();
    // HTTP closeAllConnections excludes upgraded sockets. They are still ours.
    for (const socket of sockets) socket.destroy();
    if (vite) await vite.close();
    await Promise.all([server, ipv6].map(s => new Promise(resolve => {
      if (!s.listening) { resolve(); return; }
      s.close(resolve); s.closeIdleConnections(); s.closeAllConnections();
    })));
  }
  try {
    await listen(server, port, '127.0.0.1');
    try { await listen(ipv6, port, '::1'); } catch (error) {
      if (!['EAFNOSUPPORT', 'EADDRNOTAVAIL'].includes(error.code)) throw error;
    }
    ipv6.on('upgrade', (...args) => server.emit('upgrade', ...args));
    const create = viteFactory || (await import('vite')).createServer;
    vite = await create({ root: APP, publicDir: false, envPrefix: 'DATASOURCE_PUBLIC_',
      server: { middlewareMode: true, hmr: { server, clientPort: port },
        fs: { strict: true, allow: [APP, path.join(ROOT, 'node_modules'), path.join(ROOT, 'ui/runtime/datasource-vite-cache')],
          deny: ['**/.env*', '**/*.{pem,key,p12}', '**/.niulai-state/**', '**/.job-runtime/**',
            '**/niulai-private/**', '**/.research-sources/**', '**/mentor/runtime/**'] } } });
    ready = true;
    return { server, ipv6, bridge, scheduler, factorMining, informationYield, informationYieldV5, owner, close, port };
  } catch (error) { await close(); throw error; }
}
