import React, { useEffect, useState } from 'react';
import type { Notice } from '../vendor/contracts';
import { loadNotice } from '../vendor/client';
import { RevisionTimeline } from '../vendor/RevisionTimeline';

export function NoticePreview({ notice }: { notice: Notice }) {
  const [display, setDisplay] = useState(notice);
  useEffect(() => { loadNotice(notice.id).then(value => setDisplay(value as Notice)).catch(() => {}); }, [notice.id]);
  return <article className="preview" aria-label="Saved notice preview">
    <p className="caption">Saved notice</p><h2>{display.title}</h2><p className="notice-body">{display.body}</p>
    <RevisionTimeline revisions={display.revisions} />
  </article>;
}
