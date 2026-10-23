import { useId } from 'react';

export const MODELS = [
  { value: 'opus', label: 'Opus' },
  { value: 'sonnet', label: 'Sonnet' },
  { value: 'haiku', label: 'Haiku' },
];
export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];

export interface ModelEffortPickerProps {
  model: string | null;
  effort: string | null;
  onChange: (patch: { model?: string | null; effort?: string | null }) => void;
  disabled?: boolean;
  compact?: boolean;
}

/** The run's model and effort: two dropdowns, empty meaning Claude's default. A value outside the lists (an older free-text model) stays as an extra option. */
export function ModelEffortPicker({ model, effort, onChange, disabled, compact }: ModelEffortPickerProps) {
  const id = useId();
  const extra = (v: string | null, list: string[]) => (v && !list.includes(v) ? <option value={v}>{v}</option> : null);
  return (
    <div className={`mep${compact ? ' compact' : ''}`}>
      <div className="lbl">
        <label htmlFor={`${id}-model`}>Model</label>
        <select id={`${id}-model`} className="f" disabled={disabled} value={model ?? ''} onChange={(e) => onChange({ model: e.target.value || null })}>
          <option value="">Default</option>
          {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          {extra(model, MODELS.map((m) => m.value))}
        </select>
      </div>
      <div className="lbl">
        <label htmlFor={`${id}-effort`}>Effort</label>
        <select id={`${id}-effort`} className="f" disabled={disabled} value={effort ?? ''} onChange={(e) => onChange({ effort: e.target.value || null })}>
          <option value="">Default</option>
          {EFFORTS.map((x) => <option key={x} value={x}>{x}</option>)}
          {extra(effort, EFFORTS)}
        </select>
      </div>
    </div>
  );
}
