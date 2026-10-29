import { describe, expect, it } from 'vitest';
import { bodyText, highlight, offsetsOf, rangeAt } from './anchorDom';

const mount = (html: string) => { const el = document.createElement('div'); el.innerHTML = html; document.body.append(el); return el; };

describe('anchorDom', () => {
  it('bodyText skips pre.mermaid', () => {
    const el = mount('<p>one</p><pre class="mermaid">graph TD</pre><p>two</p>');
    expect(bodyText(el)).toBe('onetwo');
  });
  it('offsetsOf and rangeAt round-trip over two elements', () => {
    const el = mount('<p>hello <b>big</b> world</p><p>next para</p>');
    const t = bodyText(el);
    const start = t.indexOf('big'), end = t.indexOf('next') + 4;
    const range = rangeAt(el, start, end);
    expect(range.toString()).toBe(t.slice(start, end));
    expect(offsetsOf(el, range)).toEqual({ start, end });
  });
  it('offsetsOf handles element boundary points', () => {
    const el = mount('<p>ab</p><p>cd</p>');
    const r = document.createRange();
    r.setStart(el, 1); r.setEnd(el, 2);
    expect(offsetsOf(el, r)).toEqual({ start: 2, end: 4 });
  });
  it('highlight wraps across an element boundary and undo restores the DOM', () => {
    const el = mount('<p>hello <b>big</b> world</p><p>next</p>');
    const before = el.innerHTML, text = bodyText(el);
    const start = text.indexOf('lo'), end = text.indexOf('rld') ;
    const undo = highlight(el, [{ id: 'a', start, end }]);
    const marks = el.querySelectorAll('mark.anchor-hl[data-thread="a"]');
    expect(marks.length).toBeGreaterThan(1);
    expect([...marks].map((m) => m.textContent).join('')).toBe(text.slice(start, end));
    expect(bodyText(el)).toBe(text);
    undo();
    expect(el.innerHTML).toBe(before);
  });
  it('highlight handles overlapping spans', () => {
    const el = mount('<p>abcdef</p>');
    const before = el.innerHTML;
    const undo = highlight(el, [{ id: 'a', start: 0, end: 4 }, { id: 'b', start: 2, end: 6 }]);
    expect(bodyText(el)).toBe('abcdef');
    undo();
    expect(el.innerHTML).toBe(before);
  });
});
