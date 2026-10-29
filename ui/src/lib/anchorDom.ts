// DOM side of share-link anchors: the same text, offsets and highlights on every surface.
import type { Span } from './anchor';

function textNodes(root: Element): Text[] {
  const out: Text[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.parentElement?.closest('pre.mermaid,[data-no-anchor]')) out.push(n as Text);
  }
  return out;
}

export const bodyText = (root: Element): string => textNodes(root).map((n) => n.data).join('');

function pointOffset(root: Element, node: Node, offset: number): number {
  const point = document.createRange();
  point.setStart(node, offset);
  let acc = 0;
  for (const tn of textNodes(root)) {
    if (tn === node) return acc + offset;
    if (point.comparePoint(tn, 0) >= 0) break;
    acc += tn.length;
  }
  return acc;
}

export function offsetsOf(root: Element, range: Range): Span {
  return { start: pointOffset(root, range.startContainer, range.startOffset), end: pointOffset(root, range.endContainer, range.endOffset) };
}

export function rangeAt(root: Element, start: number, end: number): Range {
  const range = document.createRange();
  const nodes = textNodes(root);
  let acc = 0, startSet = false;
  for (const tn of nodes) {
    if (!startSet && start < acc + tn.length) { range.setStart(tn, start - acc); startSet = true; }
    if (startSet && end <= acc + tn.length) { range.setEnd(tn, end - acc); return range; }
    acc += tn.length;
  }
  const last = nodes[nodes.length - 1];
  if (!last) { range.setStart(root, 0); range.setEnd(root, 0); return range; }
  if (!startSet) range.setStart(last, last.length);
  range.setEnd(last, last.length);
  return range;
}

/** Wraps each span in `<mark class="anchor-hl">`, one per text node piece. Returns the undo. */
export function highlight(root: Element, spans: (Span & { id: string })[]): () => void {
  const marks: HTMLElement[] = [];
  for (const { id, start, end } of spans) {
    let acc = 0;
    for (let tn of textNodes(root)) {
      const from = Math.max(start, acc) - acc, to = Math.min(end, acc + tn.length) - acc;
      acc += tn.length;
      if (to <= from) continue;
      if (from > 0) tn = tn.splitText(from);
      if (to - from < tn.length) tn.splitText(to - from);
      const mark = document.createElement('mark');
      mark.className = 'anchor-hl';
      mark.dataset.thread = id;
      tn.replaceWith(mark);
      mark.append(tn);
      marks.push(mark);
    }
  }
  return () => {
    for (const mark of marks) mark.replaceWith(...mark.childNodes);
    root.normalize();
  };
}
