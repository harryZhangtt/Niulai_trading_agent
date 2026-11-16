import { useId, type ReactNode } from 'react';
import { displayDate } from '../scheduler/components/shared';
import type { EvidenceSeverity, EvidenceValue, ResiliencePanelProps } from './types';
import styles from './ResiliencePanel.module.css';

interface FieldDefinition {
  readonly label: string;
  readonly value: ReactNode;
  readonly severity?: EvidenceSeverity;
  readonly availability?: EvidenceValue['availability'];
  readonly indicator?: 'threshold' | 'semantic';
}

function severityClass(severity: EvidenceSeverity | undefined): string {
  switch (severity) {
    case 'positive': return styles.positive;
    case 'info': return styles.info;
    case 'warning': return styles.warning;
    case 'critical': return styles.critical;
    default: return '';
  }
}

function thresholdLabel(severity: EvidenceSeverity | undefined): string | null {
  switch (severity) {
    case 'positive': return 'Within threshold';
    case 'info': return 'Below warning threshold';
    case 'warning': return 'Warning threshold';
    case 'critical': return 'Limit reached';
    default: return null;
  }
}

function semanticSeverityLabel(severity: EvidenceSeverity | undefined): string | null {
  switch (severity) {
    case 'positive': return 'Clear status';
    case 'info': return 'Informational status';
    case 'warning': return 'Warning status';
    case 'critical': return 'Critical status';
    default: return null;
  }
}

function Value({ value }: { readonly value: EvidenceValue }) {
  return <bdi>{value.text}</bdi>;
}

function DateValue({ value, zone, includeZone = false }: {
  readonly value: EvidenceValue;
  readonly zone: string;
  readonly includeZone?: boolean;
}) {
  if (value.availability !== 'recorded' || !Number.isFinite(Date.parse(value.text))) return <Value value={value} />;
  return <time dateTime={value.text}><bdi>{displayDate(value.text, zone)}{includeZone ? ` · ${zone}` : ''}</bdi></time>;
}

function labelled(label: string, value: EvidenceValue): ReactNode {
  return <><span className={styles.inlineLabel}>{label}</span> <Value value={value} /></>;
}

function pair(firstLabel: string, first: EvidenceValue, secondLabel: string, second: EvidenceValue): ReactNode {
  return <>{labelled(firstLabel, first)}<span aria-hidden="true"> · </span>{labelled(secondLabel, second)}</>;
}

function counter(used: EvidenceValue, limit: EvidenceValue): ReactNode {
  if (used.availability === 'recorded' && limit.availability === 'recorded') {
    return <bdi>{used.text} used / {limit.text} limit</bdi>;
  }
  return <>{used.availability === 'recorded' ? <bdi>{used.text} used</bdi> : labelled('Used', used)}<span aria-hidden="true"> · </span>{limit.availability === 'recorded' ? <bdi>{limit.text} limit</bdi> : labelled('Limit', limit)}</>;
}

function retry(value: EvidenceValue, source: EvidenceValue, zone: string): ReactNode {
  return <><DateValue value={value} zone={zone} /><span aria-hidden="true"> · </span>{labelled('Source', source)}</>;
}

function definitions(fields: readonly FieldDefinition[]): ReactNode {
  return fields.map((field) => {
    const indicator = field.indicator === 'threshold'
      ? thresholdLabel(field.severity)
      : field.indicator === 'semantic' ? semanticSeverityLabel(field.severity) : null;
    return <div className={styles.row} data-availability={field.availability} data-severity={field.severity ?? 'neutral'} key={field.label}>
      <dt>{field.label}</dt>
      <dd>
        <span className={styles.value}>{field.value}</span>
        {indicator ? <span className={`${field.indicator === 'threshold' ? styles.threshold : styles.semanticState} ${severityClass(field.severity)}`}>{indicator}</span> : null}
      </dd>
    </div>;
  });
}

