import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { rangeAt } from '../lib/anchorDom';
import type { PublicThread } from './types';
import { SharePage } from './SharePage';

vi.mock('../lib/prdRender', async (orig) => ({ ...(await orig<object>()), renderDiagrams: vi.fn() }));

const TEXT = '# My PRD\n\n## Goal\n\nHello brave world. Second sentence here.\n\n```mermaid\ngraph TD; A-->B\n```\n';
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }));
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const poll = () => act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
const thread = (o: Partial<PublicThread> & { id: string }): PublicThread => ({ anchor: { exact: 'Hello brave', prefix: '', suffix: '' }, resolved: false, comments: [{ id: `${o.id}c`, author: 'Ann', by_owner: false, body: 'looks odd', at: '2026-01-01T00:00:00Z' }], ...o });

let threads: PublicThread[];
let prdText: string;
let post: (url: string, body: any) => Promise<Response>;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  window.history.pushState({}, '', '/s/tok/');
  threads = []; prdText = TEXT;
  post = () => json({}, 500);
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === 'POST') return post(url, JSON.parse(String(init.body)));
    if (url.endsWith('/api/threads')) return json(threads);
    return json({ title: 'My PRD', status: 'Draft', text: prdText, updated_at: '2026-01-02T03:04:05Z' });
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); window.getSelection()?.removeAllRanges(); vi.useRealTimers(); vi.unstubAllGlobals(); });

const prose = () => document.querySelector('.prose') as HTMLElement;
const textNode = (el: Element) => el.firstChild as Text;
function select(a: Node, ao: number, b: Node, bo: number) {
  const r = document.createRange(); r.setStart(a, ao); r.setEnd(b, bo);
  const s = window.getSelection()!; s.removeAllRanges(); s.addRange(r);
  act(() => { document.dispatchEvent(new Event('selectionchange')); });
}
// Offsets inside the first paragraph; the body text starts with the heading "Goal" and a newline.
const selectInPara = (from: number, to: number) => {
  const r = rangeAt(prose(), 5 + from, 5 + to);
  select(r.startContainer, r.startOffset, r.endContainer, r.endOffset);
};
const typeIn = (label: string, v: string) => fireEvent.change(screen.getByLabelText(label), { target: { value: v } });
const submit = async (name: string) => { fireEvent.click(screen.getByRole('button', { name })); await flush(); };
const posts = () => fetchMock.mock.calls.filter(([, i]) => i?.method === 'POST');

async function open() { render(<SharePage />); await flush(); }

