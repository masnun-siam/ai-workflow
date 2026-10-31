import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/endpoints';
import type { DuplicateMatch } from '../api/types';
import { usePeerReviewOffers, useRepos, useSessions, useSettings } from '../api/hooks';
import { useStarter } from '../board/actions';
import { Button, Dialog, toast } from '../components';
import { smallChangeArg } from '../features/smallChange';
import '../features/features.css';
import { repoLink } from '../lib/repo';
import { routes } from '../lib/routes';
import { clockText } from '../lib/format';
import { lensName, PLAN_RUN } from '../lib/vocab';
import { RepoSelect } from '../shell/RepoSelect';
import { useRepo } from '../shell/useRepo';
import { useStart } from '../start/StartContext';
import { limitedUntil } from '../start/startLogic';
import '../start/start.css';

export type Route = 'feature' | 'small';
export const PRIORITIES = ['', 'critical', 'high', 'medium', 'low'] as const;
export const priorityName = (p: string) => (p ? p[0].toUpperCase() + p.slice(1) : 'No priority');

/** The account for this work and every step after it (run-engine/ui_origin.py). */
const pinned = (account?: string) => (account ? { claude_cmd: account, pin_account: true } : {});

/** The two starts behind the create box. */
function useCreateWork(repo: string) {
  const starter = useStarter();
  return {
    pending: starter.pending,
    /** /create-prd: Claude interviews you into a PRD. Opens the session. */
    feature: (text: string, lenses: string[], account?: string) =>
      starter.startSession({ repo, command: 'create-prd', args: text.trim(), ...(lenses.length ? { peer_review: lenses } : {}), ...pinned(account), ...PLAN_RUN }),
    /** One /create-tasks session that files and refines the issue; stays on this page. */
    small: (text: string, priority: string, account?: string) =>
      starter.startBoard({ repo, skill: 'create-tasks', arg: smallChangeArg(priority ? `${text.trim()} Priority: ${priority}.` : text), via: 'headless', ...pinned(account), ...PLAN_RUN }, { nav: false }),
  };
}

const LABEL: Record<Route, string> = { feature: 'Feature', small: 'Small change' };
const STEPS: Record<Route, string[]> = { feature: ['Interview', 'Review', 'Approve', 'Tasks', 'Build'], small: ['File issue', 'Refine', 'Run'] };
const short = (slug: string) => slug.split('/').pop() ?? slug;

type Preset = { repo?: string; route?: Route; text?: string };
type Auto = { route: Route | null; why: string } | 'asking' | null;

