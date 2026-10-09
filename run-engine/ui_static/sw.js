// Installability only: nothing is cached, so the UI is always live. When the Mac is unreachable
// (asleep, off the tailnet) a page load gets a plain explanation instead of the browser's error.
const OFFLINE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>aiw</title><body style="margin:0;min-height:100dvh;display:grid;place-items:center;background:#0e1116;color:#c9d1db;font:15px/1.5 system-ui,sans-serif;padding:16px">
<div style="max-width:320px"><p style="color:#e6e9ee;font-weight:600;margin:0 0 6px">Can't reach aiw ui</p>
<p style="margin:0 0 16px">Check that the Mac is awake, <code>aiw ui</code> is running, and this phone is on Tailscale.</p>
<button onclick="location.reload()" style="min-height:44px;padding:0 16px;border:0;border-radius:6px;background:#5eead4;color:#06241f;font-weight:600">Try again</button></div>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
