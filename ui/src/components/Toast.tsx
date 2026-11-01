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
const timers = new Map<number, ReturnType<typeof setTimeout>>();
const dismiss = (id: number) => {
  clearTimeout(timers.get(id));
  timers.delete(id);
  items = items.filter((t) => t.id !== id);
  emit();
};
const ttl = (t: ToastOpts) => t.ms ?? (t.action || t.tone ? 7000 : 4200);
const resume = (t: ToastItem) => {
  clearTimeout(timers.get(t.id));
  timers.set(t.id, setTimeout(() => dismiss(t.id), ttl(t)));
};
const pause = (id: number) => {
  clearTimeout(timers.get(id));
  timers.delete(id);
};

/** Show a toast from anywhere (also used by the query cache for failed writes). */
export function toast(msg: string, o: ToastOpts = {}) {
  const id = ++seq;
  const item = { id, msg, ...o };
  items.slice(0, -3).forEach((t) => pause(t.id));
  items = [...items.slice(-3), item];
  emit();
  resume(item);
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
        <div
          key={t.id}
          className={`toast${t.tone === 'bad' ? ' bad' : ''}`}
          onMouseEnter={() => pause(t.id)}
          onMouseLeave={() => resume(t)}
          onFocus={() => pause(t.id)}
          onBlur={() => resume(t)}
        >
          <span>{t.msg}</span>
          {t.action ? (
            <button type="button" onClick={() => { t.action?.onClick(); dismiss(t.id); }}>{t.action.label}</button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