describe('comment button', () => {
  it('is offered for a sentence, placed after the prose container', async () => {
    await open();
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    selectInPara(0, 11);
    const btn = screen.getByRole('button', { name: 'Comment' });
    expect(btn.tagName).toBe('BUTTON');
    expect(prose().compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('is not offered for collapsed, whitespace-only, title, diagram or rail selections', async () => {
    threads = [thread({ id: 't1' })];
    await open();
    selectInPara(3, 3);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    selectInPara(11, 12); // a single space
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    select(textNode(document.querySelector('h1')!), 0, textNode(document.querySelector('h1')!), 4);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    const pre = prose().querySelector('pre.mermaid')!;
    select(textNode(pre), 0, textNode(pre), 5);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
    const rail = textNode(prose().querySelector('.thread-slot .thread-c p.plain')!);
    select(rail, 0, rail, 3);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
  });

  async function longBody(n: number) {
    prdText = `# T\n\n${'a'.repeat(n + 5)}\n`;
    await open();
    selectInPara(0, n);
  }
  it('offers 1,000 characters and disables 1,001 with the message and no post', async () => {
    await longBody(1000);
    expect(screen.getByRole('button', { name: 'Comment' }).getAttribute('aria-disabled')).toBeNull();
    cleanup(); await longBody(1001);
    const btn = screen.getByRole('button', { name: 'Select less text (max 1,000 characters)' });
    expect(btn.getAttribute('aria-disabled')).toBe('true');
    fireEvent.click(btn);
    expect(screen.queryByLabelText('Comment')).toBeNull();
    expect(posts()).toHaveLength(0);
  });

  it('offers a 1,000-character Bengali selection', async () => {
    prdText = `# T\n\n${'বাংলা'.repeat(220)}\n`;
    await open();
    const t = textNode(prose().querySelector('p')!);
    select(t, 0, t, Array.from(t.data).slice(0, 1000).join('').length);
    expect(screen.getByRole('button', { name: 'Comment' }).getAttribute('aria-disabled')).toBeNull();
  });
});

describe('posting', () => {
  const start = async () => { await open(); selectInPara(0, 11); fireEvent.click(screen.getByRole('button', { name: 'Comment' })); };

  it('asks for the name once, posts the anchor, shows and focuses the new thread', async () => {
    post = (_url, body) => json({ id: 'n1', anchor: body.anchor, resolved: false, comments: [{ id: 'c', author: body.name, by_owner: false, body: body.body, at: '2026-01-03T00:00:00Z' }] }, 201);
    await start();
    typeIn('Your name', '  Bo  '); typeIn('Comment', ' first ');
    await submit('Post');
    const [url, init] = posts()[0];
    expect(url).toBe('/s/tok/api/threads');
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ name: 'Bo', body: 'first', anchor: { exact: 'Hello brave', prefix: 'Goal\n' } });
    expect(body.anchor.prefix.length).toBeLessThanOrEqual(32);
    expect(localStorage.getItem('aiw-share-name')).toBe('Bo');
    await flush();
    const card = document.querySelector('[data-thread-card="n1"]') as HTMLElement;
    expect(card).toBeTruthy();
    expect(document.activeElement).toBe(card);
    expect(prose().querySelector('mark.anchor-hl')?.textContent).toBe('Hello brave');
    selectInPara(0, 11);
    // the second form has no name field (queried before opening, by label)
    expect(screen.queryByLabelText('Your name')).toBeNull();
  });

  it('disables Submit while a post is in flight', async () => {
    let done!: (r: Response) => void;
    post = () => new Promise<Response>((r) => { done = r; });
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'x');
    await submit('Post');
    expect((screen.getByRole('button', { name: 'Post' }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { done(new Response('{}', { status: 500 })); });
  });

  it.each([
    [400, 'not valid'], [413, 'too large'], [429, 'try again in a minute'], [409, 'Share is full'], [500, 'Could not post, your draft is kept'],
  ])('a %i keeps the draft and shows %s', async (status, msg) => {
    post = () => json({}, status);
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'keep me');
    await submit('Post');
    expect((screen.getByRole('alert')).textContent).toContain(msg);
    expect((screen.getByLabelText('Comment') as HTMLTextAreaElement).value).toBe('keep me');
    await poll();
    expect((screen.getByLabelText('Comment') as HTMLTextAreaElement).value).toBe('keep me');
  });

  it('a network failure keeps the draft', async () => {
    post = () => Promise.reject(new TypeError('x'));
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'keep me');
    await submit('Post');
    expect(screen.getByRole('alert').textContent).toContain('Could not post, your draft is kept');
    expect((screen.getByLabelText('Comment') as HTMLTextAreaElement).value).toBe('keep me');
  });

  it('a 409 disables commenting and says Share is full', async () => {
    post = () => json({}, 409);
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'x');
    await submit('Post');
    expect(screen.getByRole('status').textContent).toBe('Share is full');
    selectInPara(0, 5);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
  });

  it('a 404 shows the inactive view with the draft in a read-only textarea', async () => {
    post = () => json({}, 404);
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'my draft');
    await submit('Post');
    expect(screen.getByText('This link is no longer active')).toBeTruthy();
    const ta = screen.getByLabelText('Your unsent comment') as HTMLTextAreaElement;
    expect(ta.value).toBe('my draft');
    expect(ta.readOnly).toBe(true);
  });

  it('keeps an open draft when another selection is commented', async () => {
    await start();
    typeIn('Your name', 'Bo'); typeIn('Comment', 'draft');
    selectInPara(13, 20);
    fireEvent.click(screen.getByRole('button', { name: 'Comment' }));
    expect((screen.getByLabelText('Comment') as HTMLTextAreaElement).value).toBe('draft');
    expect(document.querySelector('blockquote')?.textContent).toBe('Hello brave');
  });
});

