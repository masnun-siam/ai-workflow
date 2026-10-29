// Every dispatch: the live ones as cards, the rest as history; New dispatch opens the dialog.
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useDispatches } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, useListSelection } from '../components';
import { clockText, money } from '../lib/format';
import { routes } from '../lib/routes';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { ACTIVE, DSTATE, counts, dispatchHeading, dispatchRepo, issueNo, nowLine, secs } from '../dispatch/vocab';
import { columns } from '../dispatch/LaneViews';
import '../dispatch/dispatch.css';

const live = (d: Dispatch) => d.state === 'running' || d.state === 'paused';

function Card({ d, rowProps }: { d: Dispatch; rowProps: ReturnType<ReturnType<typeof useListSelection>['rowProps']> }) {
  const c = counts(d);
  const st = DSTATE[d.state];
  const asks = d.lanes.map((l) => ({ l, now: nowLine(l, d.lanes) })).filter((x) => x.now.ask);
  return (
    <Link {...rowProps} to={routes.dispatch(d.id)} className={`live-card dsp-card${asks.length ? ' you' : ''}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div className="row"><Chip tone={st.tone} live={st.live}>{st.label}</Chip><span className="grow" /><span className="faint" style={{ fontSize: 12 }}>{secs(d.totals.seconds)}</span></div>
      <b>{dispatchHeading(d)}</b>
      <ol className="dsp-train" role="img" aria-label={`${c.closed} of ${c.total} done`}>
        {columns(d.lanes).map((w, k) => {
          const cls = w.every((l) => l.stage === 'closed') ? 'done' : w.some((l) => ACTIVE.includes(l.stage)) ? 'now' : '';
          return <li key={k} className={cls}><i /><span>Wave {k + 1}</span></li>;
        })}
      </ol>
      <span className="muted" style={{ fontSize: 13 }}>
        {c.closed} of {c.total} done{c.active ? `, ${c.active} in progress` : ''}{c.queued ? `, ${c.queued} waiting` : ''}
      </span>
      {asks.length ? (
        <ul className="dsp-card-asks">
          {asks.slice(0, 3).map(({ l, now }) => <li key={l.key}><span className="dsp-ref">{issueNo(l.key)}</span> {now.text}</li>)}
          {asks.length > 3 ? <li className="faint">and {asks.length - 3} more</li> : null}
        </ul>
      ) : null}
    </Link>
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
  const all = q.data?.dispatches ?? [];
  const running = all.filter(live);
  const past = all.filter((d) => !live(d));
  const nav = useNavigate();
  const { rowProps } = useListSelection({ keys: [...running, ...past].map((d) => d.id), onOpen: (id) => nav(routes.dispatch(id)) });
  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Dispatches</h1>
          <p className="sub">Run an epic’s issues side by side. Each one is built, grinded, merged and wrapped up, and the next starts as soon as what it waits for is done.</p>
        </div>
        <Button variant="primary" onClick={() => setOpen(true)}><Icon n="plus" />Run an epic</Button>
      </div>
      {q.isError ? <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load dispatches. {q.error.message}</Banner> : null}
      <section aria-label="Running">
        <div className="group-h"><h2>Running</h2><span className="n">{running.length}</span></div>
        {running.length ? (
          <div className="dsp-trains">{running.map((d) => <Card key={d.id} d={d} rowProps={rowProps(d.id)} />)}</div>
        ) : q.isPending ? <div className="skel" style={{ height: 90 }} /> : (
          <EmptyState icon="bolt" title="Nothing is running" actions={<Button variant="primary" onClick={() => setOpen(true)}>Run an epic</Button>}>
            Pick an epic whose issues are refined. The ones with nothing to wait for start right away; the rest follow as their blockers merge.
          </EmptyState>
        )}
      </section>
      {past.length ? (
        <section className="stack" style={{ gap: 10 }} aria-label="History">
          <h2>History</h2>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Epic</th><th>Result</th><th>Issues</th><th>Started</th><th className="num">Took</th><th className="num">Spent</th></tr></thead>
              <tbody>
                {past.map((d) => {
                  const c = counts(d);
                  const rp = rowProps(d.id);
                  return (
                    <tr key={d.id} {...rp} className="click" onClick={() => { rp.onClick(); nav(routes.dispatch(d.id)); }}>
                      <td className="title"><Link onClick={(e) => e.stopPropagation()} to={routes.dispatch(d.id)}>{d.title || d.epic}</Link><div className="faint mono" style={{ fontSize: 12 }}>{d.epic ?? dispatchRepo(d)}</div></td>
                      <td><Chip tone={DSTATE[d.state].tone}>{DSTATE[d.state].label}</Chip></td>
                      <td>{c.closed}/{c.total} done{c.skipped ? `, ${c.skipped} skipped` : ''}</td>
                      <td>{new Date(d.created_at * 1000).toLocaleDateString()} {clockText(d.created_at)}</td>
                      <td className="num">{secs(d.totals.seconds)}</td>
                      <td className="num">{d.runner === 'herdr' ? '—' : money(d.totals.cost)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      <NewDispatchDialog open={open} onOpenChange={onOpenChange} epic={asked ?? undefined} />
    </div>
  );
}
