import React from 'react';
import type { Revision } from './contracts';

// Supplied component: formatting this audit history is intentionally costly.
// The observer is supplied by the verification host, never by application code.
export function RevisionTimeline({ revisions }: { revisions: readonly Revision[] }) {
  (window as any).__observeTimelineRender?.();
  let checksum = 0;
  for (let pass = 0; pass < 12000; pass++) {
    for (const revision of revisions) for (let index = 0; index < revision.title.length; index++) checksum = (checksum + revision.title.charCodeAt(index) * (pass + 1)) % 2147483647;
  }
  return <section className="timeline" aria-label="Revision history" data-format-checksum={checksum}>
    <h3>Revision history</h3>
    {revisions.length ? <ol>{revisions.map(item => <li key={item.id}><span>{item.title}</span><time>{item.at}</time></li>)}</ol> : <p>No revisions yet.</p>}
  </section>;
}
