import { Fragment, useState } from 'react';
import { IssueAction } from '../board/IssueAction';
import { IssueSignals } from '../board/IssueSignals';
import { useRefining, useStarter } from '../board/actions';
import { Button, Chip, Icon, IssueChip, LinkButton, useListSelection } from '../components';
import { useOwnedIssues } from '../dispatch/useOwner';
import { STAGE, nowLine } from '../dispatch/vocab';
import '../dispatch/dispatch.css';
import type { Feature, FeatureIssue } from '../lib/features';
import { routes } from '../lib/routes';
import { ATTENTION_ORDER, ISSUE, PLAN_RUN } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { KeyScope } from '../shell/shortcuts';
import { taskArg } from './useStepRunner';

export function IssuesTab({ f, repo }: { f: Feature; repo: string }) {
  const starter = useStarter();
  const refining = useRefining(repo);
  const [text, setText] = useState('');
  const [picked, setPicked] = useState<number[]>([]);
  const toggle = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  const panel = usePanel();
  const selection = useListSelection({ keys: orderedIssues(f.issues).map((i) => String(i.n)), onOpen: (k) => panel.open({ kind: 'issue', repo, n: Number(k) }), panelTarget: (k) => ({ kind: 'issue', repo, n: Number(k) }), reset: repo });

  return (
    <div className="stack">
      {f.epic ? (
        <div className="row wrap" style={{ gap: 14 }}>
          <LinkButton sm to={routes.newDispatch(`${repo}#${f.epic}`) + `&repo=${repo}`}><Icon n="bolt" />Run epic</LinkButton>
          <span className="muted" style={{ fontSize: 13 }}>Builds the ready issues side by side, then grinds, merges and wraps up each one.</span>
          <span className="grow" />
          <form
            className="row"
            style={{ gap: 6 }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (!text.trim()) return;
              const id = await starter.startBoard({ repo, skill: 'create-tasks', arg: taskArg(f.epic!, f.prd.path, text), via: 'headless', ...PLAN_RUN });
              if (id !== null) setText('');
            }}
          >
            <input id="add-task" className="f" style={{ width: 260 }} aria-label="Add a task to this epic" placeholder="Add a task to this epic" value={text} onChange={(e) => setText(e.target.value)} />
            <Button type="submit" disabled={!text.trim() || starter.pending}>Add</Button>
          </form>
        </div>
      ) : null}
      {picked.length > 0 && picked.every((n) => !refining.has(n)) ? (
        <div className="row">
          <Button variant="primary" sm shortcut="e" disabled={starter.pending} onClick={async () => { const id = await starter.startBoard({ repo, skill: 'refine-issues', arg: picked.join(' '), via: 'headless', ...PLAN_RUN }); if (id !== null) setPicked([]); }}>
            Refine {picked.length} picked
          </Button>
          <Button variant="ghost" sm onClick={() => setPicked([])}>Clear</Button>
        </div>
      ) : null}
      {!f.issues.length ? (
        <div className="empty"><p>No issues yet. {f.stage === 'approved' ? 'Create tasks to split the PRD into issues.' : 'Issues appear after the PRD is approved and split into tasks.'}</p></div>
      ) : (
        <IssueTable issues={f.issues} repo={repo} picked={picked} onPick={toggle} selection={selection} />
      )}
    </div>
  );
}

/** The issues in the order `IssueTable` renders them, so keyboard selection follows the screen. */
export const orderedIssues = (issues: FeatureIssue[]) => ATTENTION_ORDER.flatMap((s) => issues.filter((i) => i.status === s));

export type IssueSelection = Pick<ReturnType<typeof useListSelection>, 'rowProps'> & { selected: string | null };

/**
 * Issues grouped by status, one row each with its signals and one action. An issue a running dispatch owns
 * shows its dispatch stage and links there instead of offering a Start. Shared by a feature and the Small changes tab.
 */
export function IssueTable({ issues, repo, picked = [], onPick, canPick = (i) => i.column === 'unrefined', lockRefine, selection }: { issues: FeatureIssue[]; repo: string; picked?: number[]; onPick?: (n: number) => void; canPick?: (i: FeatureIssue) => boolean; lockRefine?: string; selection?: IssueSelection }) {
  const panel = usePanel();
  const owned = useOwnedIssues(repo);
  const refining = useRefining(repo);
  const groups = ATTENTION_ORDER.map((s) => [s, issues.filter((i) => i.status === s)] as const).filter(([, l]) => l.length);
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 28 }}><span className="sr">Pick issues</span></th>
            <th style={{ width: 70 }}>Issue</th>
            <th>Title</th>
            <th>Status</th>
            <th className="hide-sm">Signals</th>
            <th style={{ textAlign: 'right' }}>Action</th>
          </tr>
        </thead>
        <tbody>
          {groups.map(([s, l]) => (
            <Fragment key={s}>
              <tr className="sub"><td colSpan={6}>{ISSUE[s].label}, {l.length}</td></tr>
              {l.map((i) => {
                const own = owned.get(i.n);
                return (
                  <tr key={i.n} className="click" {...selection?.rowProps(String(i.n))} onClick={() => { selection?.rowProps(String(i.n)).onClick(); panel.open({ kind: 'issue', repo, n: i.n }); }}>
                    <td onClick={(e) => e.stopPropagation()}>
                      {onPick && canPick(i) && !refining.has(i.n) && !own ? <input type="checkbox" className="issue-pick" aria-label={`Pick #${i.n}`} checked={picked.includes(i.n)} onChange={() => onPick(i.n)} /> : null}
                    </td>
                    <td className="ref">#{i.n}</td>
                    <td className="title">
                      <button type="button" className="linkish" style={{ fontWeight: 600 }} onClick={(e) => { e.stopPropagation(); panel.open({ kind: 'issue', repo, n: i.n }); }}>{i.title}</button>
                      {own ? <div className={`dsp-c t-${nowLine(own.l, own.d.lanes).tone}`} style={{ fontSize: 12.5 }}>{nowLine(own.l, own.d.lanes).text}</div> : null}
                    </td>
                    <td>{own ? <Chip tone={STAGE[own.l.stage].tone} live={own.l.stage !== 'queued'}>{STAGE[own.l.stage].label}</Chip> : <IssueChip s={i.status} />}</td>
                    <td className="hide-sm"><IssueSignals card={i} /></td>
                    <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <KeyScope level="row" active={selection?.selected === String(i.n)} name={`#${i.n} ${i.title}`}>
                        {own ? <LinkButton sm to={`${routes.dispatch(own.d.id)}?lane=${encodeURIComponent(own.l.key)}`}>In dispatch</LinkButton> : <IssueAction card={i} repo={repo} refineLock={lockRefine} />}
                      </KeyScope>
                    </td>
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
