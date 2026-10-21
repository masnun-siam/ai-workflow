import { useEffect, useState, type FormEvent } from 'react';
import { api } from '../api/endpoints';
import { useApiMutation, useRepos, useVaultPrd, keys } from '../api/hooks';
import { Button, Chip, Dialog, toast } from '../components';
import './repos.css';

/** A repo name the server accepts: lower case, letters, digits, `.`, `_`, `-`. */
export const repoName = (s: string) => typingName(s).replace(/^-+|-+$/g, '');
/** While typing: same, but a trailing `-` stays so "gym app" can become "gym-app". */
export const typingName = (s: string) => s.toLowerCase().replace(/[^a-z0-9._-]+/g, '-').slice(0, 100);

/** Folders the registered repos live in, most used first: likely homes for a new one. */
export function parentFolders(repos: { path: string }[], n = 5): string[] {
  const count = new Map<string, number>();
  for (const r of repos) {
    const dir = r.path.replace(/\/+$/, '').replace(/\/[^/]+$/, '');
    if (dir.startsWith('/')) count.set(dir, (count.get(dir) ?? 0) + 1);
  }
  return [...count].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n).map(([d]) => d);
}
const tilde = (p: string) => p.replace(/^\/Users\/[^/]+/, '~');

interface Props {
  open: boolean;
  /** The notes-vault folder holding the PRD this repo is for (`05-Work/<Project>/<Feature>`). */
  vaultFolder?: string;
  onClose: () => void;
  /** Called with the new repo after it is made (the Where picker selects it). */
  onCreated?: (r: { slug: string; path: string }) => void;
  /** A starting name, e.g. the PRD's title. */
  name?: string;
}

/** Create a local git repo with a README (and the vault PRD in docs/prds/), registered as local/<name>. */
export function CreateRepoDialog({ open, onClose, ...rest }: Props) {
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Create a repo"
      description="Makes a local git repo with a README and adds it to your repos. Nothing is committed or pushed."
      showDescription
      bare
    >
      <CreateForm onClose={onClose} {...rest} />
    </Dialog>
  );
}

function CreateForm({ vaultFolder, name: initial, onClose, onCreated }: Omit<Props, 'open'>) {
  const repos = useRepos();
  const [name, setName] = useState(repoName(initial ?? ''));
  const finalName = repoName(name);
  const [parent, setParent] = useState('');
  const [prdFolder, setPrdFolder] = useState(vaultFolder ?? '');
  const [showPrd, setShowPrd] = useState(!!vaultFolder);
  const [error, setError] = useState('');
  const canBrowse = repos.data?.can_browse === true;
  const homes = parentFolders(repos.data?.repos ?? []);
  const prd = useVaultPrd(showPrd ? prdFolder.trim() : '');
  const create = useCreate();
  const browse = useApiMutation((start?: string) => api.browse(start), [], { quiet: true });

  const pick = async () => {
    try {
      const r = await browse.mutateAsync(parent || undefined);
      if (r.path) {
        setParent(r.path);
        setError('');
      }
    } catch (e) {
      setError(`Could not open the folder picker: ${(e as Error).message}`);
    }
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!finalName || !parent.trim()) return setError(!finalName ? 'Name the repo' : 'Choose the folder to create it in');
    if (showPrd && prdFolder.trim() && !prd.data?.exists) return setError('No PRD.md in that vault folder');
    setError('');
    try {
      const r = await create.mutateAsync({ parent: parent.trim(), name: finalName, prd_folder: showPrd && prdFolder.trim() ? prdFolder.trim() : undefined });
      const made = { slug: r.slug ?? `local/${finalName}`, path: r.path ?? '' };
      toast(`Created ${made.slug}`);
      onCreated?.(made);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  useEffect(() => setError(''), [name, parent]);

  const p = prd.data;
  return (
    <form className="dlg-form" onSubmit={submit} noValidate>
      <div className="d-b">
        <label className="lbl" htmlFor="cr-name">
          Name
          <input id="cr-name" className="f" value={name} autoFocus autoComplete="off" spellCheck={false} placeholder="gym-app" onChange={(e) => setName(typingName(e.target.value))} />
        </label>
        <label className="lbl" htmlFor="cr-parent">
          Create it in
          <span className="row">
            <input id="cr-parent" className="f mono" value={parent} autoComplete="off" spellCheck={false} placeholder="/Users/you/Projects or ~/Projects" onChange={(e) => setParent(e.target.value)} />
            {canBrowse ? <Button onClick={pick} disabled={browse.isPending}>Choose…</Button> : null}
          </span>
        </label>
        {homes.length > 0 ? (
          <div className="chips-row" role="group" aria-label="Where your repos live">
            <span className="muted">Where your repos live:</span>
            {homes.map((d) => (
              <button key={d} type="button" className="pill-btn" aria-pressed={parent === d} onClick={() => setParent(d)}>{tilde(d)}</button>
            ))}
          </div>
        ) : null}
        {parent && finalName ? <p className="path-preview">{parent.trim().replace(/\/+$/, '')}/{finalName}</p> : null}
        {showPrd ? (
          <label className="lbl" htmlFor="cr-prd">
            PRD from the vault folder
            <span className="hint">Copied to docs/prds/ and used for the README.</span>
            <input id="cr-prd" className="f mono" value={prdFolder} placeholder="05-Work/<Project>/<Feature>" onChange={(e) => setPrdFolder(e.target.value)} />
            {prdFolder.trim() && p ? (
              p.exists ? (
                <span className="row wrap" style={{ fontWeight: 400 }}>
                  {p.title || 'PRD'}
                  <Chip tone={p.status === 'Approved' ? 'ship' : 'review'}>{p.status || 'no status'}</Chip>
                  {p.status !== 'Approved' ? <span className="muted">Not approved yet; you can still create the repo.</span> : null}
                </span>
              ) : (
                <span className="err-text" role="status">No PRD.md in that folder.</span>
              )
            ) : null}
          </label>
        ) : (
          <div><Button variant="ghost" sm onClick={() => setShowPrd(true)}>Start from a PRD in the notes vault…</Button></div>
        )}
        {error ? <p className="err-text" role="alert">{error}</p> : null}
      </div>
      <div className="d-f">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Creating…' : 'Create repo'}</Button>
      </div>
    </form>
  );
}

/** Quiet create: the dialog shows the error itself. */
function useCreate() {
  return useApiMutation((v: { parent: string; name: string; prd_folder?: string }) => api.createRepo(v.parent, v.name, v.prd_folder), [keys.repos, ['sessions']], { quiet: true });
}
