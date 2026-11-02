import type { MetricDefinition } from './types';

export const number = (value: number | null | undefined): string =>
  value == null || !Number.isFinite(value) ? 'Unknown' : new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(value);

export const label = (value: string): string => value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/^\w/, character => character.toUpperCase());

export function display(value: unknown): string {
  if (value == null || value === '') return 'Unknown';
  if (typeof value === 'number') return number(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : 'None recorded';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function time(value: string | null | undefined): string {
  if (!value) return 'Unknown';
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} (date only)`;
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return `${value} (timezone unknown)`;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
}

export function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : null;
  } catch { return null; }
}

export function host(value: string | null): string {
  const url = safeUrl(value);
  return url ? new URL(url).hostname.replace(/^www\./, '') : 'No public URL recorded';
}

export function metricLabel(key: string, definitions?: Record<string, MetricDefinition>): string {
  return definitions?.[key]?.label ?? label(key);
}

export function tone(value: string | null | undefined): 'good' | 'bad' | 'warn' | 'neutral' {
  if (!value) return 'neutral';
  if (/^(ok|complete|completed|pass|passed|eligible|accepted|verified|valid|available|usable)$/.test(value)) return 'good';
  if (/(fail|blocked|ineligible|invalid|leak)/.test(value)) return 'bad';
  if (/(unknown|partial|unavailable|reconstruct|missing|pending|limited|not_evaluated|not_rechecked|provisional|interrupted)/.test(value)) return 'warn';
  return 'neutral';
}
