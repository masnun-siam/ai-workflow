import { useEffect, useState } from 'react';
import { approve, postError, ShareError, shareToken, withdraw } from './api';
import { fits, NAME_MAX, NameField, type Identity } from './Comments';
import { clearApproval, getApproval, setApproval, type StoredApproval } from './storage';
import type { PublicApproval } from './types';

const norm = (s: string) => s.trim().toLowerCase();
const listed = (approvals: PublicApproval[], name: string) => approvals.some((a) => norm(a.name) === norm(name));

/** What the control shows: a held key for a listed name is "withdraw", a listed name alone is "approved". */
export function approveState(approvals: PublicApproval[], storedName: string, stored: StoredApproval | null): 'withdraw' | 'approved' | 'approve' {
  if (stored && listed(approvals, stored.name)) return 'withdraw';
  return storedName && listed(approvals, storedName) ? 'approved' : 'approve';
}

const beforeEdit = (at: string, updatedAt: string) => Date.parse(at) < Date.parse(updatedAt);

interface Props { approvals: PublicApproval[]; updatedAt: string; who: Identity; onList: (f: (cur: PublicApproval[]) => PublicApproval[]) => void; reload: () => void; onGone: () => void }

export function Approve({ approvals, updatedAt, who, onList, reload, onGone }: Props) {
  const token = shareToken();
  const [stored, setStored] = useState(() => getApproval(token));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const state = approveState(approvals, who.stored, stored);

  // A key whose name is no longer listed (deleted by the author, or a re-share) is dead.
  useEffect(() => {
    if (stored && state !== 'withdraw') { clearApproval(token); setStored(null); }
  }, [stored, state, token]);

  const run = async (go: () => Promise<void>, on404?: () => void) => {
    setBusy(true); setError('');
    try { await go(); } catch (e) {
      if (e instanceof ShareError && e.status === 404 && on404) on404();
      else if (e instanceof ShareError && e.status === 404) onGone();
      else setError(postError(e, true));
    } finally { setBusy(false); }
  };

  const give = () => run(async () => {
    const r = await approve(who.name);
    who.remember(who.name);
    if (r.key) { setApproval(token, r.name, r.key); setStored({ name: r.name, key: r.key }); }
    onList((cur) => (listed(cur, r.name) ? cur : [...cur, { name: r.name, at: r.at }]));
  });

  const take = () => stored && run(async () => {
    await withdraw(stored.name, stored.key);
    clearApproval(token); setStored(null);
    onList((cur) => cur.filter((a) => norm(a.name) !== norm(stored.name)));
  }, () => {
    setError('That approval is no longer there');
    clearApproval(token); setStored(null);
    reload();
  });

  const n = approvals.length;
  return (
    <section aria-label="Approvals" className="approve">
      {state === 'approve' && <NameField who={who} label="Your name to approve" />}
      {state === 'approve' && <button type="button" className="btn primary sm" disabled={busy || !fits(who.name, NAME_MAX)} onClick={give}>Approve</button>}
      {state === 'withdraw' && <button type="button" className="btn sm" disabled={busy} onClick={take}>You approved · Withdraw</button>}
      {state === 'approved' && <p>Approved as {who.stored}</p>}
      {error && <p role="alert" className="err">{error}</p>}
      {n > 0 && (
        <>
          <p>{n} {n === 1 ? 'approval' : 'approvals'}</p>
          <ul className="plain">
            {approvals.map((a) => <li key={a.name}>{a.name}{beforeEdit(a.at, updatedAt) && <span className="muted"> · before last edit</span>}</li>)}
          </ul>
        </>
      )}
    </section>
  );
}
