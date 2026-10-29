import { describe, expect, it } from 'vitest';
import { FUZZY_BUDGET, makeAnchor, placeAnchor, placeThreads, type Anchor } from './anchor';

const SENT = 'The reviewer opens the shared link and leaves a comment on the second paragraph of the document.';
const base = `Intro text here. ${SENT} Closing words follow.`;
const anchorOf = (text: string, quote: string) => { const s = text.indexOf(quote); return makeAnchor(text, s, s + quote.length); };
const slice = (text: string, r: { span: { start: number; end: number } | null }) => (r.span ? text.slice(r.span.start, r.span.end) : null);

describe('makeAnchor', () => {
  it('cuts 32 code points of context, fewer at the edges', () => {
    const t = 'a'.repeat(50) + 'QUOTE' + 'b'.repeat(50);
    const a = makeAnchor(t, 50, 55);
    expect(a).toEqual({ exact: 'QUOTE', prefix: 'a'.repeat(32), suffix: 'b'.repeat(32) });
    expect(makeAnchor('QUOTE tail', 0, 5)).toEqual({ exact: 'QUOTE', prefix: '', suffix: ' tail' });
  });
  it('counts context in code points, not UTF-16 units', () => {
    const t = '😀'.repeat(40) + 'Q' + '😀'.repeat(40);
    const a = makeAnchor(t, 80, 81);
    expect(Array.from(a.prefix)).toHaveLength(32);
    expect(Array.from(a.suffix)).toHaveLength(32);
  });
});

describe('placeAnchor', () => {
  it('keeps exact+context after a paragraph is added above', () => {
    const a = anchorOf(base, SENT);
    const next = `A brand new paragraph.\n\n${base}`;
    const r = placeAnchor(next, a, true);
    expect(slice(next, r)).toBe(SENT);
    expect(r.fuzzyTried).toBe(false);
  });
  it('falls back to the quote alone when it occurs once', () => {
    const a = anchorOf(base, SENT);
    const next = base.replace('Intro text here.', 'Changed.').replace('Closing words follow.', 'Other ending.');
    expect(slice(next, placeAnchor(next, a, true))).toBe(SENT);
  });
  it('does not guess a repeated quote without context, and skips fuzzy', () => {
    const a: Anchor = { exact: 'word', prefix: 'gone ', suffix: ' gone' };
    const r = placeAnchor('one word and another word', a, true);
    expect(r).toEqual({ span: null, fuzzyTried: false });
  });
  it('places a one-word edit with the fuzzy step', () => {
    const a = anchorOf(base, SENT);
    const next = base.replace('comment', 'remark');
    const r = placeAnchor(next, a, true);
    expect(r.fuzzyTried).toBe(true);
    expect(slice(next, r)).toContain('leaves a remark on the second');
  });
  it('Outdated when the sentence is deleted or mostly rewritten', () => {
    const a = anchorOf(base, SENT);
    expect(placeAnchor('Intro text here. Closing words follow.', a, true).span).toBeNull();
    const rewritten = 'Intro text here. Someone writes something entirely unrelated about budgets and timelines now. Closing words follow.';
    expect(placeAnchor(rewritten, a, true).span).toBeNull();
  });
  it('Outdated on a tie between two equally good windows', () => {
    const q = 'the quick brown fox jumps over the lazy dog today';
    const a: Anchor = { exact: q, prefix: '', suffix: '' };
    const variant = q.replace('quick', 'slow!');
    const text = `${variant}. Then, much later, ${variant}.`;
    expect(placeAnchor(text, a, true)).toEqual({ span: null, fuzzyTried: true });
  });
  it('fuzzy is tried at 300 characters and skipped at 301', () => {
    const quote = (n: number) => ('lorem ipsum dolor sit amet '.repeat(20)).slice(0, n);
    for (const [n, tried] of [[300, true], [301, false]] as const) {
      const q = quote(n);
      const text = `start ${q} end`;
      const edited = text.replace('dolor', 'dolar');
      const r = placeAnchor(edited, { exact: q, prefix: '', suffix: '' }, true);
      expect(r.fuzzyTried).toBe(tried);
      expect(r.span !== null).toBe(tried);
    }
  });
  it('counts a Bengali 1,000-character quote and emoji by code points', () => {
    const bn = 'আমি'.repeat(334).slice(0, 1000);
    const t = `x ${bn} y`;
    expect(placeAnchor(t, anchorOf(t, bn), true).span).toEqual({ start: 2, end: 2 + bn.length });
    const e = 'ok 😀😀😀 done';
    expect(slice(e, placeAnchor(e, anchorOf(e, '😀😀😀'), true))).toBe('😀😀😀');
    // 301 emoji = 301 code points but 602 UTF-16 units: over the fuzzy limit either way
    const many = '😀'.repeat(301);
    expect(placeAnchor(`a${many.slice(2)}b`, { exact: many, prefix: '', suffix: '' }, true).fuzzyTried).toBe(false);
  });
});

