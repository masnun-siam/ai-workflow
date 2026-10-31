import type { ReactNode } from 'react';
import { Button } from './Button';
import { Dialog } from './Dialog';

interface PauseDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  afterLabel: string;
  nowLabel: string;
  body: ReactNode;
  onAfter: () => void;
  onNow: () => void;
}

/** Pause asks when: after the running work, or now. useConfirm has only two buttons, so this has its own footer. */
export function PauseDialog({ open, onOpenChange, title, afterLabel, nowLabel, body, onAfter, onNow }: PauseDialogProps) {
  const choose = (act: () => void) => () => {
    onOpenChange(false);
    act();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      alert
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" autoFocus onClick={choose(onAfter)}>{afterLabel}</Button>
          <Button variant="solid-danger" onClick={choose(onNow)}>{nowLabel}</Button>
        </>
      }
    >
      {body}
    </Dialog>
  );
}
