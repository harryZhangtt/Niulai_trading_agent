// Manual-only portal; not registered with the active host MCP configuration.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { AjvJsonSchemaValidator } from '@modelcontextprotocol/sdk/validation/ajv';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { PortalError } from '../core/errors.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const securityTypes = { type: 'array', minItems: 1, maxItems: 4, uniqueItems: true,
  items: { type: 'string', enum: ['STK', 'OPT', 'FUT', 'FUND'] } };
const hex = '^[0-9a-f]{64}$';
const selectionQueryRecordSchema = { type: 'object', additionalProperties: false,
  required: ['entity_id', 'roster_row_sha256', 'security_class', 'symbol', 'venue'],
  properties: { entity_id: { type: 'string', pattern: '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' },
    roster_row_sha256: { type: 'string', pattern: hex }, security_class: { enum: ['COMMON_STOCK', 'ADR', 'CLASS_SHARE', 'ETF', 'FUND', 'OTHER'] },
    symbol: { type: 'string', pattern: '^[A-Z][A-Z0-9.-]{0,14}$' }, venue: { enum: ['NASDAQ', 'NYSE', 'NYSEARCA', 'NYSEAMERICAN', 'BATS'] } } };
const selectionDetailRecordSchema = { type: 'object', additionalProperties: false,
  required: ['entity_id', 'query_roster_binding_sha256', 'rank', 'rank_sha', 'roster_row_sha256', 'security_class', 'symbol', 'venue'],
  properties: { ...selectionQueryRecordSchema.properties, query_roster_binding_sha256: { type: 'string', pattern: hex },
    rank: { type: 'integer', minimum: 1 }, rank_sha: { type: 'string', pattern: hex } } };
const selectionRefSchema = { type: 'object', additionalProperties: false, required: ['bytes', 'path', 'sha256'],
  properties: { bytes: { type: 'integer', minimum: 1 }, path: { type: 'string', minLength: 1, maxLength: 512 }, sha256: { type: 'string', pattern: hex } } };
function cohortSchema(id) { return { type: 'object', additionalProperties: false,
  required: ['adaptive', 'cohort_id', 'cohort_sha256', 'ordered_query_symbols_sha256', 'query_symbol_records', 'records', 'reorder_allowed', 'reuse_allowed', 'size'],
  properties: { adaptive: { const: false }, cohort_id: { const: id }, cohort_sha256: { type: 'string', pattern: hex },
    ordered_query_symbols_sha256: { type: 'string', pattern: hex },
    query_symbol_records: { type: 'array', minItems: 1, maxItems: 8, items: selectionQueryRecordSchema },
    records: { type: 'array', minItems: 1, maxItems: 8, items: selectionDetailRecordSchema },
    reorder_allowed: { const: false }, reuse_allowed: { const: false }, size: { type: 'integer', minimum: 1, maximum: 8 } } }; }
const sampleSelectionSchema = { type: 'object', additionalProperties: false,
  required: ['algorithm', 'builder', 'cohorts', 'contract_sha256', 'eligibility', 'invariants', 'roster', 'schema_version'],
  properties: {
    schema_version: { const: 'market-pilot-sample-selection-document/v1' }, contract_sha256: { type: 'string', pattern: hex },
    algorithm: { type: 'object', additionalProperties: false, required: ['name', 'rank_preimage_exact_keys', 'seed', 'sort_order', 'version'],
      properties: { name: { const: 'sha256_ranked_without_replacement' }, seed: { const: 'market-pilot-calibration-20261110-v1' },
        version: { const: 'market-pilot-sample-selection/v1' }, rank_preimage_exact_keys: { type: 'array', minItems: 5, maxItems: 5, uniqueItems: true, items: { type: 'string' } },
        sort_order: { type: 'array', minItems: 3, maxItems: 3, uniqueItems: true, items: { type: 'string' } } } },
    builder: { type: 'object', additionalProperties: false, required: ['path', 'sha256', 'version'],
      properties: { path: { type: 'string', minLength: 1, maxLength: 512 }, sha256: { type: 'string', pattern: hex }, version: { const: 'market-pilot-sample-selection-builder/v1' } } },
    roster: { type: 'object', additionalProperties: false, required: ['normalized_rows', 'packet', 'row_count', 'validation_receipt'],
      properties: { normalized_rows: selectionRefSchema, packet: selectionRefSchema, row_count: { type: 'integer', minimum: 1 }, validation_receipt: selectionRefSchema } },
    eligibility: { type: 'object', additionalProperties: false,
      required: ['common_stock_claim', 'eligible_count', 'exact_predicates', 'query_security_class', 'query_venue', 'security_name_semantic_inference_used'],
      properties: { common_stock_claim: { const: false }, eligible_count: { type: 'integer', minimum: 1 }, query_security_class: { const: 'OTHER' },
        query_venue: { const: 'NASDAQ' }, security_name_semantic_inference_used: { const: false }, exact_predicates: { type: 'object', additionalProperties: false,
          required: ['etf', 'financial_status', 'next_shares', 'test_issue'], properties: { etf: { const: 'N' }, financial_status: { const: 'N' }, next_shares: { const: 'N' }, test_issue: { const: 'N' } } } } },
    invariants: { type: 'object', additionalProperties: false,
      required: ['adaptive_selection_allowed', 'cohort_reuse_allowed', 'cohorts_disjoint', 'order_frozen', 'promotion_authorized', 'reorder_allowed', 'without_replacement'],
      properties: { adaptive_selection_allowed: { const: false }, cohort_reuse_allowed: { const: false }, cohorts_disjoint: { const: true }, order_frozen: { const: true }, promotion_authorized: { const: false }, reorder_allowed: { const: false }, without_replacement: { const: true } } },
    cohorts: { type: 'object', additionalProperties: false, required: ['calibration', 'reserved_promotion'],
      properties: { calibration: cohortSchema('calibration'), reserved_promotion: cohortSchema('reserved_promotion') } },
  } };