describe('placeThreads', () => {
  const WORDS = 'alpha river stone cloud engine pencil garden window copper maple harbor violet signal ladder orchard magnet puzzle anchor bridge candle desert falcon glacier hammer island jungle kettle lantern meadow needle oyster pepper quartz rocket saddle tunnel umbrella valley walnut yonder zephyr'.split(' ');
  // deterministic, distinct sentences so a fuzzy match has a clear best window
  const gen = (i: number) => {
    let x = i * 2654435761 + 12345; const w = () => { x = (x * 1103515245 + 12345) % 2147483648; return WORDS[x % WORDS.length]; };
    return `Item ${i}: ${w()} ${w()} ${w()} talks to the ${w()} about ${w()} and ${w()} near the ${w()} ${w()}.`;
  };
  const doc = Array.from({ length: 520 }, (_, i) => gen(i)).join(' ');
  const mk = (i: number, text = doc) => ({ id: `t${String(i).padStart(3, '0')}`, anchor: anchorOf(text, gen(i)), created_at: `2026-01-01T00:${String(i % 60).padStart(2, '0')}:00Z` });

  it('bounds a 45 KB / 500-thread pass to 50 fuzzy attempts, oldest first', () => {
    expect(doc.length).toBeGreaterThan(30000);
    const threads = Array.from({ length: 500 }, (_, i) => mk(i));
    // edit every 5th sentence by one word so it needs a fuzzy step; delete a few outright
    let next = doc;
    for (let i = 0; i < 500; i += 5) next = next.replace(gen(i), gen(i).replace('talks', 'speaks'));
    for (let i = 3; i < 500; i += 100) next = next.replace(gen(i), '');
    const res = placeThreads(next, threads);
    expect(res.fuzzyAttempts).toBeLessThanOrEqual(FUZZY_BUDGET);
    expect(res.fuzzyAttempts).toBe(FUZZY_BUDGET);
    const oldest = [...threads].sort((a, b) => (a.created_at + a.id < b.created_at + b.id ? -1 : 1));
    const needing = oldest.filter((t) => Number(t.id.slice(1)) % 5 === 0);
    expect(res.spans.get(needing[0].id)).not.toBeNull();
    expect(res.spans.get(needing[needing.length - 1].id)).toBeNull();
    expect(res.spans.get('t003')).toBeNull();
  });
  it('returns the previous result object for unchanged text and no new threads', () => {
    const threads = [mk(1), mk(2)];
    const prev = placeThreads(doc, threads);
    expect(placeThreads(doc, threads, prev)).toBe(prev);
  });
  it('places only a new thread when the text is unchanged', () => {
    const prev = placeThreads(doc, [mk(1)]);
    const res = placeThreads(doc, [mk(1), mk(2)], prev);
    expect(res).not.toBe(prev);
    expect(res.spans.get('t001')).toBe(prev.spans.get('t001'));
    expect(res.spans.get('t002')).not.toBeNull();
  });
  it('drops threads that are gone', () => {
    const prev = placeThreads(doc, [mk(1), mk(2)]);
    expect([...placeThreads(doc, [mk(2)], prev).spans.keys()]).toEqual(['t002']);
  });
  it('keeps Outdated until the text changes, then places again', () => {
    const gone = doc.replace(gen(1), '');
    const t = mk(1);
    const prev = placeThreads(gone, [t]);
    expect(prev.spans.get('t001')).toBeNull();
    expect(placeThreads(gone, [t], prev)).toBe(prev);
    const back = placeThreads(doc, [t], prev);
    expect(back.spans.get('t001')).not.toBeNull();
  });
});
