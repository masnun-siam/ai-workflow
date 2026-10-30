import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Icon } from '../components';
import { useStarter } from '../board/actions';
import { routes } from '../lib/routes';
import { PLAN_RUN } from '../lib/vocab';
import { useRepos } from '../api/hooks';
import { repoLink } from '../lib/repo';
import { RepoSelect } from '../shell/RepoSelect';
import { smallChangeArg } from './smallChange';

export type Route = 'auto' | 'feature' | 'small';
export const PRIORITIES = ['', 'critical', 'high', 'medium', 'low'] as const;
export const priorityName = (p: string) => (p ? p[0].toUpperCase() + p.slice(1) : 'No priority');

/** The two starts behind the capture box and the New page. */
export function useCreateWork(repo: string) {
  const starter = useStarter();
  return {
    pending: starter.pending,
    /** /create-prd: Claude interviews you into a PRD. Opens the session. */
    feature: (text: string, lenses: string[] = []) =>
      starter.startSession({ repo, command: 'create-prd', args: text.trim(), ...(lenses.length ? { peer_review: lenses } : {}), ...PLAN_RUN }),
    /** One /create-tasks session that files and refines the issue; stays on this page. */
    small: (text: string, priority = '') =>
      starter.startBoard({ repo, skill: 'create-tasks', arg: smallChangeArg(priority ? `${text.trim()} Priority: ${priority}.` : text), via: 'headless', ...PLAN_RUN }, { nav: false }),
  };
}

const LABEL: Record<Route, string> = { auto: 'Auto', feature: 'Feature', small: 'Small change' };

/** One box for both kinds of work. Auto goes to the New page, where jev picks the route and you confirm it.
 *  `pickRepo` adds a repo picker that defaults to `repo` (All repos view); without it the bar files into `repo`. */
export function CaptureBar({ repo, initial = 'auto', pickRepo = false }: { repo: string; initial?: Route; pickRepo?: boolean }) {
  const [text, setText] = useState('');
  const [route, setRoute] = useState<Route>(initial);
  const [priority, setPriority] = useState('');
  const [picked, setPicked] = useState('');
  const target = picked || repo;
  const repos = useRepos().data?.repos ?? [];
  const work = useCreateWork(target);
  const navigate = useNavigate();
  const submit = async () => {
    const t = text.trim();
    if (!t) return;
    if (route === 'auto') return navigate(repoLink(target, routes.newWork(t)));
    if (route === 'feature') return void work.feature(t);
    if ((await work.small(t, priority)) !== null) setText('');
  };
  return (
    <form className="capture" aria-label="New feature or small change" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <Icon n="plus" s={18} />
      <input
        className="cap-in"
        aria-label="Describe a feature or a fix"
        placeholder={route === 'small' ? 'A bug or a small change, in one line. Claude files it as an issue and refines it.' : 'Describe a feature or a fix. Claude routes it to a PRD or an issue.'}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="route" role="radiogroup" aria-label="Route">
        {(Object.keys(LABEL) as Route[]).map((r) => (
          <button key={r} type="button" role="radio" aria-checked={route === r} onClick={() => setRoute(r)}>{LABEL[r]}</button>
        ))}
      </div>
      {route === 'small' ? (
        <select aria-label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
          {PRIORITIES.map((p) => <option key={p} value={p}>{priorityName(p)}</option>)}
        </select>
      ) : null}
      {pickRepo ? <RepoSelect repos={repos} value={target} onChange={setPicked} label="Capture repo" width={170} /> : null}
      <Button type="submit" variant="accent" noAction disabled={!text.trim() || !target || work.pending}>{route === 'small' ? 'File issue' : 'Create'}</Button>
    </form>
  );
}
