// One flow per browser is kept in localStorage so leaving the page doesn't lose it; the hash
// still carries it too, so links and Back keep working. Storage can throw (private mode).
const KEY = 'aiw.flow';

export function loadFlow(storage) {
  try {
    const f = JSON.parse(storage.getItem(KEY) || 'null');
    return f && typeof f === 'object' ? f : null;
  } catch {
    return null;
  }
}

export function saveFlow(storage, flow) {
  try { storage.setItem(KEY, JSON.stringify(flow)); } catch { /* best-effort: the hash still holds the flow */ }
  globalThis.dispatchEvent?.(new Event('aiw:flow'));
}

export function clearFlow(storage) {
  try { storage.removeItem(KEY); } catch { /* nothing saved to clear */ }
  globalThis.dispatchEvent?.(new Event('aiw:flow'));
}
