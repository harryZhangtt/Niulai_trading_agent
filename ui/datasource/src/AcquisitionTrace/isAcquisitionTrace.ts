import type { AcquisitionDriverTrace } from '../types';

function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function safe(value: unknown, depth = 0): boolean {
  if (depth > 8) return false;
  if (value === null || ['string', 'boolean'].includes(typeof value)) return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.length <= 64 && value.every(item => safe(item, depth + 1));
  if (!object(value) || Object.keys(value).length > 64) return false;
  return Object.entries(value).every(([key, item]) => !/^(raw|raw_result|path|private_path|prompt|credentials?|token|secret|exception)$/i.test(key) && safe(item, depth + 1));
}

export function isAcquisitionTrace(value: unknown): value is AcquisitionDriverTrace {
  if (!object(value) || !safe(value)) return false;
  const operations = value.operations;
  const units = value.units;
  const accounting = value.accounting;
  return value.checker_verdict === 'pass'
    && typeof value.checker_verdict_sha256 === 'string' && /^[a-f0-9]{64}$/.test(value.checker_verdict_sha256)
    && Array.isArray(operations) && operations.length > 0 && operations.length <= 8
    && Array.isArray(units) && units.length === 1 && object(units[0]) && units[0].review_disposition === 'approve'
    && Array.isArray(value.missing_links) && value.missing_links.length === 0
    && object(accounting) && accounting.complete_chains === 1 && accounting.credited_units === 1;
}
