import { forwardRef, useCallback, useRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ForwardedRef, type ReactNode } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import { useAction, type ActionKey } from '../shell/shortcuts';

export type Variant = 'default' | 'primary' | 'you' | 'danger' | 'solid-danger' | 'ghost';
const cls = (v: Variant, sm?: boolean, icon?: boolean, extra?: string) =>
  ['btn', v === 'primary' && 'primary', v === 'you' && 'you', v === 'danger' && 'danger', v === 'solid-danger' && 'danger solid', v === 'ghost' && 'ghost', sm && 'sm', icon && 'icon', extra]
    .filter(Boolean)
    .join(' ');

interface Common {
  variant?: Variant;
  sm?: boolean;
  /** Square icon-only button: pass an aria-label. */
  icon?: boolean;
  /** Key that does what a click does (FR-4); shown as a badge and in the tooltip, listed in the palette. */
  shortcut?: ActionKey;
  /** Wins over other buttons on the same key and level; defaults to primary and "you" buttons. */
  primary?: boolean;
  /** Register nothing: shell chrome the global keys already cover. */
  noAction?: boolean;
}

const keyText = (k: ActionKey) => (k === 'Enter' ? 'Enter' : k.toUpperCase());

/** The button's name for the palette: its aria-label, else its text without the key badge. */
function labelOf(el: HTMLElement | null) {
  if (!el) return '';
  const aria = el.getAttribute('aria-label');
  if (aria) return aria;
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('[data-kbd]').forEach((n) => n.remove());
  return (copy.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/** Registers the element as an action (a click on key press) and returns the ref, badge and attributes to render. */
function useButtonAction<T extends HTMLElement>(
  { shortcut, primary, noAction, variant, disabled, title }: Common & { disabled?: boolean; title?: string },
  forwarded?: ForwardedRef<T>,
) {
  const el = useRef<T | null>(null);
  const ref = useCallback((n: T | null) => {
    el.current = n;
    if (typeof forwarded === 'function') forwarded(n);
    else if (forwarded) forwarded.current = n;
  }, [forwarded]);
  useAction(noAction ? null : {
    label: () => labelOf(el.current),
    key: shortcut,
    primary: primary ?? (variant === 'primary' || variant === 'you'),
    disabled,
    run: () => el.current?.click(),
  });
  const key = shortcut ? keyText(shortcut) : null;
  return {
    ref,
    badge: key ? <span className="kbd hide-sm" data-kbd aria-hidden="true">{key}</span> : null as ReactNode,
    attrs: key ? { 'aria-keyshortcuts': key, title: title ? `${title} (${key})` : `Shortcut: ${key}` } : { title },
  };
}

/** `<button>` with the prototype's .btn styles. Defaults to type="button" so it never submits a form by accident. */
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & Common>(function Button(
  { variant = 'default', sm, icon, className, type = 'button', shortcut, primary, noAction, children, ...rest },
  fwd,
) {
  const { ref, badge, attrs } = useButtonAction<HTMLButtonElement>({ shortcut, primary, noAction, variant, disabled: rest.disabled, title: rest.title }, fwd);
  return (
    <button ref={ref} type={type} className={cls(variant, sm, icon, className)} {...rest} {...attrs}>
      {children}
      {badge}
    </button>
  );
});

/** In-app link styled as a button. */
export function LinkButton({ variant = 'default', sm, icon, className, shortcut, primary, noAction, children, ...rest }: LinkProps & Common) {
  const { ref, badge, attrs } = useButtonAction<HTMLAnchorElement>({ shortcut, primary, noAction, variant, title: rest.title });
  return (
    <Link ref={ref} className={cls(variant, sm, icon, className)} {...rest} {...attrs}>
      {children}
      {badge}
    </Link>
  );
}

/** External link (GitHub etc.) styled as a button; opens in a new tab. */
export function ExtButton({ variant = 'default', sm, icon, className, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & Common) {
  return <a className={cls(variant, sm, icon, className)} target="_blank" rel="noopener noreferrer" {...rest} />;
}
