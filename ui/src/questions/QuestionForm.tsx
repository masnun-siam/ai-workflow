// FR-9: the question form, used in the Inbox and on the session page. Re-checks the session every 3 s
// (useSession) so the submit button unlocks when the Claude process exits.
import { useState } from 'react';
import { useAnswer, useSession } from '../api/hooks';
import { ApiError } from '../api/client';
import type { AnswerBody, PendingQuestion, Question } from '../api/types';
import { Button, Icon, useToast } from '../components';
import { mdToHtml } from '../lib/md';

const REC = ' (Recommended)';
const MAX_OTHER = 4000;
export const displayLabel = (l: string) => (l.endsWith(REC) ? l.slice(0, -REC.length) : l);
/** The recommended option's label: the question's `recommended`, else an option tagged "(Recommended)". */
export const recommendedOf = (q: Question) => q.recommended || q.options.find((o) => o.label.endsWith(REC))?.label || null;

interface Ans {
  labels: string[];
  other: string;
  useOther: boolean;
}
export const initialAnswers = (qs: Question[]): Ans[] =>
  qs.map((q) => {
    const r = recommendedOf(q);
    return { labels: r ? [r] : [], other: '', useOther: false };
  });
const answered = (q: Question, a: Ans) => (a.useOther && q.allowFreeText ? a.other.trim().length > 0 : a.labels.length > 0);

/** The POST /answer body, or an error message. */
export function buildAnswer(roundId: string, qs: Question[], ans: Ans[]): AnswerBody | { error: string } {
  const answers: AnswerBody['answers'] = {};
  for (let i = 0; i < qs.length; i++) {
    const q = qs[i];
    const a = ans[i];
    const name = q.question || q.header || `Question ${i + 1}`;
    if (!answered(q, a)) return { error: `Please answer "${name}"` };
    if (a.useOther && q.allowFreeText) {
      const other = a.other.trim();
      if (other.length > MAX_OTHER) return { error: `Answer to "${name}" is longer than ${MAX_OTHER} characters` };
      answers[String(i)] = { other };
    } else answers[String(i)] = { labels: [...a.labels] };
  }
  return { round_id: roundId, answers };
}

export function QuestionForm({ sessionId, onSent }: { sessionId: string; onSent?: () => void }) {
  const q = useSession(sessionId);
  const s = q.data;
  const pending: PendingQuestion | null = s && s.waiting && s.pending_question ? s.pending_question : null;
  if (!pending) {
    return <p className="muted" role="status">{q.isLoading ? 'Loading the question…' : 'Nothing to answer here.'}</p>;
  }
  // keyed by round: a new round resets the picks, a poll of the same round keeps them
  return <Form key={pending.id} sessionId={sessionId} pending={pending} alive={s!.outcome === 'waiting' && !s!.ended_at} onSent={onSent} reload={() => void q.refetch()} />;
}

function Form({ sessionId, pending, alive, onSent, reload }: { sessionId: string; pending: PendingQuestion; alive: boolean; onSent?: () => void; reload: () => void }) {
  const qs = pending.questions;
  const n = qs.length;
  const toast = useToast();
  const answer = useAnswer();
  const [ans, setAns] = useState(() => initialAnswers(qs));
  const [err, setErr] = useState('');
  const [stale, setStale] = useState(false);
  const set = (k: number, v: Partial<Ans>) => setAns((a) => a.map((x, j) => (j === k ? { ...x, ...v } : x)));
  const ok = qs.every((q, i) => answered(q, ans[i]));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (alive || answer.isPending) return;
    const body = buildAnswer(pending.id, qs, ans);
    if ('error' in body) return setErr(body.error);
    setErr('');
    answer.mutate(
      { id: sessionId, body },
      {
        onSuccess: () => {
          toast('Answer sent, session resuming');
          onSent?.();
        },
        onError: (er: ApiError) => {
          const live = er.status === 409 && /still running/.test(er.message);
          setStale(er.status === 409 && !live);
          setErr(er.message);
        },
      },
    );
  };

  return (
    <form className="qform" onSubmit={submit}>
      {qs.map((q, k) => {
        const rec = recommendedOf(q);
        const name = `q${k}`;
        return (
          <fieldset key={k} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} disabled={answer.isPending}>
            <legend className="sr">{q.question}</legend>
            <div className="q-h">{n > 1 ? `${k + 1} of ${n}  ·  ` : ''}{q.header || 'Question'}</div>
            {q.question ? <div className="q-text prose" dangerouslySetInnerHTML={{ __html: mdToHtml(q.question) }} /> : null}
            <div className="opts">
              {q.options.map((o) => {
                const on = !ans[k].useOther && ans[k].labels.includes(o.label);
                return (
                  <label key={o.label} className={`opt${on ? ' on' : ''}`}>
                    <input
                      type={q.multiSelect ? 'checkbox' : 'radio'}
                      name={name}
                      checked={on}
                      onChange={() =>
                        set(k, {
                          useOther: false,
                          labels: q.multiSelect ? (on ? ans[k].labels.filter((x) => x !== o.label) : [...(ans[k].useOther ? [] : ans[k].labels), o.label]) : [o.label],
                        })
                      }
                    />
                    <span>
                      <span style={{ fontWeight: 600 }}>{displayLabel(o.label)}</span>
                      {o.label === rec ? <span className="rec">Recommended</span> : null}
                      {o.description ? <div className="d prose" dangerouslySetInnerHTML={{ __html: mdToHtml(o.description) }} /> : null}
                      {o.preview ? <pre className="q-preview">{o.preview}</pre> : null}
                    </span>
                  </label>
                );
              })}
              {q.allowFreeText ? (
                <label className={`opt${ans[k].useOther ? ' on' : ''}`}>
                  <input type={q.multiSelect ? 'checkbox' : 'radio'} name={name} checked={ans[k].useOther} onChange={() => set(k, { useOther: !ans[k].useOther || !q.multiSelect, labels: [] })} />
                  <span className="stack" style={{ gap: 6 }}>
                    <span style={{ fontWeight: 600 }}>Something else</span>
                    {ans[k].useOther ? (
                      <textarea className="f" rows={2} maxLength={MAX_OTHER} autoFocus placeholder="Write your own answer" aria-label={`Your own answer to: ${q.question}`} value={ans[k].other} onChange={(e) => set(k, { other: e.target.value })} />
                    ) : null}
                  </span>
                </label>
              ) : null}
            </div>
          </fieldset>
        );
      })}
      <div className="row wrap">
        <Button variant="you" type="submit" disabled={!ok || alive || answer.isPending}>
          <Icon n="send" />
          {answer.isPending ? 'Sending…' : n > 1 ? `Send ${n} answers and resume` : 'Send answer and resume'}
        </Button>
        {alive ? (
          <span className="muted" role="status" style={{ fontSize: 13 }}>
            <Icon n="clock" s={13} /> Claude is still finishing its turn. Sending unlocks when it exits.
          </span>
        ) : (
          <span className="faint" style={{ fontSize: 13 }}>Recommended options are pre-selected.</span>
        )}
      </div>
      {err ? (
        <p role="alert" style={{ color: 'var(--bad)' }}>
          {stale ? <strong>Already answered. </strong> : null}
          {err}
          {stale ? <> <Button sm onClick={reload}>Reload</Button></> : null}
        </p>
      ) : null}
    </form>
  );
}
