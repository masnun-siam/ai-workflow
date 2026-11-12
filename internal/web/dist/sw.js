// setu service worker: web push only (no offline caching; the UI is served by the local binary).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "setu", {
    body: d.body || "",
    tag: d.tag || d.event || undefined,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { path: d.path || "#/inbox" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const path = (e.notification.data && e.notification.data.path) || "#/inbox";
  e.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if ("focus" in c) {
        await c.focus();
        if ("navigate" in c) { try { await c.navigate("/" + path); } catch { /* cross-origin guard */ } }
        return;
      }
    }
    await self.clients.openWindow("/" + path);
  })());
});
