import React, { useEffect, useState } from 'react';
import type { Notice } from '../vendor/contracts';
import { appendRevision, loadNotice } from '../vendor/client';
import { NoticePreview } from './Preview';

export default function App() {
  const [selected, setSelected] = useState('harbor');
  const [notice, setNotice] = useState<Notice | null>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [feedback, setFeedback] = useState('Loading notice…');
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFeedback('Loading notice…'); setFailed(false);
    loadNotice(selected).then(value => {
      const next = value as Notice;
      setNotice(next); setTitle(next.title); setBody(next.body); setFeedback('');
    }).catch(error => { setFeedback(String(error.message)); setFailed(true); });
  }, [selected]);
  async function save() {
    setSaving(true); setFailed(false); setFeedback('Saving revision…');
    try {
      const next = await appendRevision(selected, { operationId: crypto.randomUUID(), title, body }) as Notice;
      setNotice(next); setTitle(next.title); setBody(next.body); setFeedback('Revision saved.');
    } catch (error) { setFeedback(error instanceof Error ? error.message : String(error)); setFailed(true); }
    finally { setSaving(false); }
  }
  return <div className="desk"><header><div><h1>Dispatch Desk</h1><p>Keep passenger notices clear and current.</p></div><span className="desk-mark">Service communications</span></header>
    <main><section className="editor" aria-label="Notice editor"><h2>Edit a notice</h2>
      <label>Notice<select aria-label="Notice" value={selected} onChange={event => setSelected(event.target.value)}><option value="harbor">Harbor shuttle</option><option value="ridge">Ridge connection</option></select></label>
      <label>Title<input aria-label="Title" value={title} onChange={event => setTitle(event.target.value)} /></label>
      <label>Message<textarea aria-label="Message" rows={7} value={body} onChange={event => setBody(event.target.value)} /></label>
      <p className="hint">Saving adds a permanent revision to this notice.</p>
      <div className="actions"><button onClick={save}>{saving ? 'Saving revision…' : 'Save revision'}</button>{failed && <button className="secondary" onClick={save}>Retry</button>}</div>
      <p role={failed ? 'alert' : 'status'} className={failed ? 'feedback error' : 'feedback'}>{feedback}</p>
    </section>{notice && <NoticePreview notice={{ ...notice }} />}</main>
  </div>;
}
