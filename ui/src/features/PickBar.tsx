import { Button } from '../components';

/** The Small changes pick bar: Refine N for the picked unrefined issues, Run N for the picked refined ones, and Clear. */
export function PickBar({ refine, run, busy, refineLock, onRefine, onRun, onClear }: { refine: number; run: number; busy: boolean; refineLock?: string; onRefine: () => void; onRun: () => void; onClear: () => void }) {
  return (
    <div className="row">
      {refine > 0 ? <Button variant="primary" sm shortcut="e" disabled={busy || !!refineLock} title={refineLock} onClick={onRefine}>Refine {refine}</Button> : null}
      {run > 0 ? <Button variant="primary" sm onClick={onRun}>Run {run}</Button> : null}
      <Button variant="ghost" sm onClick={onClear}>Clear</Button>
    </div>
  );
}
