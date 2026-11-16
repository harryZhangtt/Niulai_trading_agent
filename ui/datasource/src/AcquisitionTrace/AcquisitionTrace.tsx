import { Badge, Notice } from '../components';
import { label, number, time } from '../format';
import type { AcquisitionDriverTrace } from '../types';
import styles from './AcquisitionTrace.module.css';

function available(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === '') return 'Unavailable';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
}

function Timestamp({ label: title, value }: { label: string; value: string | null }) {
  return <div><dt>{title}</dt><dd>{value ? time(value) : 'Unavailable'}</dd></div>;
}

export default function AcquisitionTrace({ trace }: { trace: AcquisitionDriverTrace }) {
  return <section className={styles.trace} aria-labelledby="acquisition-trace-title">
    <div className={styles.heading}><div><h2 id="acquisition-trace-title">Acquisition driver trace</h2><p>Checker-approved structural evidence. The dashboard displays the verdict; it does not grade the trace.</p></div><Badge value="verified">Checker pass</Badge></div>
    <Notice kind="warning" title="Structural evidence only"><p>{trace.limitations.join(' ')}</p></Notice>
    <dl className={styles.identities}>
      <div><dt>Experiment ID</dt><dd><code>{trace.experiment_id}</code></dd></div>
      <div><dt>Execution ID</dt><dd><code>{trace.execution_id}</code></dd></div>
      <div><dt>Trace ID</dt><dd><code>{trace.trace_id}</code></dd></div>
      <div><dt>Case ID</dt><dd><code>{available(trace.case_id)}</code></dd></div>
      <div><dt>Driver SHA-256</dt><dd><code>{trace.driver_sha256}</code></dd></div>
      <div><dt>Checker SHA-256</dt><dd><code>{trace.checker_verdict_sha256}</code></dd></div>
    </dl>
    <div className={styles.accounting} aria-label="Trace accounting">
      <article><span>Logical operations</span><strong>{number(trace.accounting.logical_operations)}</strong></article>
      <article><span>Reserved provider items</span><strong>{available(trace.accounting.reserved_provider_items)}</strong></article>
      <article><span>Actual dispatches</span><strong>{number(trace.accounting.actual_dispatches)}</strong></article>
      <article><span>Cache hits</span><strong>{number(trace.accounting.cache_hits)}</strong></article>
      <article><span>Fallbacks</span><strong>{number(trace.accounting.fallbacks)}</strong></article>
      <article><span>Complete chains</span><strong>{number(trace.accounting.complete_chains)} / {number(trace.accounting.credited_units)}</strong></article>
    </div>
    <section><h3>Questions</h3>{trace.questions.map(question => <article className={styles.card} key={question.id}><code>{question.id}</code><p>{question.question ?? 'Question unavailable'}</p></article>)}</section>
    <section><h3>Operations and transitions</h3><div className={styles.stack}>{trace.operations.map(operation => <details className={styles.card} key={operation.operation_id}><summary><span><code>{operation.operation_id}</code><small>{label(operation.status)}</small></span><Badge value={operation.failure_code ? 'partial' : operation.status}>{operation.failure_code ? label(operation.failure_code) : label(operation.status)}</Badge></summary>
      <dl className={styles.details}><div><dt>Attempt ID</dt><dd><code>{available(operation.attempt_id)}</code></dd></div><div><dt>Dispatch ID</dt><dd><code>{available(operation.dispatch_id)}</code></dd></div><div><dt>Provider route</dt><dd>{available(operation.provider_route)}</dd></div><div><dt>Cache hit</dt><dd>{available(operation.cache_hit)}</dd></div><div><dt>Provider invoked</dt><dd>{available(operation.fetch_executed)}</dd></div><div><dt>Failure code</dt><dd>{available(operation.failure_code)}</dd></div><Timestamp label="Started" value={operation.started_at} /><Timestamp label="Finished" value={operation.finished_at} /></dl>
      <p><strong>States:</strong> {operation.states.map(label).join(' → ')}</p><p><strong>Question IDs:</strong> {operation.question_ids.join(', ')}</p>
      <details><summary>Sanitized exact arguments</summary><pre className={styles.arguments}>{JSON.stringify(operation.arguments, null, 2)}</pre><p className={styles.hash}>Argument SHA-256: <code>{operation.arguments_sha256}</code></p></details>
      <p className={styles.hash}>Proposal SHA-256: <code>{operation.proposal_sha256}</code><br />Receipt SHA-256: <code>{operation.receipt_sha256}</code></p>
    </details>)}</div></section>
    <section><h3>Quote and independent review</h3>{trace.units.map(unit => <article className={styles.card} key={unit.unit_id}><div className={styles.heading}><div><code>{unit.unit_id}</code><p>{unit.question_id} · {unit.operation_id}</p></div><Badge value={unit.review_disposition}>{label(unit.review_disposition)}</Badge></div><blockquote>{unit.quote ?? 'Quote unavailable'}</blockquote>{unit.quote_truncated ? <p>Quote preview is truncated; the hash-bound source remains authoritative.</p> : null}<dl className={styles.details}><div><dt>Reviewer</dt><dd><code>{unit.reviewer_id}</code></dd></div><div><dt>Review reason</dt><dd>{unit.review_reason ?? 'Unavailable'}</dd></div><div><dt>Source version</dt><dd><code>{available(unit.source_version)}</code></dd></div><div><dt>Raw SHA-256</dt><dd><code>{available(unit.raw_sha256)}</code></dd></div><div><dt>Text SHA-256</dt><dd><code>{available(unit.text_sha256)}</code></dd></div><div><dt>Review SHA-256</dt><dd><code>{unit.review_sha256}</code></dd></div><div><dt>Canonical disclosure</dt><dd><code>{available(unit.lineage.canonical_disclosure_id)}</code></dd></div><div><dt>Representation</dt><dd>{available(unit.lineage.representation_kind)}</dd></div><div><dt>Representation relationship</dt><dd>{available(unit.lineage.representation_relationship)}</dd></div><Timestamp label="Published" value={unit.times.published_at} /><Timestamp label="Modified" value={unit.times.modified_at} /><Timestamp label="Available" value={unit.times.available_at} /><Timestamp label="First observed" value={unit.times.first_observed_at} /><Timestamp label="Retrieved" value={unit.times.retrieved_at} /><Timestamp label="Screened" value={unit.times.screened_at} /><Timestamp label="Exposed" value={unit.times.exposed_at} /></dl><ul>{Object.entries(unit.review_checks).map(([key, passed]) => <li key={key}>{label(key)}: {passed ? 'Pass' : 'Fail'}</li>)}</ul></article>)}</section>
    <section><h3>Checker gates</h3><ul className={styles.gates}>{trace.checker_gates.map(gate => <li key={gate.id}><Badge value={gate.status}>{label(gate.status)}</Badge><span><strong>{label(gate.id)}</strong>{gate.reasons.map(reason => <small key={reason}>{reason}</small>)}</span></li>)}</ul></section>
    <p className={styles.unavailable}>Missing links: {trace.missing_links.length ? trace.missing_links.join(', ') : 'None reported by the checker'}. Values absent from receipts remain unavailable.</p>
  </section>;
}