const marketSchema = { type: 'object', additionalProperties: false,
  required: ['as_of', 'authorization_id', 'authorization_sha256', 'corporate_action_start', 'corporate_actions', 'contract', 'fields', 'fx_currencies', 'sample_selection', 'symbols'],
  properties: {
    as_of: { type: 'string', pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*Z$' },
    authorization_id: { type: 'string', pattern: '^mpa_[0-9a-f]{32}$' },
    authorization_sha256: { type: 'string', pattern: hex },
    corporate_action_start: { type: 'string', pattern: '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' },
    corporate_actions: { type: 'array', minItems: 1, maxItems: 4, uniqueItems: true,
      items: { enum: ['split', 'dividend', 'symbol_change', 'delisting'] } },
    contract: { type: 'object', additionalProperties: false,
      required: ['calibration_sha256', 'promotion_sha256', 'roster_sha256', 'sample_selection_sha256'],
      properties: Object.fromEntries(['calibration_sha256', 'promotion_sha256', 'roster_sha256', 'sample_selection_sha256']
        .map(k => [k, { type: 'string', pattern: hex }])) },
    fields: { type: 'object', additionalProperties: false,
      required: ['briefs', 'stock_fundamental', 'financial_daily', 'financial_report'],
      properties: {
        briefs: { type: 'array', minItems: 1, uniqueItems: true, items: { enum: ['latest_price', 'latest_time', 'pre_close', 'open', 'high', 'low', 'volume', 'status'] } },
        stock_fundamental: { type: 'array', minItems: 1, uniqueItems: true, items: { enum: ['market_cap', 'float_market_cap', 'ttm_eps', 'ttm_pe_rate', 'pb_rate', 'roe', 'roa'] } },
        financial_daily: { type: 'array', minItems: 1, uniqueItems: true, items: { enum: ['shares_outstanding', 'market_cap', 'pe_ttm', 'pb'] } },
        financial_report: { type: 'array', minItems: 1, uniqueItems: true, items: { enum: ['total_revenue', 'net_income', 'total_assets', 'total_liabilities', 'shareholders_equity', 'operating_cash_flow'] } },
      } },
    fx_currencies: { type: 'array', minItems: 1, maxItems: 10, uniqueItems: true,
      contains: { const: 'USD' }, items: { enum: ['USD', 'CAD', 'EUR', 'GBP', 'HKD', 'JPY', 'SGD', 'AUD', 'CNY', 'CNH'] } },
    sample_selection: sampleSelectionSchema,
    symbols: { type: 'array', minItems: 1, maxItems: 8, items: selectionQueryRecordSchema },
  } };
const accountTools = ['positions', 'assets', 'snapshot'].map(name => ({ name,
  description: `Read Tiger ${name} under the existing owner-private credential lease. Returns a receipt; data stays in private artifacts.`,
  inputSchema: { type: 'object', properties: name === 'assets' ? {} : { security_types: securityTypes }, additionalProperties: false },
  annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false },
}));
export const TIGER_TOOLS = [...accountTools, { name: 'market_snapshot',
  description: 'Manual roster-bound Tiger market pilot. Raw values stay private; only a sanitized receipt is returned.',
  inputSchema: marketSchema, annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false } }];
