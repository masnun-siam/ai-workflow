/** The stack of open layers (popovers, dialogs, panels, the drawer). The last one registered is the top one:
 *  Escape closes it first, and global keys stay off while a popover or dialog is open. */
type Layer = { close: () => void; modal: boolean };
const stack: Layer[] = [];

/** Register an open layer; returns the function that removes it. `modal` layers (dialogs, popovers) also mute global keys. */
export function pushLayer(close: () => void, modal = true): () => void {
  const l: Layer = { close, modal };
  stack.push(l);
  return () => { const i = stack.indexOf(l); if (i >= 0) stack.splice(i, 1); };
}

/** Close the top layer. True when there was one. */
export function closeTopLayer(): boolean {
  const top = stack[stack.length - 1];
  if (!top) return false;
  top.close();
  return true;
}

export const layerCount = (): number => stack.length;

/** A popover or dialog is open: global shortcuts are ignored. The DOM check covers a dialog rendered outside a registering component. */
export function overlayOpen(): boolean {
  if (stack.some((l) => l.modal)) return true;
  return typeof document !== "undefined" && !!document.querySelector('.dlg[aria-modal="true"], .wpanel[aria-modal="true"], .pop');
}
