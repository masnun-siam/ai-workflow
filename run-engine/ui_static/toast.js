// Fire-and-forget confirmation toast. Lives outside the Preact tree so it survives route changes.
// No-ops without a real document (tests, SSR-like imports).
export function toast(message, kind = 'ok') {
  const doc = globalThis.document;
  if (!doc || !doc.body || typeof doc.createElement !== 'function') return;
  let host = doc.getElementById('toasts');
  if (!host) {
    host = doc.createElement('div');
    host.id = 'toasts';
    host.setAttribute('role', 'status');
    host.setAttribute('aria-live', 'polite');
    doc.body.appendChild(host);
  }
  const el = doc.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}
