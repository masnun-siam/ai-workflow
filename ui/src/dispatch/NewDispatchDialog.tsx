// New dispatch: pick an epic, set the dispatch up, preview its waves and warnings, then start it.
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePlanDispatch, usePlanning, useSettings, useStartDispatch } from '../api/hooks';
import type { DispatchPlan, DispatchSettings } from '../api/types';
import { Banner, Button, Chip, Dialog } from '../components';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';
import { SettingsFields } from './SettingsFields';
import { issueNo } from './vocab';

const DEFAULTS: DispatchSettings = { max: 2, grind: 'full', ci: 'wait', auto_merge: false, feature_branch: null, model: null, effort: null };
const EPIC_RE = /^(?:[\w.-]+\/[\w.-]+#)?\d+$/;

/** `epic` prefills the picker ("owner/repo#n"), e.g. from a feature's Run epic button. */
export function NewDispatchDialog({ open, onOpenChange, epic: initial }: { open: boolean; onOpenChange: (o: boolean) => void; epic?: string }) {
  const { repo } = useRepo();
  const epics = (usePlanning(repo).data?.prds ?? []).filter((p) => p.epic != null);
  const [epic, setEpic] = useState(initial ?? '');
  const [s, setS] = useState<DispatchSettings>(DEFAULTS);
  const saved = useSettings().data;
  const [touched, setTouched] = useState(false);
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const preview = usePlanDispatch();
  const start = useStartDispatch();
  const nav = useNavigate();
  // Seed the saved model/effort once settings load, unless the user already picked.
  useEffect(() => {
    if (!touched && saved) setS((x) => ({ ...x, model: saved.run_model ?? null, effort: (saved.run_effort ?? null) as DispatchSettings['effort'] }));
  }, [saved, touched]);
  useEffect(() => {
    if (open) {
      setEpic(initial ?? '');
      setPlan(null);
      preview.reset();
    }
  }, [open, initial]); // eslint-disable-line react-hooks/exhaustive-deps

  const full = epic.includes('#') || !repo ? epic.trim() : `${repo}#${epic.trim().replace(/^#/, '')}`;
  const valid = EPIC_RE.test(full);
  const change = (p: Partial<DispatchSettings>) => {
    setTouched(true);
    setS({ ...s, ...p });
    setPlan(null); // settings change the warnings: preview again
  };
  const doPreview = () => preview.mutate({ epic: full, settings: s }, { onSuccess: setPlan });
  const doStart = () => start.mutate({ epic: full, settings: s }, { onSuccess: (d) => { onOpenChange(false); nav(routes.dispatch(d.id)); } });
  const runnable = plan ? plan.waves.flat().length : 0;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title="Run an epic"
      description="Each issue is built, grinded, merged and wrapped up in its own session. The next one starts as soon as what it waits for is done."
      showDescription
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          {plan ? (
            <Button variant="primary" disabled={!runnable || start.isPending} onClick={doStart}>
              {start.isPending ? 'Starting…' : `Start ${runnable} issue${runnable === 1 ? '' : 's'}`}
            </Button>
          ) : (
            <Button variant="primary" disabled={!valid || preview.isPending} onClick={doPreview}>{preview.isPending ? 'Reading the epic…' : 'Preview'}</Button>
          )}
        </>
      }
    >
      <div className="stack" style={{ gap: 16 }}>
        <div className="lbl">
          <label htmlFor="nd-epic">Epic</label>
          <div className="row wrap" style={{ gap: 8 }}>
            <input id="nd-epic" className="f" style={{ maxWidth: 260 }} placeholder={repo ? `${repo}#123, or 123` : 'owner/repo#123'} value={epic}
              onChange={(e) => { setEpic(e.target.value); setPlan(null); }} onKeyDown={(e) => e.key === 'Enter' && valid && doPreview()} autoFocus />
            {epics.length ? (
              <select className="f" style={{ maxWidth: 320 }} aria-label="Pick an epic of this repo" value="" onChange={(e) => { if (e.target.value) { setEpic(`${repo}#${e.target.value}`); setPlan(null); } }}>
                <option value="">Pick an epic…</option>
                {epics.map((p) => <option key={p.slug} value={p.epic!}>#{p.epic} {p.title}</option>)}
              </select>
            ) : null}
          </div>
          {epic && !valid ? <span className="hint" style={{ color: 'var(--bad)' }}>Use owner/repo#123, or a number in {repo || 'the current repo'}.</span> : null}
        </div>
        <SettingsFields value={s} onChange={change} />
        <p className="faint" style={{ fontSize: 12.5 }}>Started here, the issues run in background sessions. To run them in herdr tabs instead, use the herdr-dispatch skill; both show up on this page.</p>
        {preview.isError ? <Banner tone="bad" icon="alert">{preview.error.message}</Banner> : null}
        {plan ? <PlanView plan={plan} /> : null}
      </div>
    </Dialog>
  );
}

function PlanView({ plan }: { plan: DispatchPlan }) {
  const title = new Map(plan.lanes.map((l) => [`${l.repo}#${l.n}`, l.title]));
  return (
    <section className="stack" style={{ gap: 10 }} aria-label="Preview">
      <h3 style={{ fontSize: 14 }}>{plan.title || plan.epic} · {plan.lanes.length} open issue{plan.lanes.length === 1 ? '' : 's'}</h3>
      {plan.warnings.length ? (
        <Banner tone="review" icon="alert">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Banner>
      ) : null}
      {plan.waves.length ? (
        <ol className="dsp-waves">
          {plan.waves.map((w, i) => (
            <li key={i}>
              <span className="faint" style={{ fontSize: 12 }}>{i === 0 ? 'Starts first' : 'Then'}</span>
              <div className="row wrap" style={{ gap: 6 }}>
                {w.map((k) => <Chip key={k} tone={i === 0 ? 'build' : 'muted'} title={title.get(k)}>{issueNo(k)} {title.get(k)}</Chip>)}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">Nothing to run: this epic has no refined open issues. Refine them first.</p>
      )}
    </section>
  );
}
