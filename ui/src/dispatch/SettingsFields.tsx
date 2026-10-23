// The dispatch settings as form fields: the New dispatch dialog and the live editor on a dispatch share them.
import { useEffect, useState } from 'react';
import { useSaveSettings } from '../api/hooks';
import type { DispatchSettings, GrindMode } from '../api/types';
import { Button, ModelEffortPicker, Switch } from '../components';

const GRIND: { v: GrindMode; label: string; hint: string }[] = [
  { v: 'off', label: 'Off', hint: 'No grind: a ready PR goes straight to the merge gate.' },
  { v: 'simple', label: 'Simple', hint: 'Grind until the reviewer bot approves.' },
  { v: 'full', label: 'Full', hint: 'Grind until zero blocker and should-fix findings.' },
];

export function GrindSeg({ value, onChange }: { value: GrindMode; onChange: (v: GrindMode) => void }) {
  return (
    <div className="seg" role="radiogroup" aria-label="Grind mode">
      {GRIND.map((g) => (
        <button key={g.v} type="button" role="radio" aria-checked={value === g.v} className={value === g.v ? 'on' : ''} title={g.hint} onClick={() => onChange(g.v)}>
          {g.label}
        </button>
      ))}
    </div>
  );
}

export function MaxStepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="row" style={{ gap: 4 }}>
      <Button sm icon aria-label="Fewer at once" disabled={value <= 1} onClick={() => onChange(value - 1)}>−</Button>
      <span className="mono" style={{ minWidth: 22, textAlign: 'center' }} aria-live="polite">{value}</span>
      <Button sm icon aria-label="More at once" disabled={value >= 10} onClick={() => onChange(value + 1)}>+</Button>
    </div>
  );
}

/** A text field that reports on blur or Enter, so a live dispatch is not edited on every keystroke. */
function LazyText({ id, value, onCommit, placeholder }: { id: string; value: string; onCommit: (v: string) => void; placeholder?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input
      id={id}
      className="f"
      value={v}
      placeholder={placeholder}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => v !== value && onCommit(v)}
      onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()}
    />
  );
}

/**
 * Every setting. `live` marks the editor on a running dispatch: the feature branch is fixed there (lanes
 * already target it) and edits apply at each lane's next step.
 */
export function SettingsFields({ value, onChange, live }: { value: DispatchSettings; onChange: (p: Partial<DispatchSettings>) => void; live?: boolean }) {
  const saveDefaults = useSaveSettings();
  // The saved defaults follow the latest pick, so every picker starts from it.
  const pickRun = (p: { model?: string | null; effort?: string | null }) => {
    onChange(p as Partial<DispatchSettings>);
    saveDefaults.mutate({ ...(p.model !== undefined ? { run_model: p.model } : {}), ...(p.effort !== undefined ? { run_effort: p.effort } : {}) });
  };
  const grindHint = GRIND.find((g) => g.v === value.grind)?.hint;
  return (
    <div className="dsp-settings">
      <div className="dsp-field">
        <span className="dsp-k">Grind</span>
        <GrindSeg value={value.grind} onChange={(grind) => onChange({ grind })} />
        <span className="faint dsp-hint">{grindHint} Repos with no Slack channel skip it.</span>
      </div>
      <div className="dsp-field">
        <span className="dsp-k" id="am-l">Auto-merge</span>
        <Switch label="Auto-merge" checked={value.auto_merge} onChange={(auto_merge) => onChange({ auto_merge })} />
        <span className="faint dsp-hint">
          {value.auto_merge ? 'Merge commit once CI is green, a review approves (not needed on your own repo) and the grind is done.' : 'Each PR waits for you to merge it; then the issue is closed and cleaned up.'}
        </span>
      </div>
      <div className="dsp-field">
        <span className="dsp-k">At once</span>
        <MaxStepper value={value.max} onChange={(max) => onChange({ max })} />
        <span className="faint dsp-hint">Issues built at the same time. Each builds and tests in its own worktree.</span>
      </div>
      <div className="dsp-field">
        <label className="dsp-k" htmlFor="ds-fb">Feature branch</label>
        {live ? (
          <span className="mono">{value.feature_branch ?? 'each issue’s own base'}</span>
        ) : (
          <LazyText id="ds-fb" value={value.feature_branch ?? ''} placeholder="none (issue’s own base)" onCommit={(v) => onChange({ feature_branch: v.trim() || null })} />
        )}
        {!live ? <span className="faint dsp-hint">Cut from the default branch if missing; every PR targets it.</span> : null}
      </div>
      <div className="dsp-field">
        <span className="dsp-k">Model</span>
        <ModelEffortPicker model={value.model} effort={value.effort} onChange={pickRun} />
      </div>
    </div>
  );
}
