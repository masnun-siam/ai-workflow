import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/endpoints';
import { usePeerReviewOffers } from '../api/hooks';
import { Button } from '../components';
import { PRIORITIES, priorityName, useCreateWork } from '../features/CaptureBar';
import '../features/features.css';
import { routes } from '../lib/routes';
import { lensName } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

type Pick = 'feature' | 'small' | null;
type Auto = { route: Pick; why: string } | 'asking' | null;

/** One capture, two routes: jev suggests Feature or Small change for the text, the user confirms or switches. */
export function NewPage() {
  const [sp] = useSearchParams();
  const { repo, current, link } = useRepo();
  const navigate = useNavigate();
  const work = useCreateWork(repo);
  const offers = usePeerReviewOffers();
  const [text, setText] = useState(sp.get('text') ?? '');
  const [pick, setPick] = useState<Pick>(sp.get('route') === 'small' ? 'small' : sp.get('route') === 'feature' ? 'feature' : null);
  const [auto, setAuto] = useState<Auto>(null);
  const [lenses, setLenses] = useState<string[]>([]);
  const [priority, setPriority] = useState('');

  const ask = async (t: string) => {
    if (!t.trim()) return;
    setAuto('asking');
    try {
      const r = await api.route(t);
      const route: Pick = r.route === 'feature' ? 'feature' : r.route === 'small_change' ? 'small' : null;
      setAuto({ route, why: r.why });
      if (route) setPick((p) => p ?? route);
    } catch {
      setAuto({ route: null, why: 'routing is unavailable' });
    }
  };
  // Route the text it was opened with once; after edits, routing again is the user's click.
  useEffect(() => { if (!pick) void ask(text); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const offer = offers.data?.kinds?.['create-prd'] ?? [];
  const toggle = (l: string) => setLenses((x) => (x.includes(l) ? x.filter((y) => y !== l) : [...x, l]));
  const start = async () => {
    if (pick === 'feature') await work.feature(text, lenses);
    else if (pick === 'small' && (await work.small(text, priority)) !== null) navigate(link(routes.changes));
  };
  const done = auto && auto !== 'asking' ? auto : null;
  const autoPick = done?.route ?? null;

  return (
    <div className="content-inner" style={{ maxWidth: 1080 }}>
      <h1 className="display">What should change?</h1>
      <div className="stack" style={{ gap: 10 }}>
        <label className="sr" htmlFor="new-text">Describe a feature or a fix</label>
        <textarea id="new-text" className="new-in" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Who it is for, what they cannot do today, and what done looks like." />
        <p className="muted" role="status" style={{ margin: 0, fontSize: 13 }}>
          {auto === 'asking' ? 'Working out the route…'
            : done && autoPick ? <>Auto picked <b>{autoPick === 'feature' ? 'Feature' : 'Small change'}</b>: {done.why}. Pick the other route if that is wrong.</>
            : done ? <>Auto could not tell ({done.why}). Pick a route.</>
            : 'Pick a route.'}
          {auto !== 'asking' && text.trim() ? <> <button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => void ask(text)}>Route again</button></> : null}
        </p>
      </div>

      <div className="routes" role="radiogroup" aria-label="Route">
        <div className="rcho" role="radio" tabIndex={0} aria-checked={pick === 'feature'} onClick={() => setPick('feature')} onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); setPick('feature'); } }}>
          <div className="rcho-h">Feature{autoPick === 'feature' ? <span className="pick">Auto's pick</span> : null}</div>
          <p>Claude interviews you into a PRD. It is reviewed and approved, then split into issues and built by a dispatch.</p>
          <div className="steps" aria-hidden="true">
            {['Interview', 'Review', 'Approve', 'Tasks', 'Build'].map((s) => <i key={s} />)}
            {['Interview', 'Review', 'Approve', 'Tasks', 'Build'].map((s) => <span key={s}>{s}</span>)}
          </div>
          {offer.length ? (
            <div className="stack" style={{ gap: 10 }} onClick={(e) => e.stopPropagation()}>
              <b style={{ fontSize: 13 }} id="new-lenses">Review the PRD with</b>
              <div className="lens-row" role="group" aria-labelledby="new-lenses">
                {offer.map((l) => <button key={l} type="button" className={`lens${lenses.includes(l) ? ' on' : ''}`} aria-pressed={lenses.includes(l)} onClick={() => { setPick('feature'); toggle(l); }}>{lensName(l)}</button>)}
              </div>
              <span className="muted" style={{ fontSize: 12 }}>Each picked lens must approve, up to {offers.data?.max_rounds ?? 5} rounds. None picked: you approve it yourself.</span>
            </div>
          ) : null}
        </div>
        <div className="rcho" role="radio" tabIndex={0} aria-checked={pick === 'small'} onClick={() => setPick('small')} onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); setPick('small'); } }}>
          <div className="rcho-h">Small change{autoPick === 'small' ? <span className="pick">Auto's pick</span> : null}</div>
          <p>Claude files one issue outside any epic and refines it with a what, why and how. Best for a bug or a change with no open decisions.</p>
          <div className="steps" aria-hidden="true">
            {['File issue', 'Refine', 'Run'].map((s) => <i key={s} />)}
            {['File issue', 'Refine', 'Run'].map((s) => <span key={s}>{s}</span>)}
          </div>
          <label className="row" style={{ gap: 10 }} onClick={(e) => e.stopPropagation()}>
            <b style={{ fontSize: 13 }}>Priority</b>
            <select className="f" style={{ width: 'auto' }} value={priority} onChange={(e) => { setPick('small'); setPriority(e.target.value); }}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{priorityName(p)}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="new-foot">
        <span className="muted grow">In {current?.name ?? repo}</span>
        <Button variant="ghost" noAction onClick={() => navigate(-1)}>Cancel</Button>
        <Button variant="accent" noAction disabled={!pick || !text.trim() || work.pending} onClick={() => void start()}>
          {pick === 'small' ? 'File the issue' : 'Start the PRD interview'}
        </Button>
      </div>
    </div>
  );
}
