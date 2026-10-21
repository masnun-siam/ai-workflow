import { useState } from 'react';
import { useSaveSettings, useSettings } from '../api/hooks';
import { Button, toast } from '../components';
import './settings.css';

/** Notes vault: where "No repo yet" sessions, dumps and worklogs are written. Saves only vault_dir. */
export function VaultSection() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [dir, setDir] = useState<string | null>(null);
  const [err, setErr] = useState('');
  const saved = settings.data?.vault_dir ?? '';
  const value = dir ?? saved;

  const onSave = async () => {
    setErr('');
    try {
      const s = await save.mutateAsync({ vault_dir: value.trim() });
      setDir(null);
      toast(`Notes vault saved${s.vault_dir ? '' : ' (using the default folder)'}`);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  return (
    <section className="set-sec" aria-labelledby="set-vault-h">
      <div>
        <h2 id="set-vault-h">Notes vault</h2>
        <p className="muted">The Obsidian vault <code>/dump</code>, <code>/create-prd</code> and worklogs write to. The Start dialog lists its project folders, so you can start those runs without a repo.</p>
      </div>
      <form className="set-form" onSubmit={(e) => { e.preventDefault(); void onSave(); }} noValidate>
        <label className="lbl" htmlFor="vault-dir">
          Vault folder
          <input id="vault-dir" className="f mono" spellCheck={false} placeholder="~/Documents/notes" value={value} aria-invalid={err ? true : undefined} onChange={(e) => setDir(e.target.value)} />
        </label>
        {err ? <p className="err-text" role="alert">{err}</p> : null}
        <div><Button variant="primary" type="submit" disabled={save.isPending || dir === null || value.trim() === saved}>{save.isPending ? 'Saving…' : 'Save vault folder'}</Button></div>
      </form>
    </section>
  );
}
