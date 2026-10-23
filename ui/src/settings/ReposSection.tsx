import { useState } from 'react';
import { api } from '../api/endpoints';
import { useApiMutation, useRemoveRepo, useRepos, useSaveSettings, useScanRepos, useSettings } from '../api/hooks';
import type { Repo, RepoSettings, ScanResult } from '../api/types';
import { Button, Chip, Icon, Switch, toast, useConfirm } from '../components';
import { PublishDialog } from '../repos/PublishDialog';
import './settings.css';

export const REPO_FILTER_AFTER = 8;
const DEFAULTS: RepoSettings = { auto_grind: false, slack_channel: '' };

/** Slack channel: edited locally, saved when the field loses focus with a changed value. */
function SlackCell({ slug, value, onSave }: { slug: string; value: string; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  if (value !== seen) { // the saved value changed (a save, or a revert): follow it
    setSeen(value);
    setDraft(value);
  }
  return (
    <input
      className="f slack"
      aria-label={`Slack channel for ${slug}`}
      placeholder="#channel"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft.trim() !== value && onSave(draft.trim())}
      onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
    />
  );
}

/** Repositories: one table (autosaved per row), Remove, scan folders, Find repos, Check remotes. */
export function ReposSection() {
  const repos = useRepos();
  const settings = useSettings();
  const save = useSaveSettings();
  const remove = useRemoveRepo();
  const scan = useScanRepos();
  const check = useApiMutation(api.checkRepos, [], { quiet: true });
  const confirm = useConfirm();
  const [over, setOver] = useState<Record<string, RepoSettings>>({}); // optimistic values while a save is in flight
  const [q, setQ] = useState('');
  const [roots, setRoots] = useState<string | null>(null);
  const [msg, setMsg] = useState('');
  const [problems, setProblems] = useState<Record<string, string | null> | null>(null);
  const [publishing, setPublishing] = useState<string | null>(null);

  const list = repos.data?.repos ?? [];
  const rowOf = (slug: string): RepoSettings => ({ ...DEFAULTS, ...settings.data?.repos?.[slug], ...over[slug] });
  const scanRoots = roots ?? (repos.data?.scan_roots ?? []).join('\n');
  const [modeOver, setModeOver] = useState<'deep' | 'simple' | null>(null);
  const mode = modeOver ?? settings.data?.grind_mode ?? 'deep';
  const changeMode = async (m: 'deep' | 'simple') => {
    setModeOver(m);
    try {
      await save.mutateAsync({ grind_mode: m });
      toast(m === 'simple' ? 'Grinding is simple: loops stop once the PR is approved' : 'Grinding is deep');
    } catch {
      /* the error toast comes from the mutation cache */
    } finally {
      setModeOver(null);
    }
  };

  // Each row saves on its own and sends only that repo's entry; a rejected save puts the old value back.
  const change = async (slug: string, patch: Partial<RepoSettings>) => {
    const next = { ...rowOf(slug), ...patch };
    setOver((o) => ({ ...o, [slug]: next }));
    try {
      await save.mutateAsync({ repos: { [slug]: next } });
      toast(`Saved ${slug}`);
    } catch {
      /* the error toast comes from the mutation cache */
    } finally {
      setOver(({ [slug]: _gone, ...rest }) => rest);
    }
  };

  const onRemove = async (r: Repo) => {
    const ok = await confirm({
      title: `Remove ${r.slug}?`,
      body: <p>It is unregistered from aiw. Its clone on disk is not touched, and Find repos adds it back.</p>,
      okLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    await remove.mutateAsync(r.slug);
    toast(`Removed ${r.slug}`);
  };

  const find = async () => {
    setMsg('');
    try {
      const folders = scanRoots.split('\n').map((s) => s.trim()).filter(Boolean);
      const r = (await scan.mutateAsync(folders)) as unknown as ScanResult;
      const n = r.added.length;
      const dup = r.duplicates.length;
      setMsg(n ? `Registered ${n} new repo${n === 1 ? '' : 's'}${dup ? `; ${dup} extra clone${dup === 1 ? '' : 's'} of a known repo skipped` : ''}.` : 'No new repos found.');
    } catch {
      /* toasted */
    }
  };
  const checkRemotes = async () => {
    setMsg('');
    try {
      const { problems: p } = await check.mutateAsync();
      setProblems(p);
      const bad = Object.values(p).filter(Boolean).length;
      setMsg(bad ? `${bad} repo${bad === 1 ? '' : 's'} with a problem, listed first.` : 'Every remote is reachable.');
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  const needle = q.trim().toLowerCase();
  const shown = (needle ? list.filter((r) => `${r.slug} ${r.name} ${r.path}`.toLowerCase().includes(needle)) : list).slice().sort((a, b) => Number(!!problems?.[b.slug]) - Number(!!problems?.[a.slug]));

  return (
    <section className="set-sec" aria-labelledby="set-repos-h">
      <div className="row wrap">
        <div className="grow">
          <h2 id="set-repos-h">Repositories</h2>
          <p className="muted">Each repo's automation. Changes save as you make them.</p>
        </div>
        <Button onClick={find} disabled={scan.isPending}><Icon n="search" />{scan.isPending ? 'Scanning…' : 'Find repos'}</Button>
        <Button onClick={checkRemotes} disabled={check.isPending || !list.length}>{check.isPending ? 'Checking…' : 'Check remotes'}</Button>
      </div>
      {msg ? <p className="set-note" role="status">{msg}</p> : null}
      <fieldset className="row wrap" style={{ gap: 14, border: 0, padding: 0, margin: 0 }}>
        <legend className="sr">Grinding for every repo</legend>
        <b>Grinding</b>
        <label className="row" style={{ gap: 6 }}><input type="radio" name="grind-mode" checked={mode === 'deep'} disabled={save.isPending} onChange={() => void changeMode('deep')} />Deep</label>
        <label className="row" style={{ gap: 6 }}><input type="radio" name="grind-mode" checked={mode === 'simple'} disabled={save.isPending} onChange={() => void changeMode('simple')} />Simple</label>
        <span className="muted" style={{ fontSize: 13 }}>
          {mode === 'deep' ? 'Every grind keeps going until the reviewer has no blocker or should-fix left.' : 'Every grind, running ones included, stops at the round where the PR is approved.'}
        </span>
      </fieldset>
      {list.length > REPO_FILTER_AFTER ? (
        <input type="search" className="f" aria-label="Filter repos" placeholder={`Filter ${list.length} repos`} value={q} onChange={(e) => setQ(e.target.value)} />
      ) : null}
      {list.length === 0 ? (
        <p className="muted">No repos registered yet. Add folders to scan below, then Find repos.</p>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr><th>Repo</th><th>GitHub</th><th>Auto-grind</th><th>Slack channel</th><th><span className="sr">Remove</span></th></tr>
            </thead>
            <tbody>
              {shown.map((r) => {
                const row = rowOf(r.slug);
                const local = r.slug.startsWith('local/');
                return (
                  <tr key={r.slug}>
                    <td>
                      <b>{r.name && r.name !== r.slug ? r.name : r.slug}</b>
                      <div className="mono faint" style={{ fontSize: 12 }}>{r.path}</div>
                    </td>
                    <td>
                      {local ? (
                        <Button sm onClick={() => setPublishing(r.slug)}>Publish</Button>
                      ) : problems?.[r.slug] ? (
                        <Chip tone="bad" title={problems[r.slug] ?? ''}>{problems[r.slug]}</Chip>
                      ) : (
                        <Chip tone="ship"><Icon n="check" s={12} />Connected</Chip>
                      )}
                    </td>
                    <td><Switch checked={row.auto_grind} label={`Auto-grind ${r.slug}`} onChange={(v) => void change(r.slug, { auto_grind: v })} /></td>
                    <td><SlackCell slug={r.slug} value={row.slack_channel} onSave={(v) => void change(r.slug, { slack_channel: v })} /></td>
                    <td><Button variant="danger" sm onClick={() => void onRemove(r)} aria-label={`Remove ${r.slug}`}>Remove</Button></td>
                  </tr>
                );
              })}
              {shown.length === 0 ? <tr><td colSpan={5} className="muted">No repo matches.</td></tr> : null}
            </tbody>
          </table>
        </div>
      )}
      <label className="lbl" htmlFor="scan-roots">
        Folders to scan
        <span className="hint">One per line. Find repos looks for git checkouts with a GitHub origin in these.</span>
        <textarea id="scan-roots" className="f mono" rows={2} spellCheck={false} value={scanRoots} onChange={(e) => setRoots(e.target.value)} />
      </label>
      {publishing ? <PublishDialog open slug={publishing} onClose={() => setPublishing(null)} /> : null}
    </section>
  );
}
