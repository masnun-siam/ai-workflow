import { useState, type FormEvent } from 'react';
import { api } from '../api/endpoints';
import { keys, useApiMutation, useOwners } from '../api/hooks';
import { Button, Dialog, toast } from '../components';
import { repoName, typingName } from './CreateRepoDialog';
import './repos.css';

interface Props {
  open: boolean;
  /** The `local/<name>` repo to publish. */
  slug: string;
  onClose: () => void;
}

/** Publish a local/<name> repo to GitHub: owner, name, private. Afterwards it is registered as owner/name. */
export function PublishDialog({ open, slug, onClose }: Props) {
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Publish to GitHub"
      description={`Creates the GitHub repo for ${slug}, makes the first commit (README and PRD) if there is none, and pushes it. aiw then knows it as owner/name, so tasks, issues and dispatch can run.`}
      showDescription
      bare
    >
      <PublishForm slug={slug} onClose={onClose} />
    </Dialog>
  );
}

function PublishForm({ slug, onClose }: Omit<Props, 'open'>) {
  const owners = useOwners();
  const [owner, setOwner] = useState('');
  const [name, setName] = useState(repoName(slug.replace(/^local\//, '')));
  const [priv, setPriv] = useState(true);
  const [error, setError] = useState('');
  const publish = useApiMutation(
    (v: { owner: string; name: string; priv: boolean }) => api.publishRepo(slug, v.owner, v.name, v.priv),
    [keys.repos, ['inbox']],
    { quiet: true },
  );
  const list = owners.data?.owners ?? [];
  const chosen = owner || list[0] || '';
  const finalName = repoName(name);
  const loadError = owners.isError ? `Could not list your GitHub accounts: ${owners.error.message}` : '';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!chosen || !finalName) return setError(!chosen ? 'Pick an owner' : 'Name the repo');
    setError('');
    try {
      await publish.mutateAsync({ owner: chosen, name: finalName, priv });
      toast(`Published ${chosen}/${finalName}`);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form className="dlg-form" onSubmit={submit} noValidate>
      <div className="d-b">
        <label className="lbl" htmlFor="pub-owner">
          Owner
          <select id="pub-owner" className="f" value={chosen} disabled={!list.length} onChange={(e) => setOwner(e.target.value)}>
            {owners.isPending ? <option>Loading…</option> : list.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="lbl" htmlFor="pub-name">
          Name
          <input id="pub-name" className="f" value={name} autoComplete="off" spellCheck={false} onChange={(e) => setName(typingName(e.target.value))} />
        </label>
        <label className="check-row" htmlFor="pub-private">
          <input id="pub-private" type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} /> Private
        </label>
        {chosen && finalName ? <p className="path-preview">github.com/{chosen}/{finalName} · {priv ? 'private' : 'public'}</p> : null}
        {loadError || error ? <p className="err-text" role="alert">{error || loadError}</p> : null}
      </div>
      <div className="d-f">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" type="submit" disabled={publish.isPending || !list.length}>{publish.isPending ? 'Publishing…' : 'Publish'}</Button>
      </div>
    </form>
  );
}
