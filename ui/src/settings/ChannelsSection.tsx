import { type KeyboardEvent, useRef, useState } from 'react';
import { useSaveSettings, useSettings } from '../api/hooks';
import type { SlackChannel } from '../api/types';
import { Button, toast, useConfirm } from '../components';
import './settings.css';

const MAX_CHANNELS = 50;
const ID_RE = /^[CGD][A-Z0-9]{8,12}$/;

/** The server's messages for a bad name, so nothing it would refuse is sent. */
const nameError = (name: string) => (name.length < 1 || name.length > 60 ? 'channel name must be 1 to 60 characters' : '');
function idError(id: string, list: SlackChannel[]) {
  if (!ID_RE.test(id)) return 'channel id must look like C0123ABCD';
  return list.some((c) => c.id === id) ? `channel ${id} is already listed` : '';
}

/** A row's name: edited locally, saved on blur or Enter when it changed and is valid. */
export function NameCell({ name, label, error, disabled, onSave }: { name: string; label: string; error: (n: string) => string; disabled: boolean; onSave: (name: string) => void }) {
  const [draft, setDraft] = useState(name);
  const [seen, setSeen] = useState(name);
  if (name !== seen) { // the saved name changed (a save, or a revert): follow it
    setSeen(name);
    setDraft(name);
  }
  const err = error(draft.trim());
  return (
    <>
      <input
        className="f"
        aria-label={label}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => !err && draft.trim() !== name && onSave(draft.trim())}
        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
      />
      {err ? <p className="err-text" role="alert">{err}</p> : null}
    </>
  );
}

/** Slack channels: the saved list repos pick their grind channel from. Every change sends the whole list. */
export function ChannelsSection() {
  const settings = useSettings();
  const save = useSaveSettings();
  const confirm = useConfirm();
  const [over, setOver] = useState<SlackChannel[] | null>(null); // optimistic list while a save is in flight
  const [name, setName] = useState('');
  const [id, setId] = useState('');
  const [tried, setTried] = useState(false); // show the Add row's errors only after an Add
  const nameRef = useRef<HTMLInputElement>(null);

  if (!settings.data) return <section className="set-sec"><h2>Slack channels</h2><p className="muted" role="status">{settings.isError ? settings.error.message : 'Loading…'}</p></section>;
  const list = over ?? settings.data.slack_channels ?? [];
  const busy = save.isPending;

  const persist = async (next: SlackChannel[], done: string) => {
    setOver(next);
    try {
      await save.mutateAsync({ slack_channels: next });
      toast(done);
      return true;
    } catch {
      return false; // the error toast comes from the mutation cache
    } finally {
      setOver(null);
    }
  };

  const onDelete = async (ch: SlackChannel) => {
    const ok = await confirm({ title: `Delete ${ch.name}?`, body: <p>Repos that send their grind reviews to {ch.name} will have no channel until you pick another.</p>, okLabel: 'Delete', danger: true });
    if (ok) await persist(list.filter((c) => c.id !== ch.id), `Deleted ${ch.name}`);
  };
  const errs = { name: nameError(name.trim()), id: idError(id.trim(), list), full: list.length >= MAX_CHANNELS ? 'at most 50' : '' };
  const add = async () => {
    setTried(true);
    if (errs.name || errs.id || errs.full) return;
    const ch = { id: id.trim(), name: name.trim() };
    if (!(await persist([...list, ch], `Added ${ch.name}`))) return;
    setName('');
    setId('');
    setTried(false);
    nameRef.current?.focus();
  };
  const onEnter = (e: KeyboardEvent) => e.key === 'Enter' && void add();

  return (
    <section className="set-sec" aria-labelledby="set-channels-h">
      <div>
        <h2 id="set-channels-h">Slack channels</h2>
        <p className="muted">The channels a repo can send its grind reviews to. Copy the id from the channel's details in Slack.</p>
      </div>
      {list.length === 0 ? <p className="muted">No channels yet. Add one below, then pick it for a repo in Repositories.</p> : null}
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr><th>Name</th><th>Channel id</th><th><span className="sr">Delete</span></th></tr>
          </thead>
          <tbody>
            {list.map((ch) => (
              <tr key={ch.id}>
                <td><NameCell name={ch.name} label={`Name of ${ch.id}`} error={nameError} disabled={busy} onSave={(n) => void persist(list.map((c) => (c.id === ch.id ? { ...c, name: n } : c)), `Renamed ${ch.id}`)} /></td>
                <td className="mono">{ch.id}</td>
                <td><Button variant="danger" sm disabled={busy} onClick={() => void onDelete(ch)} aria-label={`Delete ${ch.name}`}>Delete</Button></td>
              </tr>
            ))}
            <tr>
              <td>
                <input ref={nameRef} className="f" aria-label="New channel name" placeholder="#reviews" value={name} disabled={busy} onChange={(e) => setName(e.target.value)} onKeyDown={onEnter} />
                {tried && errs.name ? <p className="err-text" role="alert">{errs.name}</p> : null}
              </td>
              <td>
                <input className="f mono" aria-label="New channel id" placeholder="C0123ABCD" value={id} disabled={busy} onChange={(e) => setId(e.target.value)} onKeyDown={onEnter} />
                {tried && errs.id ? <p className="err-text" role="alert">{errs.id}</p> : null}
              </td>
              <td>
                <Button sm disabled={busy} onClick={() => void add()}>Add</Button>
                {tried && errs.full ? <p className="err-text" role="alert">{errs.full}</p> : null}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
