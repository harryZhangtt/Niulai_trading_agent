import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Phase = 'loading' | 'editing' | 'saving' | 'saved' | 'invalid' | 'failed' | 'uncertain';
type Operation = { id: string; entity: string; name: string };

function App() {
  const [entity, select] = useState('A');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [phases, setPhases] = useState<Record<string, Phase>>({ A: 'loading' });
  const [empty, setEmpty] = useState(false);
  const dirty = useRef(new Set<string>());
  const request = useRef(0);
  const locks = useRef(new Set<string>());
  const pending = useRef(new Map<string, Operation>());
  const nameInput = useRef<HTMLInputElement>(null);
  const phase = phases[entity] ?? 'loading';
  const update = (id: string, value: Phase) => setPhases(p => ({ ...p, [id]: value }));

  useEffect(() => {
    const generation = ++request.current;
    const controller = new AbortController();
    update(entity, pending.current.has(entity) ? 'uncertain' : 'loading');
    void (async () => {
      try {
        const response = await fetch(`/api/entities/${entity}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) });
        if (!response.ok) throw new Error('read failed');
        const data = await response.json() as { name: string | null };
        if (generation !== request.current || controller.signal.aborted) return;
        setEmpty(data.name === null);
        if (!dirty.current.has(entity)) setDrafts(d => ({ ...d, [entity]: data.name ?? '' }));
        update(entity, pending.current.has(entity) ? 'uncertain' : 'editing');
      } catch {
        if (generation === request.current && !controller.signal.aborted) update(entity, 'failed');
      }
    })();
    return () => controller.abort();
  }, [entity]);

  async function save() {
    if (locks.current.has(entity) || pending.current.has(entity)) return;
    const name = (drafts[entity] ?? '').trim();
    if (name.length < 3) {
      update(entity, 'invalid');
      nameInput.current?.focus();
      return;
    }
    locks.current.add(entity);
    const operation = { id: crypto.randomUUID(), entity, name };
    pending.current.set(entity, operation);
    update(entity, 'saving');
    try {
      const response = await fetch('/api/operations', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': operation.id },
        body: JSON.stringify(operation), signal: AbortSignal.timeout(5000),
      });
      if (response.status === 422) {
        pending.current.delete(operation.entity);
        update(operation.entity, 'invalid');
      } else if (!response.ok) {
        // A generic server error can occur after commit; status is still unknown.
        update(operation.entity, 'uncertain');
      } else {
        pending.current.delete(operation.entity);
        dirty.current.delete(operation.entity);
        update(operation.entity, 'saved');
      }
    } catch {
      update(operation.entity, 'uncertain');
    } finally {
      locks.current.delete(operation.entity);
    }
  }

  async function reconcile() {
    const operation = pending.current.get(entity);
    if (!operation || locks.current.has(entity)) return;
    locks.current.add(entity);
    try {
      const response = await fetch(`/api/operations/${operation.id}`, { signal: AbortSignal.timeout(5000) });
      if (!response.ok) return;
      const result = await response.json() as { status: string };
      if (result.status === 'complete') {
        pending.current.delete(operation.entity);
        dirty.current.delete(operation.entity);
        update(operation.entity, 'saved');
      }
    } catch {
      // Preserve the uncertain result and draft; do not create another mutation.
    } finally {
      locks.current.delete(operation.entity);
    }
  }

  const message: Record<Phase, string> = {
    loading: 'Loading profile…', editing: 'Ready to edit.', saving: 'Saving changes…', saved: 'Changes saved.',
    invalid: 'Use at least three characters. Your draft is preserved.',
    failed: 'Profile unavailable. Your draft is preserved.',
    uncertain: 'Save result unknown. Check the result before saving again.',
  };
  return <main>
    <header><p className="context">Synthetic verification fixture</p><h1>Profile editor</h1>
      <p>Check entity identity, drafts and safe recovery in one narrow flow.</p></header>
    <nav aria-label="Profiles">{['A', 'B'].map(id => <button key={id} aria-pressed={entity === id}
      onClick={() => select(id)}>Profile {id}</button>)}</nav>
    <section aria-labelledby="editor-title" className="editor">
      <h2 id="editor-title">Editing profile {entity}</h2>
      {empty && <p>No profile details yet. Add a name to get started.</p>}
      <label htmlFor="name">Display name</label>
      <input id="name" ref={nameInput} value={drafts[entity] ?? ''} aria-invalid={phase === 'invalid'}
        aria-describedby="result" disabled={phase === 'loading' || phase === 'saving' || phase === 'uncertain'} onChange={event => {
          dirty.current.add(entity); setDrafts(d => ({ ...d, [entity]: event.target.value }));
          if (phase === 'invalid') update(entity, 'editing');
        }}/>
      <div className="actions"><button onClick={() => void save()}
        disabled={phase === 'saving' || phase === 'loading' || phase === 'uncertain'}>Save changes</button>
        {phase === 'uncertain' && <button onClick={() => void reconcile()}>Check save result</button>}</div>
      <p id="result" role="status" aria-live="polite">{message[phase]}</p>
    </section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<App/>);