describe('threads', () => {
  it('places a thread beside its sentence with a highlight, and lists an unmatched one as Outdated', async () => {
    threads = [thread({ id: 't1' }), thread({ id: 't2', anchor: { exact: 'long gone text', prefix: '', suffix: '' } })];
    await open();
    expect(prose().querySelector('mark.anchor-hl')?.textContent).toBe('Hello brave');
    const slot = prose().querySelector('.thread-slot')!;
    expect(slot.previousElementSibling?.tagName).toBe('P');
    expect(slot.textContent).toContain('looks odd');
    const outdated = screen.getByRole('region', { name: 'Outdated' });
    expect(within(outdated).getByText('long gone text')).toBeTruthy();
    expect(within(outdated).getByText('looks odd')).toBeTruthy();
  });

  it('collapses a resolved thread, expands on click and then shows the reply field', async () => {
    threads = [thread({ id: 't1', resolved: true })];
    await open();
    expect(screen.queryByLabelText('Reply')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Ann looks odd/ }));
    expect(screen.getByLabelText('Reply')).toBeTruthy();
  });

  it('labels author replies and posts replies to the comments route', async () => {
    threads = [thread({ id: 't1', comments: [thread({ id: 't1' }).comments[0], { id: 'o', author: 'Sam', by_owner: true, body: 'fixed', at: '2026-01-02T00:00:00Z' }] })];
    post = (_u, b) => json({ id: 'r', author: b.name, by_owner: false, body: b.body, at: '2026-01-04T00:00:00Z' }, 201);
    localStorage.setItem('aiw-share-name', 'Cy');
    await open();
    expect(screen.getByText('Author')).toBeTruthy();
    typeIn('Reply', 'thanks');
    await submit('Reply');
    const [url, init] = posts()[0];
    expect(url).toBe('/s/tok/api/threads/t1/comments');
    expect(JSON.parse(init.body)).toEqual({ name: 'Cy', body: 'thanks' });
    expect(screen.getByText('thanks')).toBeTruthy();
  });

  it('renders reviewer text literally', async () => {
    const evil = '<img src=x onerror=alert(1)>';
    threads = [thread({ id: 't1', anchor: { exact: evil, prefix: '', suffix: '' }, comments: [{ id: 'c', author: evil, by_owner: false, body: evil, at: '2026-01-01T00:00:00Z' }] })];
    await open();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getAllByText(evil).length).toBeGreaterThan(0);
  });

  it('500 reviewer comments (author replies excluded) disable commenting', async () => {
    const mk = (n: number, by_owner: boolean) => Array.from({ length: n }, (_, i) => ({ id: `${by_owner}${i}`, author: 'A', by_owner, body: 'x', at: '2026-01-01T00:00:00Z' }));
    threads = [thread({ id: 't1', comments: [...mk(499, false), ...mk(5, true)] })];
    await open();
    selectInPara(13, 20);
    expect(screen.getByRole('button', { name: 'Comment' })).toBeTruthy();
    expect(screen.queryByText('Share is full')).toBeNull();
    threads = [thread({ id: 't1', comments: mk(500, false) })];
    await poll();
    expect(screen.getByText('Share is full')).toBeTruthy();
    selectInPara(0, 5);
    expect(screen.queryByRole('button', { name: 'Comment' })).toBeNull();
  });

  it('shows the empty state', async () => {
    await open();
    expect(screen.getByText('No comments yet. Select text to comment')).toBeTruthy();
  });
});
