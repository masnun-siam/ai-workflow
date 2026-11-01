// Send a prompt to the session (FR-20): queued while a turn is running, disabled while a question is pending.
import { useEffect, useRef, useState } from 'react';
import { usePrompt } from '../api/hooks';
import type { Session } from '../api/types';
import { Button, Icon } from '../components';
import { useAction } from '../shell/shortcuts';

export function Composer({ s }: { s: Session }) {
  const [text, setText] = useState('');
  const [note, setNote] = useState('');
  const send = usePrompt();
  const box = useRef<HTMLTextAreaElement>(null);
  const waiting = s.outcome === 'waiting';
  useAction({ label: 'Message this session', key: 'c', run: () => box.current?.focus(), disabled: waiting });
  // The note fades after a few seconds, or as soon as the user types again.
  useEffect(() => { if (text) setNote(''); }, [text]);
  useEffect(() => {
    if (!note) return;
    const t = setTimeout(() => setNote(''), 5000);
    return () => clearTimeout(t);
  }, [note]);
  const running = ['starting', 'running', 'limited'].includes(s.outcome);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || waiting || send.isPending) return;
    send.mutate({ id: s.id, text: t }, { onSuccess: (r) => { setText(''); setNote(r.state === 'queued' ? 'Queued: it goes out when this turn ends.' : 'Sent. The session is resuming.'); } });
  };
  return (
    <>
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={box}
        rows={1}
        maxLength={4000}
        aria-label="Message to this session"
        placeholder={waiting ? 'Answer the question above first' : running ? 'Send a message. It goes out when this turn ends.' : 'Send a message to continue this session'}
        disabled={waiting}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit(); }}
      />
      <Button variant="primary" icon type="submit" aria-label="Send" disabled={!text.trim() || waiting || send.isPending}><Icon n="send" /></Button>
    </form>
    {note || s.queued_prompt ? <p className="muted" role="status" style={{ fontSize: 13 }}>{note || `Queued: ${s.queued_prompt}`}</p> : null}
    </>
  );
}
