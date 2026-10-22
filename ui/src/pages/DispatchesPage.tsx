// Every dispatch: the live ones as cards, the rest as history; New dispatch opens the dialog.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useDispatches } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon } from '../components';
import { clockText, money } from '../lib/format';
import { routes } from '../lib/routes';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { DSTATE, counts, epicNo, secs } from '../dispatch/vocab';
import '../dispatch/dispatch.css';

const live = (d: Dispatch) => d.state === 'running' || d.state === 'paused';

function Card({ d }: { d: Dispatch }) {
  const c = counts(d);
  const st = DSTATE[d.state];
  const s = d.settings;
  return (
    <Link to={routes.dispatch(d.id)} className={`live-card${c.you ? ' you' : ''}`} style={{ textDecoration: 'none', color: 'inherit' }}>
      <div className="row"><Chip tone={st.tone} live={st.live}>{st.label}</Chip>{c.you ? <Chip tone="you">{c.you} need you</Chip> : null}<span className="grow" /><span className="faint" style={{ fontSize: 12 }}>{secs(d.totals.seconds)}</span></div>
      <b className="ellipsis">{d.title || `Epic #${epicNo(d.epic)}`}</b>
      <span className="faint mono" style={{ fontSize: 12 }}>{d.epic}</span>
      <div className="meter" role="img" aria-label={`${c.closed} of ${c.total} lanes done`}><span style={{ width: `${c.total ? (c.closed / c.total) * 100 : 0}%`, background: 'var(--ship)' }} /></div>
      <span className="muted" style={{ fontSize: 12.5 }}>
        {c.closed}/{c.total} done · {c.active} running · grind {s.grind} · {s.auto_merge ? 'auto-merge' : 'you merge'} · {d.runner === 'herdr' ? 'herdr' : 'headless'}
      </span>
    </Link>
  );
}

export function DispatchesPage() {
  const q = useDispatches();
  const [open, setOpen] = useState(false);
  const all = q.data?.dispatches ?? [];
  const running = all.filter(live);
  const past = all.filter((d) => !live(d));
  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Dispatches</h1>
          <p className="sub">An epic’s issues as parallel lanes: implement, grind, merge, followups, next. Started here or by the herdr-dispatch skill.</p>
        </div>
        <Button variant="primary" onClick={() => setOpen(true)}><Icon n="plus" />New dispatch</Button>
      </div>
      {q.isError ? <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load dispatches. {q.error.message}</Banner> : null}
      <section aria-label="Running">
        <div className="group-h"><h2>Running</h2><span className="n">{running.length}</span></div>
        {running.length ? (
          <div className="live-grid">{running.map((d) => <Card key={d.id} d={d} />)}</div>
        ) : q.isPending ? <div className="skel" style={{ height: 90 }} /> : (
          <EmptyState icon="bolt" title="No dispatch running" actions={<Button variant="primary" onClick={() => setOpen(true)}>Dispatch an epic</Button>}>
            Pick an epic with refined issues. Its unblocked issues start in parallel and the rest follow as their blockers merge.
          </EmptyState>
        )}
      </section>
      {past.length ? (
        <section className="stack" style={{ gap: 10 }} aria-label="History">
          <h2>History</h2>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Epic</th><th>Result</th><th>Lanes</th><th>Started</th><th>Took</th><th>Cost</th></tr></thead>
              <tbody>
                {past.map((d) => {
                  const c = counts(d);
                  return (
                    <tr key={d.id}>
                      <td className="title"><Link to={routes.dispatch(d.id)}>{d.title || d.epic}</Link><div className="faint mono" style={{ fontSize: 12 }}>{d.epic}</div></td>
                      <td><Chip tone={DSTATE[d.state].tone}>{DSTATE[d.state].label}</Chip></td>
                      <td>{c.closed}/{c.total} done{c.skipped ? `, ${c.skipped} skipped` : ''}</td>
                      <td>{new Date(d.created_at * 1000).toLocaleDateString()} {clockText(d.created_at)}</td>
                      <td className="mono">{secs(d.totals.seconds)}</td>
                      <td className="mono">{d.runner === 'herdr' ? '—' : money(d.totals.cost)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      <NewDispatchDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
