import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes } from 'react';
import { Link, type LinkProps } from 'react-router-dom';

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
}

/** `<button>` with the prototype's .btn styles. Defaults to type="button" so it never submits a form by accident. */
export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & Common>(function Button(
  { variant = 'default', sm, icon, className, type = 'button', ...rest },
  ref,
) {
  return <button ref={ref} type={type} className={cls(variant, sm, icon, className)} {...rest} />;
});

/** In-app link styled as a button. */
export function LinkButton({ variant = 'default', sm, icon, className, ...rest }: LinkProps & Common) {
  return <Link className={cls(variant, sm, icon, className)} {...rest} />;
}

/** External link (GitHub etc.) styled as a button; opens in a new tab. */
export function ExtButton({ variant = 'default', sm, icon, className, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & Common) {
  return <a className={cls(variant, sm, icon, className)} target="_blank" rel="noopener noreferrer" {...rest} />;
}
