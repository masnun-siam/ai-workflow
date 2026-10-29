import type { UseQueryResult } from '@tanstack/react-query';
import type { OpenItem, PlanningPrd } from '../api/types';
import { Button, Chip } from '../components';
import { isoDay, matchItems, typedNumber, WORKLOG_MAX_DAYS, worklogDates, type WorklogPick } from './startLogic';

/** The label each command puts over its input. */
export const ARG_LABEL: Record<string, string> = {
  'implement-issue': 'Issue',
  'pr-grind': 'Pull request',
  'pr-review': 'Pull request',
  'create-prd': 'The idea',
  dump: 'What to capture',
  day: 'What to capture (optional)',
  'faq-updater': 'New questions or options (optional)',
  'repo-bootstrap': 'Phase and issue (optional)',
  'skill-feedback': 'The feedback',
  'peer-review': 'What to review (optional)',
  custom: 'Prompt',
  'refine-issues': 'Epic number or issue numbers',
  'create-tasks': 'PRD',
  'verifier-locally': 'What to verify (optional)',
  'docs-updater': 'Focus (optional)',
  'sync-from-wasensi': 'Focus (optional)',
  'release-pr': 'Options (optional)',
};
export const ARG_HINT: Record<string, string> = {
  'implement-issue': '5940, or an issue URL',
  'pr-grind': 'A PR URL, or the Slack link of the review thread',
  'pr-review': '5960, or a PR URL',
  'refine-issues': '#812, or #813 #814',
  'release-pr': '--dry-run, or what to hold back',
};

/** Free text: 8 rows, ⌘↵ / Ctrl+↵ submits. */
export function TextInput({ id, label, placeholder, value, onChange, onSubmit }: { id: string; label: string; placeholder?: string; value: string; onChange: (v: string) => void; onSubmit: () => void }) {
  return (
    <div className="lbl">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        className="f"
        rows={8}
        autoFocus
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onSubmit();
          }
        }}
      />
      <span className="hint">⌘↵ to start</span>
    </div>
  );
}

