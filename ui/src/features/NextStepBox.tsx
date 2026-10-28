import { Button } from '../components';
import type { Feature } from '../lib/features';
import { nextStep, stepKey } from '../lib/nextStep';
import { useEpicDispatch } from '../dispatch/useOwner';
import { needsYou } from '../dispatch/vocab';
import { useStepRunner } from './useStepRunner';

/** The Next step box: one primary action, at most one secondary (FR-12). Solid orange when it waits on you. */
export function NextStepBox({ f, repo }: { f: Feature; repo: string }) {
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const { run, busy } = useStepRunner(f, repo);
  const you = live?.c.you ? live.d.lanes.filter(needsYou) : [];
  const why = you.map((l) => `#${l.n}: ${l.needs_you ?? l.held ?? 'waiting to merge'}`).join(' ');
  return (
    <section className={you.length ? 'alert-you' : 'next'} aria-label="Next step">
      <div style={{ flex: '1 1 420px', minWidth: 0 }}>
        {you.length ? null : <div className="k">Next step</div>}
        {you.length ? <h2>{ns.title}</h2> : <div className="t">{ns.title}</div>}
        {you.length ? <p>{why || ns.hint}</p> : <div className="h">{ns.hint}</div>}
      </div>
      <div className="row wrap">
        {ns.secondary ? <Button shortcut={stepKey(ns.secondary.action)} disabled={busy} onClick={() => run(ns.secondary!.action)}>{ns.secondary.label}</Button> : null}
        <Button variant={ns.quiet ? 'default' : 'primary'} shortcut={stepKey(ns.primary.action)} disabled={busy} onClick={() => run(ns.primary.action)}>{ns.primary.label}</Button>
      </div>
    </section>
  );
}
