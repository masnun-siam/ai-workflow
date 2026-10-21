import { useEffect, useState } from 'react';
import { useReviewSettings, useSaveReview } from '../api/hooks';
import type { ReviewSettings } from '../api/types';
import { Button, Chip, toast, useConfirm } from '../components';
import { lensName } from '../lib/vocab';
import './settings.css';

interface Cfg {
  max_rounds: string;
  default_lenses: string[];
  lenses: Record<string, string>;
}
const fromServer = (r: ReviewSettings): Cfg => ({ max_rounds: String(r.max_rounds), default_lenses: [...r.default_lenses], lenses: { ...r.lenses } });
export const validRounds = (s: string) => /^\d+$/.test(s.trim()) && Number(s) >= 1 && Number(s) <= 10;

/** Peer review: rounds, default lenses, per-lens prompts (an edited one is marked), reset to the plugin defaults. */
export function ReviewSection() {
  const q = useReviewSettings();
  const save = useSaveReview();
  const confirm = useConfirm();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const data = q.data;
  useEffect(() => {
    if (data && cfg === null) setCfg(fromServer(data));
  }, [data, cfg]);

  if (!cfg || !data) return <section className="set-sec"><h2>Peer review</h2><p className="muted" role="status">{q.isError ? q.error.message : 'Loading…'}</p></section>;
  const names = Object.keys(cfg.lenses);
  const roundsOk = validRounds(cfg.max_rounds);
  const edited = (n: string) => !!data.shipped && cfg.lenses[n] !== data.shipped.lenses[n];

  const send = async (body: Record<string, unknown>, done: string) => {
    try {
      setCfg(fromServer(await save.mutateAsync(body)));
      toast(done);
    } catch {
      /* toasted */
    }
  };
  const reset = async () => {
    const ok = await confirm({
      title: 'Reset peer review?',
      body: <p>Rounds, default lenses and every lens prompt go back to the plugin's defaults. Your edits are removed.</p>,
      okLabel: 'Reset to defaults',
      danger: true,
    });
    if (ok) await send({ reset: true }, 'Peer review reset');
  };

  return (
    <section className="set-sec" aria-labelledby="set-review-h">
      <div>
        <h2 id="set-review-h">Peer review</h2>
        <p className="muted">How a review panel runs. Your changes are kept apart from the plugin's defaults, so an update still brings new defaults for anything you didn't change.</p>
      </div>
      <form
        className="set-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (roundsOk) void send({ max_rounds: Number(cfg.max_rounds), default_lenses: cfg.default_lenses, lenses: cfg.lenses }, 'Peer review saved');
        }}
        noValidate
      >
        <label className="lbl" htmlFor="rev-rounds" style={{ maxWidth: 260 }}>
          Rounds before it asks you
          <span className="hint">1 to 10</span>
          <input id="rev-rounds" className="f" type="number" min={1} max={10} step={1} value={cfg.max_rounds} aria-invalid={roundsOk ? undefined : true} onChange={(e) => setCfg({ ...cfg, max_rounds: e.target.value })} />
        </label>
        {!roundsOk ? <p className="err-text" role="alert">Rounds must be a whole number from 1 to 10.</p> : null}
        <div className="stack" style={{ gap: 8 }}>
          <h3 id="rev-default-h">Lenses ticked by default</h3>
          <div className="lens-row" role="group" aria-labelledby="rev-default-h">
            {names.map((n) => {
              const on = cfg.default_lenses.includes(n);
              return (
                <button key={n} type="button" className={`lens${on ? ' on' : ''}`} aria-pressed={on} onClick={() => setCfg({ ...cfg, default_lenses: on ? cfg.default_lenses.filter((x) => x !== n) : [...cfg.default_lenses, n] })}>
                  {lensName(n)}
                </button>
              );
            })}
          </div>
        </div>
        {names.map((n) => (
          <details key={n} className="lens-prompt">
            <summary>{lensName(n)} prompt {edited(n) ? <Chip tone="review">edited</Chip> : null}</summary>
            <textarea className="f" rows={6} aria-label={`${lensName(n)} prompt`} value={cfg.lenses[n]} onChange={(e) => setCfg({ ...cfg, lenses: { ...cfg.lenses, [n]: e.target.value } })} />
          </details>
        ))}
        <div className="row wrap">
          <Button variant="primary" type="submit" disabled={save.isPending || !roundsOk}>{save.isPending ? 'Saving…' : 'Save peer review'}</Button>
          {data.overridden ? <Button variant="ghost" onClick={() => void reset()} disabled={save.isPending}>Reset to defaults</Button> : null}
        </div>
      </form>
    </section>
  );
}
