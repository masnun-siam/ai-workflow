import { type KeyboardEvent, useRef, useState } from 'react';
import { useSaveSettings, useSettings } from '../api/hooks';
import type { Reviewer, Settings } from '../api/types';
import { Banner, Button, toast, useConfirm } from '../components';
import { NameCell } from './ChannelsSection';
import './settings.css';

const MAX_REVIEWERS = 50;
const SLACK_RE = /^[UW][A-Z0-9]{8,12}$/;
const LOGIN_RE = /^[A-Za-z0-9-]{1,39}$/;

/** The server's messages (#839), so nothing it would refuse is sent. */
const nameError = (name: string) => (name.length < 1 || name.length > 60 ? 'reviewer name must be 1 to 60 characters' : '');
function slackError(id: string, list: Reviewer[]) {
  if (!id) return '';
  if (!SLACK_RE.test(id)) return 'Slack id must look like U0123ABCD';
  return list.some((r) => r.slack_id === id) ? `Slack id ${id} is already listed` : '';
}
function loginError(login: string, list: Reviewer[]) {
  if (!login) return '';
  if (!LOGIN_RE.test(login)) return 'not a GitHub login';
  const low = login.toLowerCase();
  return list.some((r) => r.github_login.toLowerCase() === low) ? `login ${low} is already listed` : '';
}

/** "a", "a and b", "a, b and c". */
const joinAnd = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);

/** Where a reviewer is used, as the delete confirm names it: "It is active and overrides o/r." or "". */
function usage(r: Reviewer, s: Settings) {
  const active = (s.active_reviewers ?? []).includes(r.id);
  const repos = Object.entries(s.repos ?? {}).filter(([, v]) => v.reviewers?.includes(r.id)).map(([slug]) => slug);
  const parts = [active ? 'is active' : '', repos.length ? `overrides ${joinAnd(repos)}` : ''].filter(Boolean);
  return parts.length ? `It ${parts.join(' and ')}.` : '';
}

/** Reviewers: the saved grind reviewers, and the Active ticks that swap them. List edits send the whole list. */
export function ReviewersSection() {
  const settings = useSettings();
  const save = useSaveSettings();
  const confirm = useConfirm();
  const [over, setOver] = useState<Reviewer[] | null>(null); // optimistic list while a save is in flight
  const [overActive, setOverActive] = useState<string[] | null>(null); // optimistic ticks
  const [name, setName] = useState('');
  const [slack, setSlack] = useState('');
  const [login, setLogin] = useState('');
  const [tried, setTried] = useState(false); // show the Add row's errors only after an Add
  const nameRef = useRef<HTMLInputElement>(null);

  if (!settings.data) return <section className="set-sec"><h2>Reviewers</h2><p className="muted" role="status">{settings.isError ? settings.error.message : 'Loading…'}</p></section>;
  const data = settings.data;
  const list = over ?? data.reviewers ?? [];
  const active = overActive ?? data.active_reviewers ?? [];
  const busy = save.isPending;

  // Each list edit omits id on a new entry only: the server makes it, and existing ids stay stable through renames.
  const persist = async (next: (Omit<Reviewer, 'id'> & { id?: string })[], done: string) => {
    setOver(next.map((r) => ({ id: '', ...r })));
    try {
      await save.mutateAsync({ reviewers: next as Reviewer[] }); // the PUT takes a new entry without its id
      toast(done);
      return true;
    } catch {
      return false; // the error toast comes from the mutation cache
    } finally {
      setOver(null);
    }
  };

  const tick = async (id: string, on: boolean) => {
    const next = on ? [...active, id] : active.filter((x) => x !== id);
    setOverActive(next);
    try {
      await save.mutateAsync({ active_reviewers: next });
    } catch {
      // reverts below; the cache toasts the error
    } finally {
      setOverActive(null);
    }
  };

  const onDelete = async (r: Reviewer) => {
    const used = usage(r, data);
    const ok = await confirm({ title: `Delete ${r.name}?`, body: used ? <p>{used}</p> : undefined, okLabel: 'Delete', danger: true });
    if (ok) await persist(list.filter((x) => x.id !== r.id), `Deleted ${r.name}`);
  };

  const v = { name: name.trim(), slack: slack.trim(), login: login.trim() };
  const errs = {
    name: nameError(v.name),
    slack: !v.slack && !v.login ? 'add a Slack id or a GitHub login' : slackError(v.slack, list),
    login: loginError(v.login, list),
    full: list.length >= MAX_REVIEWERS ? 'at most 50' : '',
  };
  const add = async () => {
    setTried(true);
    if (errs.name || errs.slack || errs.login || errs.full) return;
    if (!(await persist([...list, { name: v.name, slack_id: v.slack, github_login: v.login }], `Added ${v.name}`))) return;
    setName('');
    setSlack('');
    setLogin('');
    setTried(false);
    nameRef.current?.focus();
  };
  const onEnter = (e: KeyboardEvent) => e.key === 'Enter' && void add();
  const err = (msg: string) => (tried && msg ? <p className="err-text" role="alert">{msg}</p> : null);

  return (
    <section className="set-sec" aria-labelledby="set-reviewers-h">
      <div>
        <h2 id="set-reviewers-h">Reviewers</h2>
        <p className="muted">Who grind asks to review a PR. Tick <strong>Active</strong> on the ones every repo uses; untick one and tick another to swap.</p>
      </div>
      {active.length === 0 ? (
        <Banner tone="review" icon="alert">No active reviewer: Slack repos mention {data.bot_label ?? 'the channels.json bot'}, GitHub repos skip grinding.</Banner>
      ) : null}
      {list.length === 0 ? <p className="muted">No reviewers yet. Add a bot or a person below, by Slack id, GitHub login or both.</p> : null}
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr><th>Name</th><th>Slack id</th><th>GitHub login</th><th>Active</th><th><span className="sr">Delete</span></th></tr>
          </thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.id || r.name}>
                <td><NameCell name={r.name} label={`Name of ${r.name}`} error={nameError} disabled={busy} onSave={(n) => void persist(list.map((x) => (x.id === r.id ? { ...x, name: n } : x)), `Renamed ${n}`)} /></td>
                <td className="mono">{r.slack_id || '—'}</td>
                <td className="mono">{r.github_login || '—'}</td>
                <td><input type="checkbox" aria-label={`Active: ${r.name}`} checked={active.includes(r.id)} disabled={busy} onChange={(e) => void tick(r.id, e.target.checked)} /></td>
                <td><Button variant="danger" sm disabled={busy} onClick={() => void onDelete(r)} aria-label={`Delete ${r.name}`}>Delete</Button></td>
              </tr>
            ))}
            <tr>
              <td>
                <input ref={nameRef} className="f" aria-label="New reviewer name" placeholder="Masum" value={name} disabled={busy} onChange={(e) => setName(e.target.value)} onKeyDown={onEnter} />
                {err(errs.name)}
              </td>
              <td>
                <input className="f mono" aria-label="New reviewer Slack id" placeholder="U0123ABCD" value={slack} disabled={busy} onChange={(e) => setSlack(e.target.value)} onKeyDown={onEnter} />
                {err(errs.slack)}
              </td>
              <td>
                <input className="f mono" aria-label="New reviewer GitHub login" placeholder="gsm-masum" value={login} disabled={busy} onChange={(e) => setLogin(e.target.value)} onKeyDown={onEnter} />
                {err(errs.login)}
              </td>
              <td colSpan={2}>
                <Button sm disabled={busy} onClick={() => void add()}>Add</Button>
                {err(errs.full)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
