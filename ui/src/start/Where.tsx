import { useState } from 'react';
import { api } from '../api/endpoints';
import { useApiMutation } from '../api/hooks';
import type { Repo } from '../api/types';
import { Button } from '../components';
import { folderOf } from './startLogic';
import type { WhereSel } from './startLogic';

const VAULT = '__vault';
const PATH = '__path';

/**
 * "Where": a registered repo, "No repo yet" (notes vault, for commands that can run without one), or a typed
 * / browsed checkout path. "Create a new repo…" opens the Create dialog and selects the repo it makes.
 */
export function Where({ repos, value, onChange, canVault, canBrowse, vaultFolder, onCreate }: {
  repos: Repo[];
  value: WhereSel;
  onChange: (w: WhereSel) => void;
  canVault: boolean;
  canBrowse: boolean;
  vaultFolder: { project: string; feature: string };
  onCreate: () => void;
}) {
  const browse = useApiMutation((start?: string) => api.browse(start), [], { quiet: true });
  const [err, setErr] = useState('');
  const selected = value.kind === 'vault' ? VAULT : value.kind === 'path' ? PATH : value.slug;

  const pick = async () => {
    setErr('');
    try {
      const start = value.kind === 'path' ? value.path : repos.find((r) => value.kind === 'repo' && r.slug === value.slug)?.path;
      const r = await browse.mutateAsync(start);
      if (r.path) {
        const known = repos.find((x) => x.path === r.path); // a path that is a registered checkout is that repo
        onChange(known ? { kind: 'repo', slug: known.slug } : { kind: 'path', path: r.path });
      }
    } catch (e) {
      setErr(`Could not open the folder picker: ${(e as Error).message}`);
    }
  };

  return (
    <div className="lbl">
      <label htmlFor="start-where">Where</label>
      <select
        id="start-where"
        className="f"
        value={selected}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === VAULT ? { kind: 'vault' } : v === PATH ? { kind: 'path', path: value.kind === 'path' ? value.path : '' } : { kind: 'repo', slug: v });
        }}
      >
        {repos.map((r) => (
          <option key={r.slug} value={r.slug}>{r.name && r.name !== r.slug ? `${r.name} (${r.slug})` : r.slug}</option>
        ))}
        {canVault ? <option value={VAULT}>No repo yet: notes vault</option> : null}
        <option value={PATH}>Another folder…</option>
      </select>
      {value.kind === 'path' ? (
        <span className="row">
          <input
            className="f mono"
            aria-label="Path to a git checkout"
            placeholder="/Users/you/Projects/repo"
            autoComplete="off"
            spellCheck={false}
            value={value.path}
            onChange={(e) => onChange({ kind: 'path', path: e.target.value })}
          />
          {canBrowse ? <Button onClick={pick} disabled={browse.isPending}>Browse…</Button> : null}
        </span>
      ) : null}
      {value.kind === 'vault' ? (
        <span className="hint">
          Runs in your notes vault{folderOf(vaultFolder) ? <>, filed under <span className="mono">{folderOf(vaultFolder)}</span></> : ' and files under 05-Work/<Project>/<Feature>'}.
        </span>
      ) : null}
      {!canVault && repos.length === 0 && value.kind !== 'path' ? <span className="hint">No repos registered yet. Add one in Settings, or enter a path.</span> : null}
      {err ? <span className="err-text" role="alert">{err}</span> : null}
      <span className="row wrap" style={{ fontWeight: 400 }}>
        <Button variant="ghost" sm onClick={onCreate}>Create a new repo…</Button>
        {canBrowse && value.kind !== 'path' ? <Button variant="ghost" sm onClick={pick} disabled={browse.isPending}>Browse for a folder…</Button> : null}
      </span>
    </div>
  );
}
