import { Button } from '../components';
import type { Feature } from '../lib/features';
import { nextStep, stepKey } from '../lib/nextStep';
import { useEpicDispatch } from '../dispatch/useOwner';
import { useStepRunner } from './useStepRunner';

/** The Next step box: one primary action, at most one secondary (FR-12). */
export function NextStepBox({ f, repo }: { f: Feature; repo: string }) {
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const { run, busy } = useStepRunner(f, repo);
  return (
    <section className="next" aria-label="Next step">
      <div>
        <div className="k">Next step</div>
        <div className="t">{ns.title}</div>
        <div className="h">{ns.hint}</div>
      </div>
      <div className="row wrap">
        {ns.secondary ? <Button shortcut={stepKey(ns.secondary.action)} disabled={busy} onClick={() => run(ns.secondary!.action)}>{ns.secondary.label}</Button> : null}
        <Button variant={ns.quiet ? 'default' : 'primary'} shortcut={stepKey(ns.primary.action)} disabled={busy} onClick={() => run(ns.primary.action)}>{ns.primary.label}</Button>
      </div>
    </section>
  );
}