export function ResiliencePanel({ evidence, zone, stale, refreshing, partial }: ResiliencePanelProps) {
  const headingPrefix = `resilience-${useId().replaceAll(':', '')}`;
  const incomplete = partial || evidence.snapshot.status.text.toLowerCase() === 'partial';
  const effectiveFreshness = stale
    ? { text: 'Retained stale snapshot', availability: 'recorded', severity: 'warning' } as const
    : evidence.snapshot.projectionFreshness;
  const completeness = incomplete
    ? { text: 'Partial', availability: 'recorded', severity: 'warning' } as const
    : evidence.snapshot.status;
  const readStatus = stale
    ? refreshing ? 'Updating retained stale snapshot' : 'Retained stale snapshot'
    : refreshing ? 'Updating retained snapshot' : 'Latest detail read succeeded';
  const announcement = `${readStatus}.${incomplete ? ' Evidence completeness is partial.' : ''}`;

  const groups: ReadonlyArray<{
    readonly title: string;
    readonly description?: string;
    readonly fields: readonly FieldDefinition[];
  }> = [
    {
      title: 'Snapshot',
      fields: [
        { label: 'Recorded at', value: <DateValue value={evidence.snapshot.generatedAt} zone={zone} includeZone />, availability: evidence.snapshot.generatedAt.availability },
        { label: 'Snapshot completeness', value: <Value value={completeness} />, availability: completeness.availability },
        { label: 'Effective freshness', value: <Value value={effectiveFreshness} />, availability: effectiveFreshness.availability },
      ],
    },
    {
      title: 'Active work',
      description: 'Provider execution, business acceptance and email delivery are separate outcomes.',
      fields: [
        { label: 'Scheduler', value: pair('State', evidence.activeWork.schedulerStatus, 'Attempts', evidence.activeWork.schedulerAttempts) },
        { label: 'Latest provider attempt', value: pair('Phase', evidence.activeWork.providerLatestPhase, 'Status', evidence.activeWork.providerLatestStatus) },
      ],
    },
    {
      title: 'Recovery',
      fields: [
        { label: 'Unknown-outcome fence', value: <Value value={evidence.recovery.unknownFence} />, severity: evidence.recovery.unknownFence.severity, availability: evidence.recovery.unknownFence.availability, indicator: 'semantic' },
        { label: 'Provider replay authorization', value: <Value value={evidence.recovery.replayAuthorization} />, severity: evidence.recovery.replayAuthorization.severity, availability: evidence.recovery.replayAuthorization.availability, indicator: 'semantic' },
        { label: 'Retry timing', value: retry(evidence.recovery.retryDelay, evidence.recovery.retrySource, zone) },
        { label: 'Mentor cycles', value: <Value value={evidence.recovery.mentorCycles} />, availability: evidence.recovery.mentorCycles.availability },
        { label: 'No-progress budget', value: counter(evidence.recovery.noProgressCycles, evidence.recovery.noProgressLimit), severity: evidence.recovery.noProgressCycles.severity, indicator: 'threshold' },
        { label: 'Repeated-evidence budget', value: counter(evidence.recovery.repeatedCycles, evidence.recovery.repeatedLimit), severity: evidence.recovery.repeatedCycles.severity, indicator: 'threshold' },
        { label: 'Evidence reset', value: <Value value={evidence.recovery.evidenceReset} />, availability: evidence.recovery.evidenceReset.availability },
      ],
    },
    {
      title: 'Host timing',
      fields: [
        { label: 'Heartbeat age at snapshot', value: <Value value={evidence.hostTiming.heartbeatAge} />, availability: evidence.hostTiming.heartbeatAge.availability },
        { label: 'Watchdog observation', value: <Value value={evidence.hostTiming.watchdog} />, availability: evidence.hostTiming.watchdog.availability },
        { label: 'Last tick', value: <Value value={evidence.hostTiming.lastTick} />, availability: evidence.hostTiming.lastTick.availability },
        { label: 'Catch-up', value: <Value value={evidence.hostTiming.catchUp} />, availability: evidence.hostTiming.catchUp.availability },
      ],
    },
  ];

  return (
    <div className={styles.container}>
    <section className={styles.panel} aria-label="Scheduler resilience evidence">
      <header className={styles.header}>
        <h3>Resilience</h3>
        <p>Read-only evidence for the selected scheduler scope.</p>
        <p className={`${styles.readStatus} ${stale ? styles.warning : ''}`} role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
      </header>

      <div className={styles.groups}>
        {groups.map((group) => {
          const headingId = `${headingPrefix}-${group.title.toLowerCase().replaceAll(' ', '-')}`;
          return <section className={styles.group} aria-labelledby={headingId} key={group.title}>
            <h4 id={headingId}>{group.title}</h4>
            {group.description ? <p className={styles.groupDescription}>{group.description}</p> : null}
            <dl>{definitions(group.fields)}</dl>
          </section>;
        })}
      </div>
    </section>
    </div>
  );
}

export default ResiliencePanel;
