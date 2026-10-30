// FR-8, FR-9: change the answers Away mode gave. One section per ticked round, prefilled with the logged picks.
import { useState } from 'react';
import { ApiError } from '../api/client';
import { useAfkChange } from '../api/hooks';
import type { AfkChangeBody, AfkLogEntry, AfkQuestion } from '../api/types';
import { Button, Dialog, useToast } from '../components';
import { clockText } from '../lib/format';
import { answered, buildAnswer, QuestionFields, type Ans } from '../questions/QuestionForm';

export type RoundEntry = AfkLogEntry & { id: string; questions: AfkQuestion[] };

const prefill = (l: RoundEntry): Ans[] => l.questions.map((q) => ({ labels: q.picked ?? [], other: '', useOther: false, none: false }));
const differs = (q: AfkQuestion, a: Ans) => a.useOther || a.none || a.labels.length !== (q.picked ?? []).length || a.labels.some((x) => !(q.picked ?? []).includes(x));

export function ChangeDialog({ rounds, onClose }: { rounds: RoundEntry[]; onClose: () => void }) {
  const toast = useToast();
  const change = useAfkChange();
  const [edits, setEdits] = useState<Record<string, Ans[]>>({});
  const [err, setErr] = useState('');
  const get = (l: RoundEntry) => edits[l.id] ?? prefill(l);
  const set = (l: RoundEntry, k: number, v: Partial<Ans>) => setEdits((e) => ({ ...e, [l.id]: get(l).map((x, j) => (j === k ? { ...x, ...v } : x)) }));
  const changed = rounds.filter((l) => l.questions.some((q, k) => differs(q, get(l)[k])));
  const ready = changed.length > 0 && rounds.every((l) => l.questions.every((q, k) => answered(q, get(l)[k])));

  const submit = () => {
    const changes: AfkChangeBody['changes'] = [];
    for (const l of changed) {
      const body = buildAnswer(l.id, l.questions, get(l));
      if ('error' in body) return setErr(body.error);
      changes.push({ id: l.id, answers: body.answers });
    }
    setErr('');
    change.mutate(changes, {
      onSuccess: ({ results }) => {
        const cmd = (sid: string) => rounds.find((l) => l.sid === sid)?.command ?? sid;
        toast(results.map((r) => `${cmd(r.sid)}: ${'error' in r ? r.error : r.state}`).join('; '));
        onClose();
      },
      onError: (er: ApiError) => setErr(er.message),
    });
  };

  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={`Change ${rounds.length} answer${rounds.length === 1 ? '' : 's'}`}
      description="Pick other options for the answers Away mode gave. Each changed session gets one new turn."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="you" onClick={submit} disabled={!ready || change.isPending}>
            {change.isPending ? 'Sending…' : 'Submit'}
          </Button>
        </>
      }
    >
      <div className="stack" style={{ gap: 20 }}>
        {rounds.map((l) => (
          <section key={l.id} className="stack qform" aria-label={`${l.command} ${clockText(l.at)}`}>
            <h3 style={{ fontSize: 14 }}>{l.command} <span className="faint">{clockText(l.at)}</span></h3>
            <QuestionFields qs={l.questions} ans={get(l)} onChange={(k, v) => set(l, k, v)} disabled={change.isPending} name={`${l.id}:`} />
          </section>
        ))}
        {err ? <p role="alert" style={{ color: 'var(--bad)' }}>{err}</p> : null}
      </div>
    </Dialog>
  );
}
