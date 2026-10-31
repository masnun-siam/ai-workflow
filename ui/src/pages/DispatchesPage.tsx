// Every dispatch in one table, filtered by tab and repo in the browser; Run an epic opens the dialog.
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useDispatches } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, useListSelection } from '../components';
import { money, shortRepo } from '../lib/format';
import { withParam } from '../lib/repo';
import { routes } from '../lib/routes';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { DSTATE, counts, dispatchHeading, dispatchRepo, issueNo, needsYou, nowLine, secs } from '../dispatch/vocab';
import { RepoScope } from '../shell/RepoScope';
import { useRepo } from '../shell/useRepo';
import { useRepoFilter } from '../shell/useRepoFilter';
import '../features/features.css';
import '../dispatch/dispatch.css';

const live = (d: Dispatch) => d.state === 'running' || d.state === 'paused';
const stoppedOnYou = (d: Dispatch) => live(d) && counts(d).you > 0;

/** `id` is the `?show=` value, '' for All. */
const TABS: { id: string; label: string; holds: (d: Dispatch) => boolean; none: string }[] = [
  { id: '', label: 'All', holds: () => true, none: 'No dispatches in this repo.' },
  { id: 'needs', label: 'Needs you', holds: stoppedOnYou, none: 'Nothing needs you.' },
  { id: 'live', label: 'Live', holds: live, none: 'Nothing is live.' },
  { id: 'finished', label: 'Finished', holds: (d) => !live(d), none: 'Nothing has finished yet.' },
];

const rank = (d: Dispatch) => (stoppedOnYou(d) ? 0 : d.state === 'running' ? 1 : d.state === 'paused' ? 2 : 3);

function Row({ d, rowProps, onOpen }: { d: Dispatch; rowProps: ReturnType<ReturnType<typeof useListSelection>['rowProps']>; onOpen: () => void }) {
  const c = counts(d);
  const st = DSTATE[d.state];
  const repo = dispatchRepo(d);
  const you = stoppedOnYou(d) ? d.lanes.filter(needsYou) : [];
  const bar = [['merged', c.closed], ['build', c.active], ['ready', c.queued], ['refine', c.skipped]] as const;
  return (
    <tr {...rowProps} className="click" onClick={() => { rowProps.onClick(); onOpen(); }}>
      <td>{you.length ? <Chip tone="you">Needs you</Chip> : <Chip tone={st.tone} live={st.live}>{st.label}</Chip>}</td>
      <td className="title">
        <Link onClick={(e) => e.stopPropagation()} to={routes.dispatch(d.id)}>{dispatchHeading(d)}</Link>
        {repo ? (
          <div className="strip-m">
            <span>{shortRepo(repo)}</span>
            {live(d) ? null : <span>{new Date(d.created_at * 1000).toLocaleDateString()}</span>}
            {!live(d) && c.skipped ? <span>{c.skipped} skipped</span> : null}
          </div>
        ) : null}
        {you.length ? (
          <div className="dsp-row-ask">
            <span className="dsp-ref">{issueNo(you[0].key)}</span> {nowLine(you[0], d.lanes).text}{you.length > 1 ? ` and ${you.length - 1} more` : ''}
          </div>
        ) : null}
      </td>
      <td>
        <b>{c.closed}/{c.total}</b>
        <span className="ibar" role="img" aria-label={`${c.closed} of ${c.total} done`}>
          {bar.map(([s, n]) => (n ? <i key={s} className={`s-${s}`} style={{ flexGrow: n }} /> : null))}
        </span>
      </td>
      <td className="num">{secs(d.totals.seconds)}</td>
      <td className="num">{d.runner === 'herdr' ? '—' : money(d.totals.cost)}</td>
    </tr>
  );
}

export function DispatchesPage() {
  const q = useDispatches();
  const [sp, setSp] = useSearchParams();
  const asked = sp.get('new'); // ?new=owner/repo#n: a Run epic button sent us here
  const [open, setOpen] = useState(!!asked);
  const onOpenChange = (o: boolean) => {
    setOpen(o);
    if (!o && asked) {
      const n = new URLSearchParams(sp);
      n.delete('new');
      setSp(n, { replace: true });
    }
  };
  const nav = useNavigate();
  const { repo } = useRepo();
  const { only, setOnly } = useRepoFilter();
  const tab = TABS.find((t) => t.id === sp.get('show')) ?? TABS[0];
  const all = q.data?.dispatches ?? [];
  const inRepo = all.filter((d) => !only || dispatchRepo(d).toLowerCase() === only.toLowerCase());
  const rows = inRepo.filter(tab.holds).sort((a, b) => rank(a) - rank(b) || b.created_at - a.created_at);
  const { rowProps } = useListSelection({ keys: rows.map((d) => d.id), onOpen: (id) => nav(routes.dispatch(id)), reset: `${tab.id}|${only}` });
  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow"><h1>Dispatches</h1></div>
        <RepoScope repo={repo} only={only} setOnly={setOnly} label="Show dispatches from" />
        <Button variant="primary" onClick={() => setOpen(true)}><Icon n="plus" />Run an epic</Button>
      </div>
      {q.isError ? <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load dispatches. {q.error.message}</Banner> : null}
      {q.isPending ? <div className="skel" style={{ height: 90 }} /> : null}
      {q.data && !all.length ? (
        <EmptyState icon="bolt" title="Nothing is running" actions={<Button variant="primary" onClick={() => setOpen(true)}>Run an epic</Button>}>
          Pick an epic whose issues are refined. The ones with nothing to wait for start right away; the rest follow as their blockers merge.
        </EmptyState>
      ) : null}
      {all.length ? (
        <section className="stack" style={{ gap: 10 }} aria-label="All dispatches">
          <div className="scope dsp-tabs" role="group" aria-label="Show dispatches">
            {TABS.map((t) => (
              <button key={t.id} type="button" aria-pressed={t === tab} onClick={() => nav({ search: withParam(sp.toString(), 'show', t.id) })}>
                {t.label} <span className="n">{inRepo.filter(t.holds).length}</span>
              </button>
            ))}
          </div>
          {rows.length ? (
            <div className="tbl-wrap">
              <table className="tbl">
                <thead><tr><th>State</th><th>Dispatch</th><th>Issues</th><th className="num">Took</th><th className="num">Spent</th></tr></thead>
                <tbody>{rows.map((d) => <Row key={d.id} d={d} rowProps={rowProps(d.id)} onOpen={() => nav(routes.dispatch(d.id))} />)}</tbody>
              </table>
            </div>
          ) : <p className="muted">{tab.none}</p>}
        </section>
      ) : null}
      <NewDispatchDialog open={open} onOpenChange={onOpenChange} epic={asked ?? undefined} />
    </div>
  );
}
