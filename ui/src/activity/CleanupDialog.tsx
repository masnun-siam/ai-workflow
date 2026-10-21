// Clean up old sessions (FR-19): finished sessions by repo; ones with unsaved work start unticked.
import { useEffect, useState } from 'react';
import { useCleanupSessions, useCleanupTargets } from '../api/hooks';
import type { CleanupItem } from '../api/types';
import { Button, Dialog, useToast } from '../components';
import { shortRepo } from '../lib/format';

export function CleanupDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useCleanupTargets(open);
  const clean = useCleanupSessions();
  const toast = useToast();
  const items: CleanupItem[] = q.data?.items ?? [];
  const [picked, setPicked] = useState<Set<string>>(new Set());
  useEffect(() => setPicked(new Set(items.filter((i) => !i.flags.length).map((i) => i.key))), [q.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const groups = [...items.reduce((m, i) => m.set(i.repo || 'Other', [...(m.get(i.repo || 'Other') ?? []), i]), new Map<string, CleanupItem[]>())];
  const flip = (k: string) => setPicked((p) => { const n = new Set(p); if (!n.delete(k)) n.add(k); return n; });
  const run = () =>
    clean.mutate([...picked], { onSuccess: (r) => { toast(`Removed ${r.removed} session${r.removed === 1 ? '' : 's'}`); onClose(); } });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Clean up old sessions"
      description="Removes finished sessions and their saved transcripts. Sessions marked with unsaved work are not ticked."
      showDescription
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="solid-danger" disabled={!picked.size || clean.isPending} onClick={run}>Remove {picked.size} session{picked.size === 1 ? '' : 's'}</Button></>}
    >
      {q.isLoading ? <p className="muted">Loading…</p> : null}
      {q.isError ? <p role="alert">Could not load: {q.error.message}</p> : null}
      {q.data && !items.length ? <p className="muted">Nothing to clean up.</p> : null}
      {groups.map(([repo, g]) => (
        <fieldset key={repo} style={{ border: 0, padding: 0, margin: 0 }}>
          <legend style={{ fontWeight: 700, marginBottom: 6 }}>{shortRepo(repo)}</legend>
          {g.map((i) => (
            <label key={i.key} className="row" style={{ padding: '4px 0', alignItems: 'flex-start' }}>
              <input type="checkbox" checked={picked.has(i.key)} onChange={() => flip(i.key)} style={{ marginTop: 3 }} />
              <span className="grow">{i.label}{i.flags.length ? <span className="muted"> · unsaved: {i.flags.join(', ')}</span> : null}</span>
            </label>
          ))}
        </fieldset>
      ))}
    </Dialog>
  );
}
