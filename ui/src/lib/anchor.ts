// Anchors for share-link comments: a quote plus context, placed in the PRD's rendered text.
// Offsets are UTF-16 units (what the DOM uses); limits are counted in code points.

export interface Anchor { exact: string; prefix: string; suffix: string }
export interface Span { start: number; end: number }
export interface Placements { text: string; spans: Map<string, Span | null>; fuzzyAttempts: number }
export interface PlaceableThread { id: string; anchor: Anchor; created_at: string }

export const MAX_QUOTE = 1000;
export const CONTEXT = 32;
export const FUZZY_MAX_QUOTE = 300;
export const FUZZY_BUDGET = 50;
const MIN_SIMILARITY = 0.8;
const MIN_MARGIN = 0.05;

export const countPoints = (s: string): number => Array.from(s).length;

export function makeAnchor(text: string, start: number, end: number): Anchor {
  return {
    exact: text.slice(start, end),
    prefix: Array.from(text.slice(0, start)).slice(-CONTEXT).join(''),
    suffix: Array.from(text.slice(end)).slice(0, CONTEXT).join(''),
  };
}

function occurrences(text: string, needle: string): number[] {
  const at: number[] = [];
  for (let i = text.indexOf(needle); i !== -1; i = text.indexOf(needle, i + 1)) at.push(i);
  return at;
}

// Sellers approximate substring match: for each end position, the best edit distance and where
// that window starts. Returns the best window and the best one that does not overlap it.
function bestWindows(text: string, quote: string): { best: Span & { sim: number }; next: number } {
  const n = text.length, m = quote.length;
  let dPrev = new Int32Array(m + 1), dCur = new Int32Array(m + 1);
  let sPrev = new Int32Array(m + 1), sCur = new Int32Array(m + 1);
  for (let j = 0; j <= m; j++) dPrev[j] = j;
  const cands: { start: number; end: number; sim: number }[] = [];
  for (let i = 1; i <= n; i++) {
    dCur[0] = 0; sCur[0] = i;
    const c = text.charCodeAt(i - 1);
    for (let j = 1; j <= m; j++) {
      let d = dPrev[j - 1] + (quote.charCodeAt(j - 1) === c ? 0 : 1), s = sPrev[j - 1];
      if (dPrev[j] + 1 < d) { d = dPrev[j] + 1; s = sPrev[j]; }
      if (dCur[j - 1] + 1 < d) { d = dCur[j - 1] + 1; s = sCur[j - 1]; }
      dCur[j] = d; sCur[j] = s;
    }
    cands.push({ start: sCur[m], end: i, sim: 1 - dCur[m] / Math.max(i - sCur[m], m) });
    [dPrev, dCur] = [dCur, dPrev]; [sPrev, sCur] = [sCur, sPrev];
  }
  let best = cands[0];
  for (const c of cands) if (c.sim > best.sim) best = c;
  let next = 0;
  for (const c of cands) if ((c.end <= best.start || c.start >= best.end) && c.sim > next) next = c.sim;
  return { best, next };
}

function fuzzyPlace(text: string, quote: string): Span | null {
  if (!text) return null;
  const { best, next } = bestWindows(text, quote);
  if (best.sim < MIN_SIMILARITY || best.sim - next < MIN_MARGIN) return null;
  return { start: best.start, end: best.end };
}

/** Places one anchor. `fuzzy` false skips the third step. A null span means Outdated. */
export function placeAnchor(text: string, a: Anchor, fuzzy: boolean): { span: Span | null; fuzzyTried: boolean } {
  const at = (start: number): { span: Span; fuzzyTried: boolean } => ({ span: { start, end: start + a.exact.length }, fuzzyTried: false });
  const outdated = { span: null, fuzzyTried: false };
  if (!a.exact) return outdated;
  const withContext = occurrences(text, a.prefix + a.exact + a.suffix);
  if (withContext.length === 1) return at(withContext[0] + a.prefix.length);
  if (withContext.length > 1) return outdated;
  const alone = occurrences(text, a.exact);
  if (alone.length === 1) return at(alone[0]);
  if (alone.length > 1) return outdated;
  if (!fuzzy || countPoints(a.exact) > FUZZY_MAX_QUOTE) return outdated;
  return { span: fuzzyPlace(text, a.exact), fuzzyTried: true };
}

/**
 * One placement pass. Threads already placed in `prev` keep their span while the text is unchanged;
 * everything else is placed, oldest first, with at most FUZZY_BUDGET fuzzy attempts.
 */
export function placeThreads(text: string, threads: PlaceableThread[], prev?: Placements): Placements {
  const keep = prev?.text === text ? prev.spans : undefined;
  const todo = threads.filter((t) => !keep?.has(t.id));
  if (prev && keep && !todo.length && keep.size === threads.length) return prev;
  const spans = new Map<string, Span | null>();
  for (const t of threads) if (keep?.has(t.id)) spans.set(t.id, keep.get(t.id) ?? null);
  let fuzzyAttempts = 0;
  const oldestFirst = [...todo].sort((x, y) => (x.created_at < y.created_at ? -1 : x.created_at > y.created_at ? 1 : x.id < y.id ? -1 : x.id > y.id ? 1 : 0));
  for (const t of oldestFirst) {
    const { span, fuzzyTried } = placeAnchor(text, t.anchor, fuzzyAttempts < FUZZY_BUDGET);
    if (fuzzyTried) fuzzyAttempts++;
    spans.set(t.id, span);
  }
  return { text, spans, fuzzyAttempts };
}
