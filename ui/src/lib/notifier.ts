import type { FeedEvent, NotificationFeed } from '../api/types';

/** One poll result: what to show and the id to remember. A first response, or a lower `latest` (server restart), shows nothing. */
export function step(last: number | null, res: NotificationFeed): { last: number; show: FeedEvent[] } {
  if (last === null || res.latest < last) return { last: res.latest, show: [] };
  return { last: res.latest, show: res.events.filter((e) => e.id > last) };
}

/** Show a system notification through the service worker; the same tag replaces, so tabs show one. A click opens `path`. */
export function showNotification(title: string, opts: { body: string; tag: string; path: string }) {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted' || !('serviceWorker' in navigator)) return;
  navigator.serviceWorker.ready
    .then((r) => r.showNotification(title, { body: opts.body, tag: opts.tag, data: { path: opts.path } }))
    .catch((err) => console.warn('notification failed', err));
}