/** A single-line argument (issue numbers, options). */
export function LineInput({ id, label, hint, placeholder, value, onChange }: { id: string; label: string; hint?: string; placeholder?: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="lbl">
      <label htmlFor={id}>{label}</label>
      {hint ? <span className="hint">{hint}</span> : null}
      <input id={id} className="f" autoComplete="off" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/**
 * The repo's open issues or PRs: typing filters the list, a click fills the argument. When the list can't load
 * (or the repo is a path), a number or URL typed in the box still works.
 */
export function OpenPicker({ id, command, kind, value, onChange, q, slug, usable, placeholder }: {
  id: string;
  command: string;
  kind: 'issue' | 'pr';
  value: string;
  onChange: (v: string) => void;
  q: UseQueryResult<{ items: OpenItem[] }>;
  slug: string;
  usable: boolean;
  placeholder: string;
}) {
  const noun = kind === 'pr' ? 'PRs' : 'issues';
  const items = q.data?.items ?? [];
  const chosen = typedNumber(value);
  const shown = matchItems(items, value);
  const hit = items.find((it) => it.number === chosen);
  const fill = (it: OpenItem) => onChange(command === 'pr-grind' && it.url ? it.url : String(it.number));
  return (
    <div className="lbl">
      <label htmlFor={id}>{ARG_LABEL[command]}</label>
      <input id={id} className="f" autoComplete="off" autoFocus placeholder={usable ? `${placeholder}, or type to search the list` : placeholder} value={value} onChange={(e) => onChange(e.target.value)} />
      {usable ? (
        <div className="pick" style={{ fontWeight: 400 }}>
          <div className="row">
            <span className="muted grow">{q.isSuccess ? `Open ${noun} in ${slug} · ${items.length}` : `Open ${noun}`}</span>
            <Button variant="ghost" sm disabled={q.isFetching} onClick={() => void q.refetch()}>{q.isFetching ? 'Loading…' : 'Refresh'}</Button>
          </div>
          {hit ? <p role="status" className="muted"><b>#{hit.number}</b> {hit.title}</p> : null}
          {q.isError ? (
            <p className="muted">Could not list {noun}: {q.error.message.replace(/\.+$/, '')}. Type a number or URL instead.</p>
          ) : q.isSuccess && !items.length ? (
            <p className="muted">No open {noun} in {slug}. A number or URL still works.</p>
          ) : items.length && !shown.length ? (
            <p className="muted">No open {noun} match. A number or URL still works.</p>
          ) : items.length ? (
            <div className="pick-list" role="group" aria-label={`Open ${noun}`}>
              {shown.slice(0, 50).map((it) => (
                <button key={it.number} type="button" className={it.number === chosen ? 'on' : ''} aria-pressed={it.number === chosen} onClick={() => fill(it)}>
                  <span className="ref">#{it.number}</span>
                  <span className="grow">{it.title}</span>
                  {it.draft ? <Chip>draft</Chip> : null}
                  {it.labels.slice(0, 2).map((l) => <Chip key={l} tone="muted">{l}</Chip>)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <span className="hint">Type a number or an issue/PR URL.</span>
      )}
    </div>
  );
}

const SOMETHING_ELSE = '__other';
/** create-tasks: pick an approved PRD, or type a path or a finding. */
export function PrdInput({ id, prds, value, onChange }: { id: string; prds: PlanningPrd[]; value: string; onChange: (v: string) => void }) {
  const known = prds.some((p) => p.path === value);
  const other = prds.length === 0 || (value !== '' && !known) || value === SOMETHING_ELSE;
  return (
    <div className="lbl">
      <label htmlFor={id}>{ARG_LABEL['create-tasks']}</label>
      {prds.length ? (
        <select id={id} className="f" value={other ? SOMETHING_ELSE : value} onChange={(e) => onChange(e.target.value === SOMETHING_ELSE ? SOMETHING_ELSE : e.target.value)}>
          <option value="">Pick an approved PRD…</option>
          {prds.map((p) => <option key={p.path} value={p.path}>{p.title}</option>)}
          <option value={SOMETHING_ELSE}>Something else (a path, or a finding to file as one issue)…</option>
        </select>
      ) : (
        <span className="hint">No approved PRDs in this repo. Type a PRD path, or a finding to file as one issue.</span>
      )}
      {other ? (
        <input id={prds.length ? `${id}-other` : id} className="f" aria-label="PRD path or finding" autoComplete="off" placeholder="docs/prds/my-feature.md" value={value === SOMETHING_ELSE ? '' : value} onChange={(e) => onChange(e.target.value)} />
      ) : null}
    </div>
  );
}
export const prdArg = (v: string) => (v === SOMETHING_ELSE ? '' : v);

/** worklog: Today / Yesterday / A day / A range (one session per day, 3 at a time). */
export function WorklogInput({ value, onChange, error }: { value: WorklogPick; onChange: (v: WorklogPick) => void; error?: string }) {
  const today = isoDay(new Date());
  const wl = worklogDates(value, today);
  const n = 'dates' in wl ? wl.dates.length : 0;
  const set = (p: Partial<WorklogPick>) => onChange({ ...value, ...p });
  return (
    <fieldset className="wl">
      <legend>Which day</legend>
      <div className="seg" role="radiogroup" aria-label="Which day">
        {([['today', 'Today'], ['yesterday', 'Yesterday'], ['day', 'A day'], ['range', 'A range']] as const).map(([m, l]) => (
          <button key={m} type="button" role="radio" aria-checked={value.mode === m} className={value.mode === m ? 'on' : ''} onClick={() => set({ mode: m })}>{l}</button>
        ))}
      </div>
      {value.mode === 'day' ? (
        <label className="lbl" htmlFor="wl-day">Day<input id="wl-day" className="f" type="date" max={today} value={value.day} onChange={(e) => set({ day: e.target.value })} /></label>
      ) : null}
      {value.mode === 'range' ? (
        <div className="wl-range">
          <label className="lbl" htmlFor="wl-from">From<input id="wl-from" className="f" type="date" max={value.to || today} value={value.from} onChange={(e) => set({ from: e.target.value })} /></label>
          <label className="lbl" htmlFor="wl-to">To<input id="wl-to" className="f" type="date" min={value.from || undefined} max={today} value={value.to} onChange={(e) => set({ to: e.target.value })} /></label>
        </div>
      ) : null}
      {value.mode === 'range' && n ? (
        <p className="hint">{n === 1 ? 'One worklog run' : `${n} worklog runs, 3 at a time (the rest start as those finish)`}, one daily note each. At most {WORKLOG_MAX_DAYS} days.</p>
      ) : null}
      {error ? <p className="err-text" role="alert">{error}</p> : null}
    </fieldset>
  );
}
