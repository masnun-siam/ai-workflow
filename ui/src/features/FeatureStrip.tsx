import type { ComponentProps } from 'react';
import { Button, Icon, LinkButton, MoreMenu } from '../components';
import type { Feature } from '../lib/features';
import { repoLink } from '../lib/repo';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { NextStepButtons, useNextStep } from './NextStepBox';
import { IssueBar, StageTicks } from './StripParts';

type Props = { f: Feature; repo: string; onRunEpic: () => void; more: ComponentProps<typeof MoreMenu>['items'] };

/** The Feature page header: the list's strip with the page title, then the next step on one line. */
export function FeatureStrip({ f, repo, onRunEpic, more }: Props) {
  const { ns, live, you, why } = useNextStep(f, repo);
  const at = stageIdx(f.stage);
  return (
    <>
      <header className={`strip fstrip${you.length ? ' you' : ''}`}>
        <span className={`hold ${STAGES[at].tone}`} aria-hidden="true" />
        <div className="strip-c strip-t">
          <h1>{f.title}</h1>
          <div className="strip-m">
            <span>{f.epic ? `epic #${f.epic}` : 'no epic yet'}</span>
            <span className="mono">{f.prd.path}</span>
          </div>
        </div>
        <div className="strip-c fstrip-s"><StageTicks at={at} />{STAGES[at].label}</div>
        <div className="strip-c strip-p fstrip-p"><IssueBar issues={f.issues} you={new Set(you.map((l) => l.n))} /></div>
        <div className="strip-c fstrip-a">
          <section aria-label="Next step"><NextStepButtons f={f} repo={repo} ns={ns} /></section>
          {live ? (
            <LinkButton to={repoLink(repo, routes.dispatch(live.d.id))}>
              <Icon n="bolt" />{live.c.you ? `Dispatch needs you (${live.c.you})` : `Dispatch: ${live.c.closed} of ${live.c.total} done`}
            </LinkButton>
          ) : f.epic && f.issues.length && ns.primary.action.kind !== 'dispatch' ? (
            <Button variant="primary" onClick={onRunEpic} title="Build the epic's issues side by side">
              <Icon n="bolt" />Run epic
            </Button>
          ) : null}
          <MoreMenu label="More" sm={false} items={more} />
        </div>
      </header>
      <p className={`fnext${you.length ? ' you' : ''}`}><b>{ns.title}</b> <span>{why || ns.hint}</span></p>
    </>
  );
}