const validator = new AjvJsonSchemaValidator();
const validators = new Map(TIGER_TOOLS.map(t => [t.name, validator.getValidator(t.inputSchema)]));
const marketFiles = ['market_raw.json', 'market_manifest.json', 'market_query.json'];

function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function digest(value) { return createHash('sha256').update(canonical(value)).digest('hex'); }
function validSampleSelection(args) {
  try {
    const doc = args.sample_selection, calibration = doc.cohorts.calibration, promotion = doc.cohorts.reserved_promotion;
    if (Buffer.byteLength(canonical(doc)) > 256 * 1024
        || digest(doc) !== args.contract.sample_selection_sha256
        || digest(doc) !== 'f3f6e9d5c4eb5f21719225be8208bdd80c108ed6268c230aacb3d1bb1cc811d1'
        || doc.contract_sha256 !== '42b3112080e3233d6922ef1b87fab38818cfb34b64757e7e0f7cb060f58f7997'
        || doc.roster.packet.sha256 !== args.contract.roster_sha256
        || doc.roster.packet.sha256 !== '3005ba73b5be023f03c9614bb1cb3a2b09ff8b86a52c12daa01763d93de60c28'
        || calibration.cohort_sha256 !== digest(calibration.records)
        || calibration.cohort_sha256 !== '442fbff98f2e02651842891d7c5d31bcec0a2be5311c32d5129400af2a1d3634'
        || calibration.ordered_query_symbols_sha256 !== digest(calibration.query_symbol_records)
        || calibration.ordered_query_symbols_sha256 !== 'ec29e8afe8975cab2d3f2a82798c4d38b28c68988be5ce6b1b219104c9478214'
        || promotion.cohort_sha256 !== digest(promotion.records)
        || promotion.cohort_sha256 !== 'bdd1594ade846603d2796a09e00ac0f5ed657f83a79c9cd278a635dd659717af'
        || promotion.ordered_query_symbols_sha256 !== digest(promotion.query_symbol_records)
        || promotion.ordered_query_symbols_sha256 !== 'b1084fb0254fa2850b1791ff96335c1e9cc958ad654e85868f1651a331f9a3ec'
        || canonical(args.symbols) !== canonical(calibration.query_symbol_records)) return false;
    for (const record of [...calibration.query_symbol_records, ...promotion.query_symbol_records]) {
      const base = { entity_id: record.entity_id, security_class: record.security_class, symbol: record.symbol, venue: record.venue };
      if (record.roster_row_sha256 !== digest(base)) return false;
    }
    const cal = new Set(calibration.query_symbol_records.map(x => x.symbol));
    if (promotion.query_symbol_records.some(x => cal.has(x.symbol))) return false;
    return doc.invariants.promotion_authorized === false && doc.invariants.order_frozen === true
      && doc.eligibility.common_stock_claim === false && doc.eligibility.query_venue === 'NASDAQ';
  } catch { return false; }
}