/** One box for both kinds of work: Auto suggests the route, the user confirms or switches. */
function CreateBody({ preset, draft, onClose }: { preset: Preset; draft: { current: string }; onClose: () => void }) {
  const { repo } = useRepo();
  const navigate = useNavigate();
  const startDialog = useStart();
  const repos = useRepos().data?.repos ?? [];
  const offers = usePeerReviewOffers();
  const [text, setText] = useState(preset.text ?? draft.current);
  const [pick, setPick] = useState<Route | null>(preset.route ?? null);
  const [picked, setPicked] = useState(preset.repo ?? '');
  const [auto, setAuto] = useState<Auto>(null);
  const [dup, setDup] = useState<DuplicateMatch | null>(null);
  const [lenses, setLenses] = useState<string[]>([]);
  const [priority, setPriority] = useState('');
  const [acctSel, setAcctSel] = useState<string | null>(null);
  const settings = useSettings().data;
  const limits = useSessions().data?.limits;
  const cmds = settings?.commands ?? [];
  const acct = acctSel ?? settings?.default ?? '';
  const account = cmds.length > 1 ? acct : undefined;
  const until = limitedUntil(cmds, acct, limits);
  const target = picked || repo;
  const work = useCreateWork(target);
  const t = text.trim();

  // Route 600 ms after typing stops; the cleanup drops a late answer for older text.
  useEffect(() => {
    setAuto(null);
    if (!t) return;
    setAuto('asking');
    let live = true;
    const timer = setTimeout(() => {
      api.route(t).then(
        (r) => { if (live) setAuto({ route: r.route === 'feature' ? 'feature' : r.route === 'small_change' ? 'small' : null, why: r.why }); },
        () => { if (live) setAuto({ route: null, why: 'routing is unavailable' }); },
      );
    }, 600);
    return () => { live = false; clearTimeout(timer); };
  }, [t]);

  // Check for a duplicate 800 ms after typing stops; the cleanup drops a late answer for older text or repo.
  useEffect(() => {
    setDup(null);
    if (!target || t.length < 20) return;
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      api.duplicate(target, t, ctl.signal).then((r) => { if (!ctl.signal.aborted) setDup(r.match ?? null); }, () => {});
    }, 800);
    return () => { clearTimeout(timer); ctl.abort(); };
  }, [target, t]);

  const done = auto && auto !== 'asking' ? auto : null;
  const route = pick ?? done?.route ?? null;
  const offer = offers.data?.kinds?.['create-prd'] ?? [];
  const change = (v: string) => { setText(v); draft.current = v; };
  const finish = () => { draft.current = ''; onClose(); };
  const start = async () => {
    if (!route || !t || !target || work.pending) return;
    if (route === 'feature') {
      if ((await work.feature(text, lenses, account)) !== null) finish();
    } else if ((await work.small(text, priority, account)) !== null) {
      finish();
      toast(`Filing the issue in ${short(target)}.`, { action: { label: 'Open Small changes', onClick: () => navigate(repoLink(target, routes.changes)) } });
    }
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void start(); }
  };
  const commands = () => { onClose(); startDialog.open({ repo: target, arg: t || undefined }); };

  return (
    <div className="cr">
      <label className="sr" htmlFor="new-text">Describe a feature or a fix</label>
      <textarea id="new-text" className="new-in" rows={4} autoFocus value={text} onChange={(e) => change(e.target.value)} onKeyDown={onKey} placeholder="Who it is for, what they cannot do today, and what done looks like." />
      <div className="cr-row">
        <div className="route" role="radiogroup" aria-label="Route">
          {(['feature', 'small'] as Route[]).map((r) => (
            <button key={r} type="button" role="radio" aria-checked={route === r} onClick={() => setPick(r)}>{LABEL[r]}</button>
          ))}
        </div>
        <RepoSelect repos={repos} value={target} onChange={setPicked} label="Repository" width={210} />
      </div>
      <p className="cr-say" role="status">
        {!t ? 'Describe it and Auto picks the route.'
          : auto === 'asking' ? 'Working out the route…'
          : !done ? null
          : !done.route ? `Auto could not tell (${done.why}). Pick a route.`
          : pick && pick !== done.route ? <>Your pick. Auto would file this as a {LABEL[done.route].toLowerCase()}. <button type="button" className="linkish" onClick={() => setPick(null)}>Use Auto's pick</button></>
          : `Auto picked ${LABEL[done.route]}: ${done.why}.`}
      </p>
      {dup ? <p className="cr-dup" role="status">Looks like <a href={dup.url} target="_blank" rel="noopener noreferrer">{dup.kind === 'issue' ? `#${dup.n} ${dup.title}` : dup.title}</a></p> : null}
      {cmds.length > 1 ? (
        <div className="cr-acct">
          <b id="new-run-on">Run on</b>
          <div className="seg" role="radiogroup" aria-labelledby="new-run-on">
            {cmds.map((a) => {
              const lim = limitedUntil(cmds, a.label, limits);
              return <button key={a.label} type="button" role="radio" aria-checked={acct === a.label} className={acct === a.label ? 'on' : ''} title={lim ? `Limited until ${clockText(lim)}` : undefined} onClick={() => setAcctSel(a.label)}>{a.label}{lim ? ' · limited' : ''}</button>;
            })}
          </div>
          <span className="muted">The next steps run on this account too.</span>
        </div>
      ) : null}
      {until ? <p className="hint" style={{ margin: 0, color: 'var(--review)' }}>This account is limited until {clockText(until)}. The session queues and starts at reset.</p> : null}
      {route ? (
        <div className="cr-plan">
          <div className="steps" style={{ gridTemplateColumns: `repeat(${STEPS[route].length},minmax(0,1fr))` }} aria-hidden="true">
            {STEPS[route].map((s) => <i key={s} />)}
            {STEPS[route].map((s) => <span key={s}>{s}</span>)}
          </div>
          {route === 'small' ? (
            <label className="row" style={{ gap: 10 }}>
              <b style={{ fontSize: 13 }}>Priority</b>
              <select className="f" style={{ width: 'auto' }} value={priority} onChange={(e) => setPriority(e.target.value)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{priorityName(p)}</option>)}
              </select>
            </label>
          ) : offer.length ? (
            <div className="stack" style={{ gap: 8 }}>
              <b style={{ fontSize: 13 }} id="new-lenses">Review the PRD with</b>
              <div className="lens-row" role="group" aria-labelledby="new-lenses">
                {offer.map((l) => <button key={l} type="button" className={`lens${lenses.includes(l) ? ' on' : ''}`} aria-pressed={lenses.includes(l)} onClick={() => setLenses((x) => (x.includes(l) ? x.filter((y) => y !== l) : [...x, l]))}>{lensName(l)}</button>)}
              </div>
              <span className="muted" style={{ fontSize: 12 }}>Each picked lens must approve, up to {offers.data?.max_rounds ?? 5} rounds. None picked: you approve it yourself.</span>
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="cr-foot">
        <button type="button" className="linkish grow" style={{ textAlign: 'left', textDecoration: 'underline' }} onClick={commands}>Run a command instead</button>
        <Button variant="ghost" noAction onClick={onClose}>Cancel</Button>
        <Button variant="accent" noAction aria-keyshortcuts="Meta+Enter Control+Enter" disabled={!route || !t || !target || work.pending} onClick={() => void start()}>
          {route === 'small' ? 'File the issue' : 'Start the PRD interview'}
        </Button>
      </div>
    </div>
  );
}

const Ctx = createContext<{ open: (p?: Preset) => void }>({ open: () => {} });

/** `const create = useCreate(); create.open({route: 'small'})`: the one way to start a feature or a small change. */
export const useCreate = () => useContext(Ctx);

export function CreateProvider({ children }: { children: ReactNode }) {
  const [preset, setPreset] = useState<Preset | null>(null);
  const draft = useRef(''); // text kept across Cancel and Esc until something is created
  const open = useCallback((p: Preset = {}) => setPreset(p), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <Dialog open={!!preset} onOpenChange={(o) => !o && setPreset(null)} title="What should change?" description="Describe a feature or a fix. Auto picks the route." bare>
        {preset ? <CreateBody preset={preset} draft={draft} onClose={() => setPreset(null)} /> : null}
      </Dialog>
    </Ctx.Provider>
  );
}

/** A quiet way into the box on the pages that create work. */
export function CreatePrompt({ repo, route, className = '' }: { repo?: string; route?: Route; className?: string }) {
  const create = useCreate();
  return (
    <button type="button" className={`cr-prompt ${className}`} onClick={() => create.open({ repo, route })}>
      <span className="grow">{route === 'small' ? 'Describe a bug or a small change' : 'Describe a feature or a fix'}</span>
      <span className="kbd hide-sm">N</span>
    </button>
  );
}
