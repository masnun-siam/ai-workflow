import { useState } from 'react';
import { useSaveSettings, useSettings } from '../api/hooks';
import { Switch, toast } from '../components';
import './settings.css';

/** jev: one switch that stops every jev call, and a read-only line on whether the CLI is installed. */
export function JevSection() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [over, setOver] = useState<boolean | null>(null); // optimistic value while a save is in flight
  const on = over ?? settings.data?.use_jev ?? true;
  const found = settings.data?.jev_installed;

  const change = async (v: boolean) => {
    setOver(v);
    try {
      await save.mutateAsync({ use_jev: v });
      toast(v ? 'jev is on' : 'jev is off');
    } catch {
      /* the error toast comes from the mutation cache */
    } finally {
      setOver(null);
    }
  };

  return (
    <section className="set-sec" aria-labelledby="set-jev-h">
      <div>
        <h2 id="set-jev-h">jev</h2>
        <p className="muted">jev answers quick judgment calls (capture route, Away mode risk, Inbox order, readiness and duplicate warnings, grind hints). Turning it off stops every call.</p>
      </div>
      <label className="lbl">
        <Switch checked={on} label="Use jev" onChange={(v) => void change(v)} />
      </label>
      {found === undefined ? null : <p className="muted">{found ? 'jev found' : 'jev not found — see docs/INSTALL.md'}</p>}
    </section>
  );
}
