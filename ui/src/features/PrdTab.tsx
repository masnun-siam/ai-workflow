import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import { keys, usePrd, useSavePrd } from '../api/hooks';
import { useStarter } from '../board/actions';
import { Banner, Button, EmptyState, useConfirm } from '../components';
import type { Feature } from '../lib/features';
import { mdToHtml } from '../lib/md';
import { PLAN_RUN } from '../lib/vocab';

export const CHANGED_MSG = 'This file changed on disk since you opened it, so nothing was saved. Reload it, then redo your edit.';
export const askArgs = (path: string, text: string) => `${path} --update ${text.trim()}`;

// mermaid is ~1MB, so it is only fetched when a PRD actually has a diagram.
async function renderDiagrams(root: HTMLElement | null) {
  const nodes = root ? Array.from(root.querySelectorAll<HTMLElement>('pre.mermaid')) : [];
  if (!nodes.length) return;
  const { default: mermaid } = await import('mermaid');
  const dark = getComputedStyle(document.documentElement).colorScheme === 'dark';
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'default' });
  await mermaid.run({ nodes, suppressErrors: true });
}

// A wide diagram fits the column with tiny labels; a click toggles it to natural size, scrolled sideways.
function toggleDiagram(e: React.MouseEvent) {
  const svg = (e.target as Element).closest('pre.mermaid')?.querySelector('svg');
  if (!svg) return;
  const full = !svg.style.width;
  svg.style.width = full ? `${svg.viewBox.baseVal.width}px` : '';
  svg.style.maxWidth = full ? 'none' : `${svg.viewBox.baseVal.width}px`;
  svg.parentElement!.classList.toggle('full', full);
}

export function PrdTab({ f, repo }: { f: Feature; repo: string }) {
  const path = f.prd.path;
  const q = usePrd(repo, path);
  const qc = useQueryClient();
  const save = useSavePrd();
  const confirm = useConfirm();
  const starter = useStarter();
  const [mode, setMode] = useState<'read' | 'edit'>('read');
  const [draft, setDraft] = useState('');
  const [err, setErr] = useState('');
  const [note, setNote] = useState('');
  const [ask, setAsk] = useState('');
  const data = q.data;
  const prose = useRef<HTMLDivElement>(null);
  useEffect(() => { if (mode === 'read') void renderDiagrams(prose.current); }, [mode, data?.text]);
  const branch = typeof data?.branch === 'string' ? data.branch : 'the current branch';
  const dirty = mode === 'edit' && !!data && draft !== data.text;

  const discard = async () => {
    if (dirty && !(await confirm({ title: 'Discard your edits?', okLabel: 'Discard', danger: true, body: <p>Your unsaved changes to this PRD will be lost.</p> }))) return false;
    setDraft(data?.text ?? '');
    setErr('');
    return true;
  };
  const doSave = () => {
    if (!data) return;
    setErr('');
    save.mutate(
      { repo, path, text: draft, base_sha: data.sha },
      {
        onSuccess: (r) => {
          const rr = r as { committed?: boolean; commit?: string; branch?: string };
          setNote(rr.committed ? `Committed ${rr.commit} on ${rr.branch} (not pushed)` : 'No changes to save');
          setMode('read');
        },
        onError: (e) => setErr(e instanceof ApiError && e.status === 409 ? CHANGED_MSG : e.message),
      },
    );
  };
  const reload = async () => {
    const r = await qc.fetchQuery({ queryKey: keys.prd(repo, path), queryFn: () => api.prd(repo, path), staleTime: 0 });
    setDraft(r.text);
    setErr('');
  };

  if (q.isError) return <EmptyState icon="alert" title="Could not read the PRD" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState>;
  if (!data) return <p className="muted" role="status">Loading the PRD…</p>;

  return (
    <div className="sess-grid">
      <div className="stack">
        <div className="row">
          <div className="seg" role="group" aria-label="PRD mode">
            <button type="button" className={mode === 'read' ? 'on' : ''} aria-pressed={mode === 'read'} onClick={async () => { if (mode === 'edit' && !(await discard())) return; setMode('read'); }}>Read</button>
            <button type="button" className={mode === 'edit' ? 'on' : ''} aria-pressed={mode === 'edit'} onClick={() => { if (mode !== 'edit') { setDraft(data.text); setNote(''); setMode('edit'); } }}>Edit</button>
          </div>
          <span className="grow" />
          <span className="muted mono" style={{ fontSize: 12 }}>{path}</span>
        </div>
        {note ? <p role="status" className="muted">{note}</p> : null}
        {mode === 'read' ? (
          <div ref={prose} onClick={toggleDiagram} className="prose box" style={{ padding: '18px 22px' }} dangerouslySetInnerHTML={{ __html: mdToHtml(data.text) }} />
        ) : (
          <div className="stack">
            <label className="sr" htmlFor="prd-text">PRD markdown</label>
            <textarea id="prd-text" className="f prd-edit" rows={16} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <Banner tone="review" icon="alert"><p>Saving commits only this file to <b>{branch}</b>, the branch the checkout is on. It is not pushed.</p></Banner>
            {err ? (
              <Banner tone="bad" icon="alert" action={err === CHANGED_MSG ? <Button sm onClick={reload}>Reload</Button> : undefined}><p>{err}</p></Banner>
            ) : null}
            <div className="row">
              <Button variant="primary" disabled={!dirty || save.isPending} onClick={doSave}>{save.isPending ? 'Saving…' : 'Save and commit'}</Button>
              <Button variant="ghost" onClick={async () => { if (await discard()) setMode('read'); }}>Discard</Button>
            </div>
          </div>
        )}
      </div>
      <div className="box">
        <h3>Ask Claude to change it</h3>
        <p className="muted" style={{ fontSize: 13 }}>Runs <code>/create-prd --update</code>, which records the decision in the PRD.</p>
        <label className="sr" htmlFor="prd-ask">What should change?</label>
        <textarea id="prd-ask" className="f" rows={4} placeholder="Example: Guests should be able to see reports but not export them." value={ask} onChange={(e) => setAsk(e.target.value)} />
        <Button disabled={!ask.trim() || starter.pending} onClick={async () => { const id = await starter.startSession({ repo, command: 'create-prd', args: askArgs(path, ask), ...PLAN_RUN }); if (id) setAsk(''); }}>Start update</Button>
      </div>
    </div>
  );
}
