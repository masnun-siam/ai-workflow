import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { FeedEvent } from '../api/types';
import { showNotification, step } from './notifier';

const ev = (id: number): FeedEvent => ({ id, event: 'e', title: `t${id}`, body: 'b', path: '#/inbox', tag: `g${id}`, ts: '' });

describe('step', () => {
  it('first response only learns latest', () => expect(step(null, { latest: 7, events: [ev(7)] })).toEqual({ last: 7, show: [] }));
  it('shows newer events', () => {
    expect(step(7, { latest: 9, events: [ev(8), ev(9)] })).toEqual({ last: 9, show: [ev(8), ev(9)] });
  });
  it('resets on a lower latest (restart)', () => expect(step(20, { latest: 3, events: [ev(3)] })).toEqual({ last: 3, show: [] }));
});

describe('showNotification', () => {
  afterEach(() => vi.unstubAllGlobals());
  const setup = (permission: string) => {
    const show = vi.fn();
    vi.stubGlobal('Notification', { permission });
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { ready: Promise.resolve({ showNotification: show }) } });
    return show;
  };
  it('shows through the service worker when granted', async () => {
    const show = setup('granted');
    showNotification('T', { body: 'B', tag: 'g', path: '#/sessions/a' });
    await Promise.resolve(); await Promise.resolve();
    expect(show).toHaveBeenCalledWith('T', { body: 'B', tag: 'g', data: { path: '#/sessions/a' } });
  });
  it('does nothing when denied', async () => {
    const show = setup('denied');
    showNotification('T', { body: 'B', tag: 'g', path: '#/inbox' });
    await Promise.resolve(); await Promise.resolve();
    expect(show).not.toHaveBeenCalled();
  });
});

describe('sw.js notificationclick', () => {
  const run = async (wins: unknown[], path: unknown) => {
    const handlers: Record<string, (e: unknown) => void> = {};
    const openWindow = vi.fn();
    const self = {
      addEventListener: (n: string, h: (e: unknown) => void) => { handlers[n] = h; },
      clients: { matchAll: async () => wins, openWindow },
      registration: { scope: 'http://x/' },
    };
    new Function('self', readFileSync('public/sw.js', 'utf8'))(self);
    let p: Promise<unknown> = Promise.resolve();
    const close = vi.fn();
    handlers.notificationclick({ notification: { close, data: { path } }, waitUntil: (x: Promise<unknown>) => { p = x; } });
    await p;
    return { close, openWindow };
  };
  it('focuses an open window and sends it the path', async () => {
    const win = { focused: false, postMessage: vi.fn(), focus: vi.fn() };
    const { close } = await run([win], '#/sessions/abc');
    expect(close).toHaveBeenCalled();
    expect(win.postMessage).toHaveBeenCalledWith({ type: 'aiw-open', path: '#/sessions/abc' });
    expect(win.focus).toHaveBeenCalled();
  });
  it('opens a window when none is open', async () => {
    const { openWindow } = await run([], '#/sessions/abc');
    expect(openWindow).toHaveBeenCalledWith('http://x/#/sessions/abc');
  });
  it('falls back to the inbox for a foreign path', async () => {
    const { openWindow } = await run([], 'https://evil');
    expect(openWindow).toHaveBeenCalledWith('http://x/#/inbox');
  });
});
