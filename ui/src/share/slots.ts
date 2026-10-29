import type { Span } from '../lib/anchor';

export interface Slot { el: HTMLElement; ids: string[] }
const BLOCK = 'p,li,h1,h2,h3,h4,h5,h6,td,th,pre';

/** One empty slot per block that holds a highlighted thread (after the block; inside a cell), threads in text order. */
export function placeSlots(root: HTMLElement, spans: (Span & { id: string })[]): { slots: Slot[]; remove: () => void } {
  const byBlock = new Map<Element, string[]>();
  for (const { id } of [...spans].sort((a, b) => a.start - b.start)) {
    const mark = Array.from(root.querySelectorAll<HTMLElement>('mark.anchor-hl')).find((m) => m.dataset.thread === id);
    const found = mark?.closest(BLOCK);
    const block = found && root.contains(found) ? found : root;
    byBlock.set(block, [...(byBlock.get(block) ?? []), id]);
  }
  const slots = [...byBlock].map(([block, ids]) => {
    const el = document.createElement('div');
    el.className = 'thread-slot';
    el.setAttribute('data-no-anchor', '');
    if (block === root || /^T[DH]$/.test(block.tagName)) block.append(el); else block.after(el);
    return { el, ids };
  });
  return { slots, remove: () => slots.forEach((s) => s.el.remove()) };
}
