import { Fragment, useState } from 'react';
import { useAutoBuild } from '../api/hooks';
import { IssueAction } from '../board/IssueAction';
import { IssueSignals } from '../board/IssueSignals';
import { useStarter } from '../board/actions';
import { Button, IssueChip, Switch } from '../components';
import type { Feature } from '../lib/features';
import { ATTENTION_ORDER, ISSUE } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { taskArg } from './useStepRunner';

export function IssuesTab({ f, repo, autoGrind }: { f: Feature; repo: string; autoGrind: boolean }) {
  const panel = usePanel();
  const starter = useStarter();
  const auto = useAutoBuild();
  const [text, setText] = useState('');
  const [picked, setPicked] = useState<number[]>([]);
  const groups = ATTENTION_ORDER.map((s) => [s, f.issues.filter((i) => i.status === s)] as const).filter(([, l]) => l.length);
  const unrefined = f.issues.filter((i) => i.column === 'unrefined').map((i) => i.n);
  const toggle = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));

  return (
    <div className="stack">
      {f.epic ? (
        <div className="row wrap" style={{ gap: 14 }}>
          <label className="row" style={{ gap: 10, fontWeight: 600 }}>
            <Switch checked={f.autobuild} label="Auto-build" disabled={auto.isPending} onChange={(on) => auto.mutate({ repo, epic: f.epic!, on })} />
            Auto-build
          </label>
          <span className="muted" style={{ fontSize: 13 }}>Starts ready, unblocked issues by priority, {f.cap} at a time. Never merges.</span>
          <span className="grow" />
          <form
            className="row"
            style={{ gap: 6 }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (!text.trim()) return;
              const id = await starter.startBoard({ repo, skill: 'create-tasks', arg: taskArg(f.epic!, f.prd.path, text), via: 'headless' });
              if (id !== null) setText('');
            }}
          >
            <input id="add-task" className="f" style={{ width: 260 }} aria-label="Add a task to this epic" placeholder="Add a task to this epic" value={text} onChange={(e) => setText(e.target.value)} />
            <Button type="submit" disabled={!text.trim() || starter.pending}>Add</Button>
          </form>
        </div>
      ) : null}
      {picked.length > 0 ? (
        <div className="row">
          <Button variant="primary" sm disabled={starter.pending} onClick={async () => { const id = await starter.startBoard({ repo, skill: 'refine-issues', arg: picked.join(' '), via: 'headless' }); if (id !== null) setPicked([]); }}>
            Refine {picked.length} picked
          </Button>
          <Button variant="ghost" sm onClick={() => setPicked([])}>Clear</Button>
        </div>
      ) : null}
      {!f.issues.length ? (
        <div className="empty"><p>No issues yet. {f.stage === 'approved' ? 'Create tasks to split the PRD into issues.' : 'Issues appear after the PRD is approved and split into tasks.'}</p></div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 28 }}><span className="sr">Pick to refine</span></th>
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
                  <tr className="sub"><td colSpan={6}>{ISSUE[s].label} · {l.length}</td></tr>
                  {l.map((i) => (
                    <tr key={i.n} className="click" onClick={() => panel.open({ kind: 'issue', repo, n: i.n })}>
                      <td onClick={(e) => e.stopPropagation()}>
                        {unrefined.includes(i.n) ? <input type="checkbox" className="issue-pick" aria-label={`Pick #${i.n} to refine`} checked={picked.includes(i.n)} onChange={() => toggle(i.n)} /> : null}
                      </td>
                      <td className="ref">#{i.n}</td>
                      <td className="title">
                        <button type="button" className="linkish" style={{ fontWeight: 600 }} onClick={(e) => { e.stopPropagation(); panel.open({ kind: 'issue', repo, n: i.n }); }}>{i.title}</button>
                      </td>
                      <td><IssueChip s={i.status} /></td>
                      <td className="hide-sm"><IssueSignals card={i} /></td>
                      <td style={{ textAlign: 'right' }}><IssueAction card={i} repo={repo} autoGrind={autoGrind} /></td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
