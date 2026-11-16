import type { DatasourceResponse } from './types';
import { isAcquisitionTrace } from './AcquisitionTrace';

const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const text = (value: unknown) => typeof value === 'string';
const nullableText = (value: unknown) => value === null || text(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const metric = (value: unknown) => value === null || typeof value === 'number' && Number.isFinite(value);

function source(value: unknown) {
  if (!record(value) || !text(value.id) || !text(value.title) || !text(value.subject)
    || !nullableText(value.url) || !text(value.scope) || !text(value.content_access)
    || !strings(value.run_ids) || !strings(value.limitations) || !record(value.labels) || !record(value.timestamps)) return false;
  const timestamps = value.timestamps;
  const labels = value.labels;
  if (['published_at', 'available_at', 'fetched_at', 'recorded_at'].some(key => !nullableText(timestamps[key]))) return false;
  if (!strings(labels.perspectives) || !strings(labels.topics)) return false;
  if (['publisher_kind', 'document_type', 'epistemic_status', 'annotation_status', 'policy_version', 'provenance_status'].some(key => !nullableText(labels[key]))) return false;
  if (value.batch_ids !== undefined && !strings(value.batch_ids) || value.collection_ids !== undefined && !strings(value.collection_ids)) return false;
  if (value.local_preview != null) {
    const preview = value.local_preview;
    if (!record(preview) || !['available', 'missing'].includes(String(preview.status)) || !text(preview.text)
      || !strings(preview.reason_codes) || typeof preview.truncated !== 'boolean') return false;
  }
  return true;
}

function run(value: unknown) {
  if (!record(value) || !text(value.id) || !text(value.query) || !text(value.status) || !text(value.scope)
    || !strings(value.source_ids) || !record(value.metrics) || !Array.isArray(value.phases) || !Array.isArray(value.script_versions)) return false;
  if (!Object.values(value.metrics).every(metric) || !value.phases.every(item => record(item) && text(item.id) && text(item.status))
    || !value.script_versions.every(item => record(item) && text(item.id) && nullableText(item.sha256))) return false;
  if (value.output != null) {
    const output = value.output;
    if (!record(output) || !text(output.summary) || !Array.isArray(output.questions) || !Array.isArray(output.observations)
      || !output.questions.every(item => record(item) && text(item.id) && text(item.question) && text(item.facet) && text(item.priority))
      || !output.observations.every(item => record(item) && text(item.source_sha256) && text(item.quote) && strings(item.topics))) return false;
  }
  return true;
}

function cohort(value: unknown) {
  if (!record(value) || !text(value.id) || !text(value.scope) || !count(value.denominator) || !record(value.metrics)) return false;
  return Object.values(value.metrics).every(item => record(item) && metric(item.sum) && metric(item.mean)
    && count(item.known) && count(item.unknown) && count(item.denominator));
}

function metrics(value: unknown) { return record(value) && Object.values(value).every(metric); }

function batch(value: unknown) {
  if (!record(value) || !text(value.id) || !text(value.execution_id) || !text(value.batch_id)
    || !text(value.status) || !strings(value.subjects) || !strings(value.source_ids) || !strings(value.limitations)
    || !metrics(value.metrics) || !record(value.configuration) || !record(value.configuration.budget)
    || !Array.isArray(value.configuration.requirements) || !Array.isArray(value.sources) || !value.sources.every(source)
    || !Array.isArray(value.requirements) || !record(value.retention) || !Array.isArray(value.script_versions)) return false;
  return value.configuration.requirements.every(item => record(item) && text(item.id) && text(item.subject)
    && text(item.access) && Array.isArray(item.routes) && item.routes.every(route => record(route) && text(route.capability) && record(route.parameters)))
    && value.requirements.every(item => record(item) && text(item.id) && Array.isArray(item.attempts)
      && item.attempts.every(attempt => record(attempt) && text(attempt.capability) && text(attempt.status) && strings(attempt.reasons)));
}

function comparison(value: unknown) {
  if (!record(value) || !text(value.id) || !text(value.title) || !text(value.status) || !text(value.scope)
    || !strings(value.limitations) || !Array.isArray(value.arms) || !Array.isArray(value.rows)) return false;
  if (!value.arms.every(item => record(item) && text(item.id) && text(item.status) && count(item.denominator) && record(item.metrics))) return false;
  if (!value.rows.every(item => record(item) && text(item.case_id) && record(item.A) && record(item.B)
    && text(item.A.status) && text(item.B.status) && metrics(item.A.metrics) && metrics(item.B.metrics) && metrics(item.differences))) return false;
  if (value.driver_trace && !isAcquisitionTrace(value.driver_trace)) return false;
  if (value.acquisition != null) {
    const acquisition = value.acquisition;
    if (!record(acquisition) || !record(acquisition.reviews) || !Array.isArray(acquisition.tasks)
      || !record(acquisition.capture_counts) || !record(acquisition.sensitivity_excluding_anonymous)
      || !Array.isArray(acquisition.collections)) return false;
    if (!acquisition.collections.every(item => record(item) && text(item.execution_id) && text(item.status)
      && text(item.arm) && metrics(item.metrics) && metrics(item.budget) && record(item.cache_outcomes)
      && Array.isArray(item.sources) && item.sources.every(source) && Array.isArray(item.units)
      && item.units.every(unit => record(unit) && text(unit.id) && strings(unit.tasks) && strings(unit.freshness) && strings(unit.limitations)))) return false;
  }
  return true;
}

/** Shape checks at the read boundary, separate from view selection and rendering. */
export function isDatasourceResponse(value: unknown): value is DatasourceResponse {
  if (!record(value) || value.schema_version !== 1 || !text(value.subject) || !text(value.snapshot_id)
    || !text(value.generated_at) || !['ok', 'partial', 'unavailable'].includes(String(value.status))
    || value.projection_state !== undefined && !['fresh', 'stale'].includes(String(value.projection_state))
    || !record(value.pagination) || !count(value.pagination.total_sources) || !count(value.pagination.total_runs)
    || !count(value.pagination.offset) || !count(value.pagination.limit)
    || !(value.pagination.next_offset === null || count(value.pagination.next_offset))
    || !Array.isArray(value.sources) || !value.sources.every(source) || !Array.isArray(value.runs) || !value.runs.every(run)
    || !Array.isArray(value.comparisons) || !record(value.aggregates) || !Array.isArray(value.aggregates.cohorts)
    || !value.aggregates.cohorts.every(cohort) || !Array.isArray(value.warnings)
    || !value.warnings.every(item => record(item) && text(item.code) && count(item.count))) return false;
  if (new Set(value.sources.map(item => item.id)).size !== value.sources.length
    || new Set(value.runs.map(item => item.id)).size !== value.runs.length) return false;
  return value.comparisons.every(comparison) && (value.batches === undefined || Array.isArray(value.batches) && value.batches.every(batch));
}
