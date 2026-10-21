import { useEffect, useId, useState } from 'react';
import { api } from '../api/endpoints';
import { useApiMutation, useVaultFolders } from '../api/hooks';
import { Button, Chip } from '../components';
import { folderOf, keywordSuggest, type FolderPick } from './startLogic';

/**
 * "No repo yet": where in the notes vault the idea is filed (05-Work/<Project>/<Feature>). Follows the best
 * keyword match for `text` until the user types; "Suggest with Claude" asks the server (a quick Haiku call).
 */
export function FolderChooser({ text, value, onChange }: { text: string; value: FolderPick; onChange: (v: FolderPick) => void }) {
  const id = useId();
  const folders = useVaultFolders().data?.folders ?? [];
  const [why, setWhy] = useState('');
  const [error, setError] = useState('');
  const suggest = useApiMutation((t: string) => api.suggestFolder(t), [], { quiet: true });

  // While the user has not typed a folder themselves, follow the best keyword match.
  useEffect(() => {
    if (value.touched) return;
    const top = keywordSuggest(folders, text)[0];
    const next = top ? { project: top.project, feature: top.feature ?? '' } : { project: '', feature: '' };
    if (next.project !== value.project || next.feature !== value.feature) onChange({ ...next, touched: false });
  }, [text, folders, value.touched, value.project, value.feature, onChange]);

  const projects = [...new Set(folders.map((f) => f.project))];
  const features = folders.filter((f) => f.project === value.project && f.feature).map((f) => f.feature as string);
  const newProject = !!value.project && !projects.includes(value.project);
  const newFeature = !!value.feature && !newProject && !features.includes(value.feature);
  const picks = keywordSuggest(folders, text);
  const where = folderOf(value);
  const set = (k: 'project' | 'feature') => (e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, [k]: e.target.value, touched: true });

  const ask = async () => {
    setError('');
    setWhy('');
    try {
      const r = (await suggest.mutateAsync(text)) as { project?: string; feature?: string; why?: string };
      onChange({ project: r.project ?? '', feature: r.feature ?? '', touched: true });
      setWhy(r.why ?? '');
    } catch (e) {
      setError(`Claude could not suggest one: ${(e as Error).message}`);
    }
  };

  return (
    <fieldset className="vf">
      <legend>Notes vault folder</legend>
      <p className="muted vf-note">Where this idea is filed. The session confirms it with you first.</p>
      <div className="vf-row">
        <label className="lbl" htmlFor={`${id}-p`}>
          Project
          <input id={`${id}-p`} className="f" list={`${id}-ps`} value={value.project} onChange={set('project')} placeholder="e.g. Gym App" autoComplete="off" />
        </label>
        <label className="lbl" htmlFor={`${id}-f`}>
          Feature
          <input id={`${id}-f`} className="f" list={`${id}-fs`} value={value.feature} onChange={set('feature')} placeholder="e.g. Member check-ins" autoComplete="off" />
        </label>
        <datalist id={`${id}-ps`}>{projects.map((p) => <option key={p} value={p} />)}</datalist>
        <datalist id={`${id}-fs`}>{features.map((f) => <option key={f} value={f} />)}</datalist>
      </div>
      <div className="row wrap">
        {where ? <span className="mono muted">{where}</span> : <span className="muted">No folder yet: the session picks one with you.</span>}
        {newProject ? <Chip tone="plan">new project</Chip> : null}
        {newFeature ? <Chip tone="plan">new feature</Chip> : null}
        <span className="grow" />
        <Button variant="ghost" sm onClick={ask} disabled={suggest.isPending || !text.trim()} title={text.trim() ? 'A quick Haiku call reads your text and the 05-Work folders' : 'Describe the idea first'}>
          {suggest.isPending ? 'Asking Claude…' : 'Suggest with Claude'}
        </Button>
      </div>
      {picks.length > 0 ? (
        <div className="chips-row" role="group" aria-label="Matching folders">
          <span className="muted">Matches:</span>
          {picks.map((p) => (
            <button key={`${p.project}/${p.feature}`} type="button" className="pill-btn" onClick={() => onChange({ project: p.project, feature: p.feature ?? '', touched: true })}>
              {p.project}{p.feature ? ` / ${p.feature}` : ''}
            </button>
          ))}
        </div>
      ) : null}
      {why ? <p className="muted">Claude: {why}</p> : null}
      {error ? <p className="err-text" role="alert">{error}</p> : null}
    </fieldset>
  );
}
