import * as RD from '@radix-ui/react-dialog';
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { KeyScope } from '../shell/shortcuts';
import { Button } from './Button';

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Short plain-text description for screen readers (and shown under the title when `showDescription`). */
  description?: string;
  showDescription?: boolean;
  wide?: boolean;
  alert?: boolean; // role=alertdialog: confirmations
  footer?: ReactNode;
  children?: ReactNode;
  /** Body without the default padding/scroll wrapper (Start dialog lays out its own columns). */
  bare?: boolean;
}

/** In-app modal. Focus trap, Esc, scrim click and focus return come from Radix. */
export function Dialog({ open, onOpenChange, title, description, showDescription, wide, alert, footer, children, bare }: DialogProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="scrim-r" />
        <RD.Content className={`dialog dlg-pos${wide ? ' wide' : ''}`} role={alert ? 'alertdialog' : 'dialog'}>
          <KeyScope level="page" active={false}>
            <div className="d-h">
              <RD.Title asChild><h2 style={{ fontSize: 17 }}>{title}</h2></RD.Title>
              {description ? (
                <RD.Description className={showDescription ? 'muted' : 'sr'}>{description}</RD.Description>
              ) : (
                <RD.Description className="sr">{title}</RD.Description>
              )}
            </div>
            {bare ? children : <div className="d-b">{children}</div>}
            {footer ? <div className="d-f">{footer}</div> : null}
          </KeyScope>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

// ---- useConfirm: in-app confirm, never window.confirm (FR-31) ------------------------------------
export interface ConfirmOpts {
  title: string;
  body?: ReactNode;
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  wide?: boolean;
}
type Confirm = (o: ConfirmOpts) => Promise<boolean>;
const ConfirmCtx = createContext<Confirm>(() => Promise.resolve(false));

/** `const confirm = useConfirm(); if (await confirm({title: 'Stop it?', body, okLabel: 'Stop', danger: true})) ...` */
export const useConfirm = () => useContext(ConfirmCtx);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ConfirmOpts | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);
  const confirm = useCallback<Confirm>((o) => {
    resolver.current?.(false);
    setState(o);
    return new Promise<boolean>((res) => {
      resolver.current = res;
    });
  }, []);
  const close = (v: boolean) => {
    resolver.current?.(v);
    resolver.current = null;
    setState(null);
  };
  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      <Dialog
        open={!!state}
        onOpenChange={(o) => !o && close(false)}
        title={state?.title ?? ''}
        alert
        wide={state?.wide}
        footer={
          <>
            <Button variant="ghost" onClick={() => close(false)}>{state?.cancelLabel ?? 'Cancel'}</Button>
            <Button variant={state?.danger ? 'solid-danger' : 'primary'} autoFocus onClick={() => close(true)}>{state?.okLabel ?? 'Confirm'}</Button>
          </>
        }
      >
        {state?.body}
      </Dialog>
    </ConfirmCtx.Provider>
  );
}
