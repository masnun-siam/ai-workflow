import { type RefObject, useEffect, useState } from 'react';
import { type Anchor, countPoints, makeAnchor, MAX_QUOTE } from '../lib/anchor';
import { bodyText, offsetsOf } from '../lib/anchorDom';

export interface Sel { start: number; end: number; tooLong: boolean; anchor: Anchor; top: number; left: number }

const inBody = (root: Element, n: Node): boolean => {
  const el = n.nodeType === 1 ? (n as Element) : n.parentElement;
  return root.contains(n) && !el?.closest('pre.mermaid,[data-no-anchor]');
};

/** The reader's selection when it starts and ends in the PRD body and holds something to quote. */
export function readSelection(root: Element): Sel | null {
  const s = window.getSelection();
  if (!s || s.rangeCount === 0 || s.isCollapsed) return null;
  const r = s.getRangeAt(0);
  if (!inBody(root, r.startContainer) || !inBody(root, r.endContainer)) return null;
  const text = bodyText(root);
  const { start, end } = offsetsOf(root, r);
  if (!text.slice(start, end).trim()) return null;
  const rect = r.getBoundingClientRect?.(); // jsdom has no layout
  return { start, end, tooLong: countPoints(text.slice(start, end)) > MAX_QUOTE, anchor: makeAnchor(text, start, end), top: (rect?.bottom ?? 0) + window.scrollY, left: (rect?.left ?? 0) + window.scrollX };
}

/** Tracks the body selection. Focus inside the comment UI keeps the last one, as clicking or tabbing to the button can drop it. */
export function useBodySelection(root: RefObject<HTMLElement>) {
  const [sel, setSel] = useState<Sel | null>(null);
  useEffect(() => {
    const on = () => {
      const next = root.current && readSelection(root.current);
      if (next) setSel((cur) => (cur && cur.start === next.start && cur.end === next.end && cur.anchor.exact === next.anchor.exact ? cur : next));
      else if (!document.activeElement?.closest('[data-comment-ui]')) setSel(null);
    };
    document.addEventListener('selectionchange', on);
    return () => document.removeEventListener('selectionchange', on);
  }, [root]);
  return [sel, () => setSel(null)] as const;
}
