import { Button } from '../components';
import type { Feature } from '../lib/features';
import { nextStep, stepKey, type Step } from '../lib/nextStep';
import { useEpicDispatch } from '../dispatch/useOwner';
import { needsYou } from '../dispatch/vocab';
import { useStepRunner } from './useStepRunner';

/** A feature's next step; `you` are the lanes its dispatch stopped on and `why` names each of them. */
export function useNextStep(f: Feature, repo: string) {
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const you = live?.c.you ? live.d.lanes.filter(needsYou) : [];
  const why = you.map((l) => `#${l.n}: ${l.needs_you ?? l.held ?? 'waiting to merge'}`).join(' ');
  return { ns, live, you, why };
}

/** One primary action, at most one secondary (FR-12). */
export function NextStepButtons({ f, repo, ns }: { f: Feature; repo: string; ns: Step }) {
  const { run, busy, labelOf } = useStepRunner(f, repo);
  return (
    <div className="row wrap">
      {ns.secondary ? <Button variant="ghost" shortcut={stepKey(ns.secondary.action)} disabled={busy} onClick={() => run(ns.secondary!.action)}>{labelOf(ns.secondary.action, ns.secondary.label)}</Button> : null}
      <Button variant={ns.quiet ? 'default' : 'primary'} shortcut={stepKey(ns.primary.action)} disabled={busy} onClick={() => run(ns.primary.action)}>{labelOf(ns.primary.action, ns.primary.label)}</Button>
    </div>
  );
}

/** The Next step box in the detail panel. Solid orange when it waits on you. */
export function NextStepBox({ f, repo }: { f: Feature; repo: string }) {
  const { ns, you, why } = useNextStep(f, repo);
  return (
    <section className={you.length ? 'alert-you' : 'next'} aria-label="Next step">
      <div style={{ flex: '1 1 420px', minWidth: 0 }}>
        {you.length ? null : <div className="k">Next step</div>}
        {you.length ? <h2>{ns.title}</h2> : <div className="t">{ns.title}</div>}
        {you.length ? <p>{why || ns.hint}</p> : <div className="h">{ns.hint}</div>}
      </div>
      <NextStepButtons f={f} repo={repo} ns={ns} />
    </section>
  );
}
