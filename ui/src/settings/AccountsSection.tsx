import { useEffect, useState } from 'react';
import { api } from '../api/endpoints';
import { useApiMutation, useSaveSettings, useSessions, useSettings } from '../api/hooks';
import type { ClaudeCommand } from '../api/types';
import { Button, Chip, Icon, toast } from '../components';
import { clockText } from '../lib/format';
import { limitedUntil } from '../start/startLogic';
import './settings.css';

type Test = { ok?: boolean; message: string };

/** Claude accounts: label + command rows, the default, Test, add, remove. Saves only commands and default. */
export function AccountsSection() {
  const settings = useSettings();
  const sessions = useSessions();
  const save = useSaveSettings();
  const test = useApiMutation((cmd: string) => api.testAccount(cmd), [], { quiet: true });
  const [rows, setRows] = useState<ClaudeCommand[] | null>(null);
  const [def, setDef] = useState('');
  const [tests, setTests] = useState<Record<number, Test>>({});

  const data = settings.data;
  useEffect(() => {
    if (data && rows === null) {
      setRows(data.commands.map((c) => ({ ...c })));
      setDef(data.default);
    }
  }, [data, rows]);
  if (!rows) return <section className="set-sec"><h2>Claude accounts</h2><p className="muted" role="status">{settings.isError ? settings.error.message : 'Loading…'}</p></section>;

  const dirty = !!data && (JSON.stringify(rows.map(({ label, cmd }) => [label, cmd])) !== JSON.stringify(data.commands.map(({ label, cmd }) => [label, cmd])) || def !== data.default);
  // Renaming the default keeps it the default.
  const edit = (i: number, k: 'label' | 'cmd', v: string) => {
    setRows(rows.map((c, j) => (j === i ? { ...c, [k]: v } : c)));
    if (k === 'label' && def === rows[i].label) setDef(v);
  };
  const remove = (i: number) => {
    const next = rows.filter((_, j) => j !== i);
    setRows(next);
    setTests({});
    if (def === rows[i].label) setDef(next[0]?.label ?? '');
  };
  const runTest = async (i: number) => {
    setTests((t) => ({ ...t, [i]: { message: 'Testing…' } }));
    try {
      const r = await test.mutateAsync(rows[i].cmd);
      setTests((t) => ({ ...t, [i]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [i]: { ok: false, message: (e as Error).message } }));
    }
  };
  const onSave = async () => {
    if (rows.some((r) => !r.label.trim() || !r.cmd.trim())) return toast.error('Every account needs a label and a command');
    try {
      const s = await save.mutateAsync({ commands: rows, default: def });
      setRows(s.commands.map((c) => ({ ...c })));
      setDef(s.default);
      setTests({});
      toast('Accounts saved');
    } catch {
      /* toasted */
    }
  };

  return (
    <section className="set-sec" aria-labelledby="set-acct-h">
      <div>
        <h2 id="set-acct-h">Claude accounts</h2>
        <p className="muted">Each account is a command that starts Claude, like <code>cc masum</code>. Sessions can run on any of them; a limited account queues its sessions until reset. The first row is plain <code>claude</code>: rename it to tell your accounts apart.</p>
      </div>
      {rows.map((a, i) => {
        const until = limitedUntil(rows, a.label, sessions.data?.limits);
        const t = tests[i];
        return (
          <div key={i} className="acct-row" role="group" aria-label={`Account ${a.label || i + 1}`}>
            <input className="f" aria-label="Label" placeholder="Label (Masum)" value={a.label} onChange={(e) => edit(i, 'label', e.target.value)} />
            <input className="f mono cmd" aria-label="Command" placeholder="cc masum" value={a.cmd} readOnly={a.builtin} title={a.builtin ? 'The built-in command; rename it with the label' : undefined} onChange={(e) => edit(i, 'cmd', e.target.value)} />
            <label className="radio">
              <input type="radio" name="default-account" checked={!!a.label && def === a.label} disabled={!a.label} onChange={() => setDef(a.label)} />
              Default
            </label>
            <Button sm onClick={() => void runTest(i)} disabled={!a.cmd.trim() || test.isPending}>Test</Button>
            {a.builtin ? <span className="muted">Built in</span> : <Button variant="danger" sm aria-label={`Remove ${a.label || 'account'}`} onClick={() => remove(i)}>Remove</Button>}
            {until ? <Chip tone="review">Limited until {clockText(until)}</Chip> : null}
            {t ? <span className={t.ok === false ? 'err-text' : 'muted'} role="status">{t.message}</span> : null}
          </div>
        );
      })}
      <div className="row wrap">
        <Button onClick={() => setRows([...rows, { label: '', cmd: '' }])}><Icon n="plus" />Add account</Button>
        <Button variant="primary" onClick={() => void onSave()} disabled={!dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save accounts'}</Button>
      </div>
    </section>
  );
}
