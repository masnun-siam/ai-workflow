import { useSyncExternalStore } from 'react';

export interface ToastOpts {
  tone?: 'bad';
  action?: { label: string; onClick: () => void };
  ms?: number;
}
interface ToastItem extends ToastOpts {
  id: number;
  msg: string;
}

let items: ToastItem[] = [];
let seq = 0;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const dismiss = (id: number) => {
  items = items.filter((t) => t.id !== id);
  emit();
};

/** Show a toast from anywhere (also used by the query cache for failed writes). */
export function toast(msg: string, o: ToastOpts = {}) {
  const id = ++seq;
  items = [...items.slice(-3), { id, msg, ...o }];
  emit();
  setTimeout(() => dismiss(id), o.ms ?? (o.action || o.tone ? 7000 : 4200));
}
toast.error = (msg: string, o: Omit<ToastOpts, 'tone'> = {}) => toast(msg, { ...o, tone: 'bad' });

/** `const toast = useToast(); toast('Saved', {action: {label: 'Watch', onClick}})`, `toast.error(msg)`. */
export const useToast = () => toast;

/** Mounted once by the app. Polite live region so screen readers announce toasts. */
export function Toaster() {
  const list = useSyncExternalStore(
    (cb) => (subs.add(cb), () => subs.delete(cb)),
    () => items,
  );
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast${t.tone === 'bad' ? ' bad' : ''}`}>
          <span>{t.msg}</span>
          {t.action ? (
            <button type="button" onClick={() => { t.action?.onClick(); dismiss(t.id); }}>{t.action.label}</button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
