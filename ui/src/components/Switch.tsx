import * as RS from '@radix-ui/react-switch';

/** Radix switch with the prototype's look. `label` is required: it is the control's accessible name. */
export function Switch({ checked, onChange, label, disabled, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; id?: string }) {
  return (
    <RS.Root
      id={id}
      className="switch"
      checked={checked}
      onCheckedChange={onChange}
      aria-label={label}
      disabled={disabled}
      onClick={(e) => e.stopPropagation()}
    />
  );
}