function safeMap(value, predicate) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (!/^[a-z][a-z0-9_]{0,63}$/.test(key) || !predicate(item)) return null;
    out[key] = item;
  }
  return out;
}
export function safeReceipt(value, code) {
  if (value?.status === 'failed' && code === 2 && /^[A-Z][A-Z0-9_]{0,79}$/.test(value.error)) {
    return { status: 'failed', error: value.error, automatic_retry: false,
      reauthorization_assumed_required: false, reconciliation_required: value.reconciliation_required === true };
  }
  if (code !== 0 || value?.status !== 'queried' || value.committed !== true || value.release_requested !== true
      || value.source_read_status !== 'complete' || !validators.has(value.tool)
      || value.source !== 'existing_owner_private_store' || value.mode !== 'query' || !Array.isArray(value.files)) {
    throw new PortalError('invalid_response');
  }
  const base = { status: 'queried', tool: value.tool, source_read_status: 'complete', committed: true,
    release_requested: true, mode: 'query', authorization_prompted: false, broker_retries_added: 0,
    source: value.source, files: value.files };
  if (value.tool === 'market_snapshot') {
    if (value.files.length !== marketFiles.length || !marketFiles.every(f => value.files.includes(f))
        || !Number.isSafeInteger(value.symbols_count) || value.symbols_count < 1 || value.symbols_count > 8) throw new PortalError('invalid_response');
    const methodCounts = safeMap(value.method_counts, x => Number.isSafeInteger(x) && x >= 0);
    const hashes = safeMap(value.response_sha256, x => typeof x === 'string' && /^[0-9a-f]{64}$/.test(x));
    if (!methodCounts || !hashes || Object.keys(methodCounts).length !== Object.keys(hashes).length
        || typeof value.authorization_id !== 'string' || !/^mpa_[0-9a-f]{32}$/.test(value.authorization_id)
        || typeof value.authorization_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.authorization_sha256)
        || value.authorization_status !== 'consumed') throw new PortalError('invalid_response');
    return { ...base, provider_attempts: 1, symbols_count: value.symbols_count, method_counts: methodCounts,
      response_sha256: hashes, authorization_id: value.authorization_id,
      authorization_sha256: value.authorization_sha256, authorization_status: 'consumed' };
  }
  if (!value.files.every(f => ['holdings.json', 'assets.json', 'query.json'].includes(f))) throw new PortalError('invalid_response');
  const result = { ...base, holdings_read: value.holdings_read === true, assets_read: value.assets_read === true };
  if (Number.isSafeInteger(value.holdings_count) && value.holdings_count >= 0) result.holdings_count = value.holdings_count;
  if (/^[0-9a-f-]{36}$/.test(value.attempt_id)) result.attempt_id = value.attempt_id;
  return result;
}

export function runTigerWorker(context, { signal, spawnImpl = spawn, timeoutMs = 105000 } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new PortalError('timeout')); return; }
    const payload = JSON.stringify(context);
    if (Buffer.byteLength(payload) > 1024 * 1024) { reject(new PortalError('invalid_arguments')); return; }
    const child = spawnImpl(path.join(ROOT, '.niulai-state/.venv/bin/python'), ['-m', 'shared.tiger.worker'], {
      cwd: ROOT, stdio: ['pipe', 'pipe', 'ignore'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', TMPDIR: path.join(ROOT, '.niulai-state/tmp') },
    });
    let output = '', stopped = false, killTimer;
    function stop() { if (stopped) return; stopped = true; child.kill('SIGTERM'); killTimer ??= setTimeout(() => child.kill('SIGKILL'), 1500); killTimer.unref(); }
    const timer = setTimeout(stop, timeoutMs); signal?.addEventListener('abort', stop, { once: true });
    function cleanup() { clearTimeout(timer); clearTimeout(killTimer); signal?.removeEventListener('abort', stop); }
    child.on('error', () => { cleanup(); reject(new PortalError('setup_required')); });
    child.stdout.on('data', data => { output += data.toString(); if (Buffer.byteLength(output) > 65536) { output = ''; stop(); } });
    child.stdin.on('error', () => {});
    child.on('close', code => { cleanup(); if (stopped) { reject(new PortalError('timeout')); return; }
      try { resolve(safeReceipt(JSON.parse(output), code)); } catch { reject(new PortalError('invalid_response')); } });
    child.stdin.end(payload);
  });
}

export function tigerTransport(context, { execute = runTigerWorker, onReceipt = () => {} } = {}) {
  const [client, upstream] = InMemoryTransport.createLinkedPair();
  const server = new Server({ name: 'tiger-leased-readonly-adapter', version: '1.1.0' }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TIGER_TOOLS }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    const { name, arguments: args = {} } = request.params; let kind;
    if (!validators.has(name)) kind = 'tool_not_allowed'; else if (!validators.get(name)(args).valid) kind = 'invalid_arguments';
    else if (name === 'market_snapshot' && !validSampleSelection(args)) kind = 'invalid_arguments';
    if (kind) return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: kind }) }] };
    try { const rawReceipt = await execute({ ...context, query: { tool: name, arguments: args } }, { signal: extra.signal });
      const receipt = safeReceipt(rawReceipt, rawReceipt?.status === 'failed' ? 2 : 0);
      onReceipt(receipt); return { isError: receipt.status !== 'queried', content: [{ type: 'text', text: JSON.stringify(receipt.status === 'queried' ? receipt : { error: 'query_failed' }) }] };
    } catch { onReceipt({ status: 'failed', error: 'TIGER_WORKER_OUTCOME_UNCONFIRMED', automatic_retry: false, reconciliation_required: true });
      return { isError: true, content: [{ type: 'text', text: '{"error":"query_failed"}' }] }; }
  });
  void server.connect(upstream); return client;
}
