import { useEffect, useState } from 'react';
import { useNotifySettings, useSaveNotify } from '../api/hooks';
import type { NotifySettings } from '../api/types';
import { Banner, Button, Chip, toast } from '../components';
import './settings.css';

type Perm = NotificationPermission | 'unsupported';
const permission = (): Perm => (typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);

interface Form {
  server: string;
  topic: string;
  user: string;
  public_url: string;
  token: string;
  password: string;
  clear_token: boolean;
  clear_password: boolean;
}
const fromServer = (n: NotifySettings): Form => ({ server: n.server, topic: n.topic, user: n.user, public_url: n.public_url, token: '', password: '', clear_token: false, clear_password: false });

/**
 * The body to POST. A secret left empty is not sent, so the server keeps the stored one; "Remove" sends ''.
 * Fields an environment variable controls are not sent either: the environment wins and the form shows them read-only.
 */
export function notifyBody(f: Form, env: string[] = []): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const k of ['server', 'topic', 'user'] as const) if (!env.includes(k)) body[k] = f[k];
  body.public_url = f.public_url;
  for (const k of ['token', 'password'] as const) {
    if (env.includes(k)) continue;
    if (f[`clear_${k}`]) body[k] = '';
    else if (f[k]) body[k] = f[k];
  }
  return body;
}

/** Notifications: the browser's permission state, and ntfy phone push. */
export function NotificationsSection() {
  const q = useNotifySettings();
  const save = useSaveNotify();
  const [perm, setPerm] = useState<Perm>(permission);
  const [form, setForm] = useState<Form | null>(null);
  const data = q.data;
  useEffect(() => {
    if (data && form === null) setForm(fromServer(data));
  }, [data, form]);

  const ask = async () => setPerm(await Notification.requestPermission());
  const set = (k: keyof Form, v: string | boolean) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const onSave = async () => {
    if (!form || !data) return;
    try {
      const r = await save.mutateAsync(notifyBody(form, data.env));
      setForm(fromServer(r));
      toast('Notifications saved');
    } catch {
      /* toasted */
    }
  };

  const env = data?.env ?? [];
  const field = (k: 'server' | 'topic' | 'user' | 'public_url', label: string, hint?: string, type = 'text', ph = '') => (
    <label className="lbl" htmlFor={`ntfy-${k}`}>
      {label}
      {hint ? <span className="hint">{hint}</span> : null}
      <input id={`ntfy-${k}`} className="f" type={type} autoComplete="off" spellCheck={false} placeholder={ph} value={form?.[k] ?? ''} disabled={env.includes(k)} onChange={(e) => set(k, e.target.value)} />
      {env.includes(k) ? <span className="hint">Set by the environment (AIW_NTFY_{k.toUpperCase()}), which wins over this form.</span> : null}
    </label>
  );
  const secret = (k: 'token' | 'password', label: string) => {
    const isSet = k === 'token' ? data?.token_set : data?.password_set;
    return (
      <>
        <label className="lbl" htmlFor={`ntfy-${k}`}>
          {label}
          <span className="hint">{isSet ? 'Saved. Leave empty to keep it.' : 'Not set.'}</span>
          <input id={`ntfy-${k}`} className="f" type="password" autoComplete="new-password" placeholder={isSet ? '••••••••' : ''} value={form?.[k] ?? ''} disabled={env.includes(k) || !!form?.[`clear_${k}`]} onChange={(e) => set(k, e.target.value)} />
          {env.includes(k) ? <span className="hint">Set by the environment (AIW_NTFY_{k.toUpperCase()}), which wins over this form.</span> : null}
        </label>
        {isSet && !env.includes(k) ? (
          <label className="check-row" htmlFor={`ntfy-clear-${k}`}>
            <input id={`ntfy-clear-${k}`} type="checkbox" checked={!!form?.[`clear_${k}`]} onChange={(e) => set(`clear_${k}`, e.target.checked)} />
            Remove the saved {label.toLowerCase()}
          </label>
        ) : null}
      </>
    );
  };

  return (
    <section className="set-sec" aria-labelledby="set-notify-h">
      <h2 id="set-notify-h">Notifications</h2>
      <div className="stack" style={{ gap: 8 }}>
        <h3>This browser</h3>
        {perm === 'granted' ? (
          <p className="row"><Chip tone="ship">On</Chip><span className="muted">You get a notification when a session needs you, even while this tab is in the background.</span></p>
        ) : perm === 'denied' ? (
          <Banner tone="review" icon="alert">
            <p>Browser notifications are blocked for this site.</p>
            <p className="muted">Allow them in the browser's site settings (the icon left of the address bar), then reload this page.</p>
          </Banner>
        ) : perm === 'unsupported' ? (
          <p className="muted">This browser does not support notifications. Phone push below still works.</p>
        ) : (
          <div className="row wrap">
            <span className="muted">Off. Turn them on to get alerts while this tab is in the background.</span>
            <Button onClick={() => void ask()}>Enable browser notifications</Button>
          </div>
        )}
      </div>
      <h3>Phone push (ntfy)</h3>
      <p className="set-note">Pushes a notification through <a href="https://ntfy.sh" target="_blank" rel="noopener noreferrer">ntfy</a> when a session waits on you, finishes or fails. A saved token or password never comes back to the browser.</p>
      {q.isError ? <p className="err-text" role="alert">{q.error.message}</p> : null}
      {!form && !q.isError ? <p className="muted" role="status">Loading…</p> : null}
      {form ? (
        <form className="set-form" onSubmit={(e) => { e.preventDefault(); void onSave(); }} noValidate>
          {field('server', 'Server', undefined, 'url', 'https://ntfy.sh')}
          {field('topic', 'Topic')}
          {secret('token', 'Access token')}
          {field('user', 'User (instead of a token)')}
          {secret('password', 'Password')}
          {field('public_url', 'Public URL of this UI', 'Notification links open it, for example your tailnet address.', 'url', 'https://mac.tailnet.ts.net')}
          <div><Button variant="primary" type="submit" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save notifications'}</Button></div>
        </form>
      ) : null}
    </section>
  );
}
