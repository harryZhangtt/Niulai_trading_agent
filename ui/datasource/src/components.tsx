import type { ReactNode } from 'react';
import { display, label, metricLabel, number, safeUrl, time, tone } from './format';
import type { AggregateMetric, Details, MetricDefinition, Run, RunOutput, Source } from './types';
import { ledgerTemporal, runSourceDecision } from './temporal';

export function Icon({ name, size = 18 }: { name: 'sources' | 'compare' | 'layers' | 'search' | 'refresh' | 'external' | 'chevron' | 'check' | 'minus' | 'plus' | 'alert'; size?: number }) {
  const paths: Record<typeof name, ReactNode> = {
    sources: <><path d="M4 3h11l5 5v13H4z" /><path d="M14 3v6h6M8 13h8M8 17h6" /></>,
    compare: <><path d="M4 5h6v14H4zM14 5h6v14h-6zM10 10h4M10 14h4" /></>,
    layers: <><path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></>,
    external: <><path d="M14 3h7v7M21 3l-10 10M10 5H4v15h15v-6" /></>,
    chevron: <path d="m9 5 7 7-7 7" />,
    check: <path d="m5 12 4 4L19 6" />,
    minus: <path d="M5 12h14" />,
    plus: <path d="M5 12h14M12 5v14" />,
    alert: <><path d="m12 3 10 18H2zM12 9v5M12 17v.2" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Badge({ value, children }: { value?: string | null; children?: ReactNode }) {
  return <span className={`badge badge-${tone(value)}`}><span className="status-dot" aria-hidden="true" />{children ?? (value ? label(value) : 'Unknown')}</span>;
}

export function SourceCutoff({ source, run }: { source: Source; run?: Run }) {
  const assessment = ledgerTemporal(source, run);
  return <div className="cutoff-status"><Badge value={assessment.status} /><span className="cell-subtext">{assessment.scope} / reviewer only</span><span className="cell-subtext">Cutoff: {time(assessment.cutoff)}</span></div>;
}

export function SourceClassification({ source }: { source: Source }) {
  return <><span>{source.labels.document_type ? label(source.labels.document_type) : 'Type unknown'}</span><span className="cell-subtext">{source.labels.publisher_kind ? label(source.labels.publisher_kind) : 'Publisher unknown'}</span><span className="cell-subtext">{source.labels.perspectives.length ? source.labels.perspectives.map(label).join(', ') : 'Perspective unknown'}</span><span className="annotation-badge"><Badge value={source.labels.annotation_status} /></span></>;
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><Icon name="sources" size={28} /><h3>{title}</h3><p>{children}</p></div>;
}

export function Notice({ children, kind = 'info', title }: { children: ReactNode; kind?: 'info' | 'warning' | 'error'; title?: string }) {
  return <div className={`notice notice-${kind}`} role={kind === 'error' ? 'alert' : undefined}><Icon name="alert" /><div>{title ? <strong>{title}</strong> : null}{children}</div></div>;
}

export function Field({ name, children, mono = false }: { name: string; children: ReactNode; mono?: boolean }) {
  return <div className="metadata-field"><dt>{name}</dt><dd className={mono ? 'mono' : undefined}>{children}</dd></div>;
}

export function DetailsTree({ value }: { value: Details }) {
  return <dl className="metadata details-tree">{Object.entries(value).map(([key, item]) => <Field key={key} name={label(key)}>
    {item && typeof item === 'object' && !Array.isArray(item) ? <DetailsTree value={item as Details} /> : display(item)}
  </Field>)}</dl>;
}

export function TemporalPanel({ source, run }: { source?: Source; run?: Run }) {
  const sourceDiagnostic = source?.temporal;
  const decision = runSourceDecision(source, run);
  const state = run ? decision?.status ?? 'unknown' : sourceDiagnostic?.status ?? 'unknown';
  const runProvenance = run?.temporal ? Object.fromEntries(Object.entries(run.temporal).filter(([key]) => key !== 'source_decisions')) : null;
  return <section className="inspector-section temporal-panel" aria-labelledby="temporal-title">
    <div className="section-heading"><h3 id="temporal-title">Temporal validity</h3><Badge value={typeof state === 'string' ? state : 'unknown'} /></div>
    <p className="subtle">Reviewer diagnostics. These assessments are separate from evidence visible to a research worker.</p>
    {run ? <div className="run-temporal-assessment"><h4>Selected execution assessment</h4><dl className="metadata"><Field name="Run cutoff">{time(run.temporal?.cutoff)}</Field><Field name="Guard status">{run.temporal?.status ? label(run.temporal.status) : 'Unknown'}</Field></dl>{decision ? <DetailsTree value={decision} /> : <p className="unknown-note">Unknown selected-run eligibility. No source decision is bound to this execution. A separate source-level check cannot establish what this run could use.</p>}{runProvenance ? <details><summary>Run-bound diagnostic provenance</summary><DetailsTree value={runProvenance} /></details> : null}</div> : null}
    {sourceDiagnostic ? <div className="source-temporal-assessment"><h4>{run ? 'Separate source-level diagnostic' : 'Source-level diagnostic'}</h4><p className="subtle">At the displayed cutoff: {typeof sourceDiagnostic.cutoff === 'string' ? time(sourceDiagnostic.cutoff) : 'Unknown'}. This does not establish eligibility for another execution.</p><DetailsTree value={sourceDiagnostic} /></div> : <p className="unknown-note">No source-level cutoff decision is recorded. A publication date alone does not establish eligibility.</p>}
    {source?.temporal_checks && source.temporal_checks.length > 1 ? <details><summary>Source-level check history ({source.temporal_checks.length})</summary>{source.temporal_checks.map((check, index) => <div className="temporal-history-check" key={index}><DetailsTree value={check} /></div>)}</details> : null}
    <p className="subtle temporal-boundary">Temporal eligibility and worker visibility are separate decisions. A reconstructed version is never strict worker evidence.</p>
  </section>;
}

function LocalDocumentPreview({ preview }: { preview: NonNullable<Source['local_preview']> }) {
  const available = preview.status === 'available';
  return <section className="inspector-section document-preview" aria-labelledby="document-preview-title">
    <div className="section-heading"><h3 id="document-preview-title">Document contents</h3><Badge value={available ? 'available' : 'missing'}>{available ? 'Local JSON available' : 'Document body missing'}</Badge></div>
    <p className="subtle">{available ? 'This is a sanitized preview of the registered local research JSON. It is not primary-source verification.' : 'The checkpoint JSON body is missing from this workspace. The actual registered catalog metadata is shown below; it is not the report body.'}</p>
    {preview.truncated ? <p className="preview-warning">Preview truncated. Content beyond the display limits is omitted.</p> : null}
    {preview.redacted_fields ? <p className="subtle">Private fields and paths are redacted ({preview.redacted_fields} recorded redactions).</p> : null}
    <details open><summary>{available ? 'Research JSON preview' : 'Catalog JSON (document body missing)'}</summary><pre tabIndex={0} aria-label="Research document JSON preview">{preview.text}</pre></details>
    <dl className="metadata"><Field name={available ? 'Document bytes' : 'Declared bytes (unverified)'}>{number(available ? preview.document_bytes : preview.declared_document_bytes)}</Field><Field name={available ? 'Document SHA-256' : 'Declared SHA-256 (unverified)'} mono>{display(available ? preview.document_sha256 : preview.declared_document_sha256)}</Field><Field name="Preview SHA-256" mono>{display(preview.preview_sha256)}</Field><Field name="Preview frozen">{time(preview.frozen_at)}</Field><Field name="Original availability">Unknown</Field></dl>
    {preview.reason_codes.length ? <p className="preview-reasons">{preview.reason_codes.join(', ')}</p> : null}
    <p className="subtle">This preview does not establish original availability, canonical Library byte identity, or historical eligibility.</p>
  </section>;
}

export function SourceInspector({ source, run, onSelectRun }: { source: Source; run?: Run; onSelectRun?: (id: string) => void }) {
  const url = safeUrl(source.url);
  return <aside className="inspector" aria-label="Selected source details" id="source-inspector">
    <a className="back-to-ledger" href="#ledger-heading">Back to source ledger</a>
    <div className="inspector-top"><span className="small-label">Selected source</span><Badge value={source.labels.provenance_status} /></div>
    <h2 className="inspector-title">{source.title || 'Untitled source'}</h2>
    {url ? <a className="source-link" href={url} target="_blank" rel="noreferrer">Open original source <Icon name="external" size={15} /></a> : <p className="subtle">No public source link is available.</p>}
    {source.local_preview ? <LocalDocumentPreview key={source.id} preview={source.local_preview} /> : null}
    <section className="inspector-section"><h3>Classification</h3><dl className="metadata">
      <Field name="Publisher">{display(source.labels.publisher_kind)}</Field>
      <Field name="Document type">{display(source.labels.document_type)}</Field>
      <Field name="Perspectives">{display(source.labels.perspectives)}</Field>
      <Field name="Topics">{display(source.labels.topics)}</Field>
      <Field name="Evidence status">{display(source.labels.epistemic_status)}</Field>
      <Field name="Annotation">{display(source.labels.annotation_status)}</Field>
      <Field name="Policy version">{display(source.labels.policy_version)}</Field>
      <Field name="Label storage">{display(source.labels.persistence)}</Field>
      <Field name="Content access">{display(source.content_access)}</Field>
      <Field name="Scope">{display(source.scope)}</Field>
    </dl></section>
    <section className="inspector-section"><h3>Source timeline</h3><dl className="metadata timeline">
      <Field name="Published">{time(source.timestamps.published_at)}</Field>
      <Field name="Available">{time(source.timestamps.available_at)}</Field>
      <Field name="Fetched">{time(source.timestamps.fetched_at)}</Field>
      <Field name="Recorded">{time(source.timestamps.recorded_at)}</Field>
    </dl><p className="subtle">Zoned timestamps use UTC. Date-only values keep their original precision; missing times remain unknown.</p></section>
    <TemporalPanel source={source} run={run} />
    <section className="inspector-section"><h3>Provenance</h3><dl className="metadata">
      <Field name="Source ID" mono>{source.id}</Field>
      <Field name="Source SHA-256" mono>{display(source.source_sha256)}</Field>
      <Field name="Version SHA-256" mono>{display(source.version_sha256)}</Field>
    </dl></section>
    <section className="inspector-section"><h3>Linked research pipelines</h3>{source.run_ids.length ? <div className="linked-runs">{source.run_ids.map(id => onSelectRun ? <button key={id} className="text-button mono" onClick={() => onSelectRun(id)}>{id}<Icon name="chevron" size={14} /></button> : <p className="linked-receipt mono" key={id}>{id}</p>)}</div> : <p className="subtle">No linked research pipeline was recorded.</p>}{source.collection_ids?.length ? <><h3>Native collection execution IDs</h3>{source.collection_ids.map(id => <p className="linked-receipt mono" key={id}>{id}</p>)}<p className="subtle">Inspect collection receipts and scoped metrics in Executions or A/B evaluation.</p></> : null}</section>
    {source.batch_ids?.length ? <section className="inspector-section"><h3>Linked acquisition batches</h3>{source.batch_ids.map(id => <p className="linked-receipt mono" key={id}>{id}</p>)}</section> : null}
    {source.limitations.length ? <section className="inspector-section"><h3>Limitations</h3><ul className="plain-list">{source.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></section> : null}
  </aside>;
}

export function AggregateTable({ metrics, definitions, caption }: { metrics: Record<string, AggregateMetric>; definitions?: Record<string, MetricDefinition>; caption: string }) {
  const entries = Object.entries(metrics);
  return entries.length ? <div className="table-wrap"><table className="data-table metric-table"><caption className="sr-only">{caption}</caption><thead><tr><th>Metric</th><th>Mean</th><th>Sum</th><th>Known / total</th><th>Unknown</th></tr></thead><tbody>
    {entries.map(([key, metric]) => <tr key={key}><th scope="row">{metricLabel(key, definitions)}<span className="cell-subtext">{metric.unit ?? definitions?.[key]?.unit ?? 'Unit not recorded'}</span></th><td className="numeric">{number(metric.mean)}</td><td className="numeric">{number(metric.sum)}</td><td className="numeric">{number(metric.known)} / {number(metric.denominator)}</td><td className="numeric">{number(metric.unknown)}</td></tr>)}
  </tbody></table></div> : <p className="unknown-note">No aggregate metrics were recorded for this cohort.</p>;
}

function CatalogOutput({ output }: { output: RunOutput }) {
  return <details className="run-output"><summary>Catalog and extracted observations</summary>
    <div className="output-summary"><p>{output.summary}</p><Badge value={output.annotation_status} /></div>
    <p className="output-boundary">These catalog annotations and extracted quotations are provisional. They have not passed semantic admission and do not certify a source claim as true.</p>
    <dl className="metadata"><Field name="Catalog SHA-256" mono>{output.catalog_sha256}</Field></dl>
    <section className="output-section"><h4>Research questions ({output.questions.length})</h4>{output.questions.length ? <ol className="question-list">{output.questions.map(question => <li key={question.id}><div className="question-meta"><span>{label(question.facet)}</span><Badge value={question.priority} /><span className="mono">{question.id}</span></div><p>{question.question}</p></li>)}</ol> : <p className="subtle">No questions were recorded in this catalog.</p>}</section>
    <section className="output-section"><h4>Extracted observations ({output.observations.length})</h4>{output.observations.length ? output.observations.map((observation, index) => <figure className="observation" key={`${observation.source_sha256}-${index}`}><blockquote><p>{observation.quote}</p></blockquote><figcaption><div className="observation-meta"><Badge value={observation.epistemic_status} /><span>{observation.topics.length ? observation.topics.map(label).join(', ') : 'Topics unknown'}</span></div><span className="observation-source">Source SHA-256 <code>{observation.source_sha256}</code></span></figcaption></figure>) : <p className="subtle">No source observations were recorded.</p>}</section>
  </details>;
}

export function RunDetails({ run, definitions }: { run: Run; definitions?: Record<string, MetricDefinition> }) {
  return <section className="run-details" aria-labelledby="run-heading"><div className="section-heading"><div><h3 id="run-heading">Execution provenance</h3><p className="subtle">{run.query || 'No query recorded'}</p></div><Badge value={run.status} /></div>
    <dl className="metadata run-metadata"><Field name="Run ID" mono>{run.id}</Field><Field name="Execution ID" mono>{display(run.execution_id)}</Field><Field name="Pipeline">{display(run.pipeline_id)}</Field><Field name="Pipeline version">{display(run.pipeline_version)}</Field><Field name="Started">{time(run.started_at)}</Field><Field name="Finished">{time(run.finished_at)}</Field><Field name="Scope">{display(run.scope)}</Field><Field name="Config SHA-256" mono>{display(run.config_sha256)}</Field></dl>
    {Object.keys(run.metrics).length ? <dl className="run-metrics">{Object.entries(run.metrics).map(([key, value]) => <div key={key}><dt>{metricLabel(key, definitions)}</dt><dd>{number(value)}<span>{definitions?.[key]?.unit ?? ''}</span></dd></div>)}</dl> : <p className="subtle">No execution metrics were recorded.</p>}
    {run.output ? <CatalogOutput output={run.output} /> : null}
    <details><summary>Phases and script versions</summary><div className="provenance-columns"><div><h4>Phases</h4>{run.phases.length ? <ol className="phase-list">{run.phases.map(phase => <li key={phase.id}><span>{label(phase.id)}</span><Badge value={phase.status} /><small>{[phase.mode, phase.action].filter(Boolean).join(' / ') || 'Mode unknown'}</small></li>)}</ol> : <p className="subtle">No phase trace recorded.</p>}</div><div><h4>Scripts</h4>{run.script_versions.length ? <dl className="metadata">{run.script_versions.map(script => <Field name={script.id} key={script.id} mono>{display(script.sha256)}</Field>)}</dl> : <p className="subtle">No script hashes recorded.</p>}</div></div></details>
  </section>;
}
