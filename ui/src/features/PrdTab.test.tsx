import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const URL_ = 'https://x.ts.net/s/tok';
const calls: { method: string; path: string; body: any }[] = [];
const summary = (o: Record<string, unknown> = {}) => ({ id: 's1', repo: 'o/r', path: 'docs/prds/f1.md', title: 'F', state: 'live', url: URL_, comments: 3, unread: 0, reachable: true, end_reason: null, ...o });
const detail = (approvals: { id: string; name: string; at: string }[], o: Record<string, unknown> = {}) => ({ ...summary(o), created_at: '', ended_at: null, last_seen_at: null, prd_updated_at: null, unsent: 0, threads: [], approvals, ...o });
const ap = (k: number) => ({ id: `a${k}`, name: `Rev${k}`, at: '' });

function mock(o: { status?: string; shares?: unknown[]; detail?: unknown; post?: () => Promise<Response>; prd?: string; sessions?: () => unknown[]; prdText?: () => string; send?: (body: any) => Promise<Response> } = {}) {
  calls.length = 0;
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }], can_browse: false, scan_roots: [] },
    '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }, gh: { ok: true } },
    '/api/inbox': { items: [], afk: {}, gh: { ok: true } },
    '/api/planning': { repo: 'o/r', stale: false, fetched_at: 1, prds: [{ slug: 'f1', title: 'Feature one', status: o.status ?? 'In review', path: 'docs/prds/f1.md', abs_path: '/x/docs/prds/f1.md', column: 'review', pr: null, epic: null, issues: 0, refined: 0, unrefined: [], children: [], panel: null }] },
    '/api/delivery': { repo: 'o/r', stale: false, fetched_at: 1, cap: 2, running: 0, auto_grind: false, lanes: [] },
    '/api/prd': { text: o.prd ?? '# F\n\n## A\nbody', sha: 'x', branch: 'main' },
  };
  const live = () => {
    if (o.sessions) routes['/api/sessions'] = { ...(routes['/api/sessions'] as object), sessions: o.sessions() };
    if (o.prdText) routes['/api/prd'] = { text: o.prdText(), sha: 'x', branch: 'main' };
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const [path] = String(url).split('?');
    const method = init?.method ?? 'GET';
    live();
    if (method !== 'GET') calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === '/api/shares' && method === 'POST') return o.post ? o.post() : json(summary(), 201);
    if (path === '/api/shares/s1/send' && o.send) return o.send(calls[calls.length - 1].body);
    if (path === '/api/shares') return json(o.shares ?? []);
    if (path === '/api/shares/s1') return method === 'GET' ? json(o.detail ?? detail([])) : json(summary({ state: 'ended', url: null }));
    if (method !== 'GET') return json({});
    return path in routes ? json(routes[path]) : json({ items: [] });
  }));
}
const posts = () => calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/seen')); // the open tab marks the share seen on its own
async function open(o: Parameters<typeof mock>[0] = {}) {
  mock(o);
  window.location.hash = '#/features/f1/prd?repo=o/r';
  render(<App />);
  return screen.findByRole('button', { name: /^Share|Sharing/ });
}
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Share button', () => {
  for (const status of ['Approved', 'Done']) {
    it(`is disabled with the reason for ${status}`, async () => {
      const b = await open({ status });
      expect((b as HTMLButtonElement).disabled).toBe(true);
      expect(b.getAttribute('title')).toBe('Only Draft or In review PRDs can be shared');
      expect(posts()).toHaveLength(0);
    });
  }

  it('warns, sends nothing on Cancel, creates on Confirm, then shows the link', async () => {
    const u = userEvent.setup();
    const b = await open({ shares: [] });
    await u.click(b);
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain('The PRD text is public as written, including its header and any paths');
    await u.click(within(dlg).getByRole('button', { name: 'Cancel' }));
    expect(posts()).toHaveLength(0);
    await u.click(b);
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
    await waitFor(() => expect(posts()).toEqual([{ method: 'POST', path: '/api/shares', body: { repo: 'o/r', path: 'docs/prds/f1.md', confirm: true } }]));
  });

  it('shows the live share: link, comments, end rule, reachability, Copy', async () => {
    const u = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const b = await open({ shares: [summary({ reachable: false })], detail: detail([ap(1)], { reachable: false }) });
    await u.click(b);
    expect(((await screen.findByLabelText('Share link')) as HTMLInputElement).value).toBe(URL_);
    expect(screen.getByText('3 comments')).toBeTruthy();
    expect(await screen.findByText('1 approval')).toBeTruthy();
    expect(screen.getByText('Ends when the PRD leaves Draft or In review')).toBeTruthy();
    expect(screen.getByText(/Not reachable right now/)).toBeTruthy();
    await u.click(screen.getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledWith(URL_);
    expect(posts()).toHaveLength(0);
  });

  it('shows Sharing… and sends one POST for a double click', async () => {
    const u = userEvent.setup();
    let release: (r: Response) => void = () => {};
    const b = await open({ post: () => new Promise<Response>((r) => { release = r; }) });
    await u.click(b);
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
    const pending = await screen.findByRole('button', { name: 'Sharing…' });
    expect((pending as HTMLButtonElement).disabled).toBe(true);
    await u.dblClick(pending);
    expect(posts()).toHaveLength(1);
    release(new Response(JSON.stringify(summary()), { status: 201, headers: { 'Content-Type': 'application/json' } }));
  });

  for (const [status, msg] of [[503, 'Tailscale is not running: stopped'], [409, 'PRD is not Draft or In review']] as const) {
    it(`shows a ${status} refusal inline, with no link`, async () => {
      const u = userEvent.setup();
      const b = await open({ post: () => json({ error: msg }, status) });
      await u.click(b);
      await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Share' }));
      expect((await screen.findByText(msg)).getAttribute('role')).toBe('alert');
      expect(screen.queryByLabelText('Share link')).toBeNull();
    });
  }
});

describe('Stop, Remove and re-share', () => {
  for (const [n, text] of [
    [0, 'Reviewers lose access. Sharing again makes a new link.'],
    [1, 'Reviewers lose access. Sharing again makes a new link and clears the 1 approval.'],
    [2, 'Reviewers lose access. Sharing again makes a new link and clears the 2 approvals.'],
  ] as const) {
    it(`Stop asks the exact text for ${n} approvals, then deletes`, async () => {
      const u = userEvent.setup();
      const b = await open({ shares: [summary()], detail: detail([1, 2].slice(0, n).map(ap)) });
      await u.click(b);
      if (n) await screen.findByText(n === 1 ? '1 approval' : '2 approvals');
      await u.click(await screen.findByRole('button', { name: 'Stop' }));
      const dlg = await screen.findByRole('alertdialog');
      expect(dlg.textContent).toContain(text);
      await u.click(within(dlg).getByRole('button', { name: 'Stop' }));
      await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/shares/s1']));
    });
  }

  for (const [n, clause] of [[2, 'Sharing again clears the 2 approvals.'], [1, 'Sharing again clears the 1 approval.'], [0, '']] as const) {
    it(`Share on an ended record with ${n} approvals`, async () => {
      const u = userEvent.setup();
      const ended = { state: 'ended', url: null, end_reason: 'stopped' };
      const b = await open({ shares: [summary(ended)], detail: detail([1, 2].slice(0, n).map(ap), ended) });
      await waitFor(() => expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).startsWith('/api/shares/s1'))).toBe(true));
      await new Promise((r) => setTimeout(r, 50));
      await u.click(b);
      const dlg = await screen.findByRole('alertdialog');
      expect(dlg.textContent).toContain('any paths.');
      if (clause) expect(dlg.textContent).toContain(clause);
      else expect(dlg.textContent).not.toContain('clears');
      expect(posts()).toHaveLength(0);
    });
  }

  it('Remove asks with the name, then deletes the approval', async () => {
    const u = userEvent.setup();
    const b = await open({ shares: [summary()], detail: detail([ap(1)]) });
    await u.click(b);
    await u.click(await screen.findByRole('button', { name: "Remove Rev1's approval" }));
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain("Remove Rev1's approval? This cannot be undone.");
    await u.click(within(dlg).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/shares/s1/approvals/a1']));
  });
});

const PRD = '# F\n\n## A\nThe first sentence is here. The second sentence is there. Third one stays.';
const anc = (exact: string) => ({ exact, prefix: '', suffix: '' });
const cm = (id: string, o: Record<string, unknown> = {}) => ({ id, author: 'Rae', by_owner: false, body: `body ${id}`, at: '2026-01-02T00:00:00Z', ...o });
const th = (id: string, exact: string, o: Record<string, unknown> = {}) => ({ id, anchor: anc(exact), created_at: `2026-01-01T00:00:0${id.slice(1)}Z`, resolved: false, sent_at: null, comments: [cm(`c${id}`)], ...o });
const rail = (threads: unknown[], o: Record<string, unknown> = {}) => ({ prd: PRD, shares: [summary(o)], detail: detail([], { threads, ...o }) });
const method = (m: string) => calls.filter((c) => c.method === m);
async function openRail(o: Parameters<typeof mock>[0]) {
  await open(o);
  return screen.findByRole('region', { name: 'Comments' });
}

describe('Thread rail', () => {
  it('lists open threads in text order, resolved collapsed, Outdated with its quote; highlights the text', async () => {
    const u = userEvent.setup();
    const r = await openRail(rail([
      th('t1', 'Third one stays'), th('t2', 'The first sentence is here'),
      th('t3', 'The second sentence is there', { resolved: true }), th('t4', 'gone words'),
    ]));
    const cards = Array.from(r.querySelectorAll('li.thread')).map((l) => l.id);
    expect(cards).toEqual(['thread-t2', 'thread-t1', 'thread-t3', 'thread-t4']);
    expect(within(r).getByText('Outdated')).toBeTruthy();
    expect(r.querySelector('#thread-t4')!.textContent).toContain('gone words');
    const marks = Array.from(document.querySelectorAll('mark.anchor-hl')).map((m) => (m as HTMLElement).dataset.thread);
    expect(marks).toEqual(['t2', 't3', 't1']);
    expect(document.querySelector('.prose')!.textContent).toContain('The first sentence is here. The second sentence is there. Third one stays.');
    const head = within(r).getByRole('button', { name: /^Resolved/ });
    expect(head.getAttribute('aria-expanded')).toBe('false');
    expect(within(r.querySelector('#thread-t3') as HTMLElement).queryByLabelText('Reply')).toBeNull();
    head.focus();
    await u.keyboard('{Enter}');
    expect(head.getAttribute('aria-expanded')).toBe('true');
    expect(within(r.querySelector('#thread-t3') as HTMLElement).getByLabelText('Reply')).toBeTruthy();
  });

  it('labels the author from by_owner, shows hostile text literally, marks New from the opening baseline', async () => {
    const hostile = '<img src=x onerror=alert(1)>';
    const r = await openRail(rail([
      th('t1', 'Third one stays', { comments: [cm('a', { author: 'Rae', body: hostile }), cm('b', { author: 'Sam', by_owner: true, at: '2026-01-05T00:00:00Z' })] }),
      th('t2', 'The first sentence is here', { comments: [cm('c', { by_owner: true, at: '2026-01-05T00:00:00Z' })] }),
      th('t3', 'The second sentence is there', { comments: [cm('d', { at: '2026-01-01T00:00:00Z' })] }),
    ], { last_seen_at: '2026-01-01T12:00:00Z' }));
    expect(within(r).getByText(hostile)).toBeTruthy();
    expect(r.querySelector('img')).toBeNull();
    expect(within(r).getAllByText('Author')).toHaveLength(2);
    expect(within(r.querySelector('#thread-t1') as HTMLElement).getByText('Sam')).toBeTruthy();
    const isNew = (id: string) => !!within(r.querySelector(`#thread-${id}`) as HTMLElement).queryByText('New');
    expect([isNew('t1'), isNew('t2'), isNew('t3')]).toEqual([true, false, false]);
    await waitFor(() => expect(calls.map((c) => c.path)).toContain('/api/shares/s1/seen'));
  });

  it('replies, resolves and reopens', async () => {
    const u = userEvent.setup();
    const r = await openRail(rail([th('t1', 'Third one stays'), th('t2', 'The first sentence is here', { resolved: true })]));
    const card = r.querySelector('#thread-t1') as HTMLElement;
    const send = within(card).getByRole('button', { name: 'Reply' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    await u.type(within(card).getByLabelText('Reply'), '  thanks  ');
    await u.click(send);
    await u.click(within(card).getByRole('button', { name: 'Resolve' }));
    await u.click(within(r).getByRole('button', { name: /^Resolved/ }));
    await u.click(within(r.querySelector('#thread-t2') as HTMLElement).getByRole('button', { name: 'Reopen' }));
    await waitFor(() => expect(calls.filter((c) => c.path !== '/api/shares/s1/seen').map((c) => [c.method, c.path, c.body])).toEqual([
      ['POST', '/api/shares/s1/threads/t1/comments', { body: 'thanks' }],
      ['PATCH', '/api/shares/s1/threads/t1', { resolved: true }],
      ['PATCH', '/api/shares/s1/threads/t2', { resolved: false }],
    ]));
  });

  it('confirms comment and thread deletes with the exact text; cancel sends nothing', async () => {
    const u = userEvent.setup();
    const r = await openRail(rail([
      th('t1', 'Third one stays', { comments: [cm('a'), cm('b', { author: 'Sam' })] }),
      th('t2', 'The first sentence is here'),
    ]));
    const del = async (name: string, text: string, ok: boolean) => {
      await u.click(within(r).getByRole('button', { name }));
      const dlg = await screen.findByRole('alertdialog');
      expect(dlg.textContent).toContain(text);
      await u.click(within(dlg).getByRole('button', { name: ok ? 'Delete' : 'Cancel' }));
    };
    await del('Delete comment by Sam', 'Delete this comment? Reviewers will no longer see it. This cannot be undone.', false);
    expect(method('DELETE')).toHaveLength(0);
    await del('Delete comment by Sam', 'Delete this comment?', true);
    const t1 = r.querySelector('#thread-t1') as HTMLElement;
    await u.click(within(t1).getByRole('button', { name: 'Delete thread' }));
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain('Delete this thread and its 2 comments? This cannot be undone.');
    await u.click(within(dlg).getByRole('button', { name: 'Delete' }));
    // single-comment thread: the comment's delete uses the thread text and route
    await u.click(within(r.querySelector('#thread-t2') as HTMLElement).getByRole('button', { name: 'Delete comment by Rae' }));
    const one = await screen.findByRole('alertdialog');
    expect(one.textContent).toContain('Delete this thread and its 1 comment?');
    await u.click(within(one).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(method('DELETE').map((c) => c.path)).toEqual([
      '/api/shares/s1/threads/t1/comments/b', '/api/shares/s1/threads/t1', '/api/shares/s1/threads/t2',
    ]));
  });

  it('ended share: Delete share record with the thread count; live share and empty ended share do not', async () => {
    const u = userEvent.setup();
    const ended = { state: 'ended', url: null, end_reason: 'stopped' };
    const r = await openRail(rail([th('t1', 'Third one stays'), th('t2', 'The first sentence is here')], ended));
    await u.click(within(r).getByRole('button', { name: 'Delete share record' }));
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain('Delete this share with its 2 threads and approvals? This cannot be undone.');
    await u.click(within(dlg).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(method('DELETE').map((c) => c.path)).toEqual(['/api/shares/s1/record']));
  });

  it('live share has no Delete share record and shows No comments yet; empty ended share shows no rail', async () => {
    const r = await openRail(rail([]));
    expect(within(r).getByText('No comments yet')).toBeTruthy();
    expect(within(r).queryByRole('button', { name: 'Delete share record' })).toBeNull();
    cleanup();
    const ended = { state: 'ended', url: null, end_reason: 'stopped' };
    await open(rail([], ended));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some((c) => String(c[0]).startsWith('/api/shares/s1'))).toBe(true));
    await new Promise((res) => setTimeout(res, 50));
    expect(screen.queryByRole('region', { name: 'Comments' })).toBeNull();
  });
});

describe('Send open comments', () => {
  const prev = (o: Record<string, unknown> = {}) => ({ prompt: 'PROMPT <b>x</b>', threads: 2, remaining: 0, dropped: 0, trimmed: [], busy: { sessions: [], panel: null }, ...o });
  const sent = (o: Record<string, unknown> = {}) => ({ session_id: 'sess1', threads: 2, remaining: 0, dropped: 0, ...o });
  const go = async (send: (b: any) => Promise<Response>, unsent = 2, o: Record<string, unknown> = {}) => {
    const r = await openRail({ ...rail([th('t1', 'Third one stays'), th('t4', 'gone words')], { unsent, ...o }), send });
    return { r, btn: within(r).getByRole('button', { name: /^Send open comments/ }) as HTMLButtonElement };
  };

  it('shows unsent, is disabled at 0', async () => {
    const { btn } = await go(() => json(prev()), 0);
    expect(btn.textContent).toBe('Send open comments (0)');
    expect(btn.disabled).toBe(true);
  });

  it('previews with outdated ids and dropped notice; Cancel sends nothing more; confirm links the session', async () => {
    const u = userEvent.setup();
    let n = 0;
    const { r, btn } = await go((b) => (b.confirm ? json(sent({ remaining: 2, dropped: 3 }), 201) : (n++, json(prev({ dropped: 3 })))));
    expect(btn.textContent).toBe('Send open comments (2)');
    await u.click(btn);
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain("3 older comments on this thread won't be sent");
    expect(within(dlg).getByText('PROMPT <b>x</b>')).toBeTruthy();
    await u.click(within(dlg).getByRole('button', { name: 'Cancel' }));
    expect(posts()).toEqual([{ method: 'POST', path: '/api/shares/s1/send', body: { outdated: ['t4'] } }]);
    await u.click(btn);
    await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Send' }));
    const st = await within(r).findByRole('status');
    expect(posts().at(-1)!.body).toEqual({ confirm: true, outdated: ['t4'] });
    expect(st.textContent).toContain('Sent 2 threads');
    expect(st.textContent).toContain('2 threads are still unsent');
    expect(st.textContent).toContain('3 older comments were left out for good');
    expect(st.querySelector('a')!.getAttribute('href')).toContain('/sessions/sess1');
    expect(btn.disabled).toBe(false);
  });

  it('shows 502 inline and 409 message', async () => {
    const u = userEvent.setup();
    for (const [status, msg] of [[502, 'Session failed to start'], [409, 'Nothing unsent']] as const) {
      const { r, btn } = await go((b) => (b.confirm ? json({ error: msg }, status) : json(prev())));
      await u.click(btn);
      await u.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Send' }));
      expect((await within(r).findByRole('alert')).textContent).toContain(msg);
      expect(btn.textContent).toBe('Send open comments (2)');
      cleanup();
    }
  });

  it('warns for a running panel and update session; Send still works; ended share works', async () => {
    const u = userEvent.setup();
    const { r, btn } = await go((b) => (b.confirm ? json(sent(), 201) : json(prev({ busy: { sessions: ['s9'], panel: 'p1' } }))), 2, { state: 'ended' });
    await u.click(btn);
    const dlg = await screen.findByRole('alertdialog');
    expect(dlg.textContent).toContain('A peer review panel is running on this PRD');
    expect(dlg.textContent).toContain('A PRD update session is running on this PRD');
    await u.click(within(dlg).getByRole('button', { name: 'Send' }));
    expect(await within(r).findByRole('status')).toBeTruthy();
  });

  it('is disabled while the request runs', async () => {
    const u = userEvent.setup();
    let release!: (r: Response) => void;
    const { btn } = await go(() => new Promise<Response>((res) => { release = res; }));
    await u.click(btn);
    await waitFor(() => expect(btn.disabled).toBe(true));
    release(new Response(JSON.stringify(prev()), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    await screen.findByRole('alertdialog');
  });
});

describe('PRD freshness', () => {
  const sess = (outcome: string) => ({ id: 'u1', command: '/create-prd docs/prds/f1.md --update x', outcome });

  it('refetches when a create-prd session ends', async () => {
    let state = 'running';
    let text = '# F\n\n## A\nold text';
    mock({ sessions: () => [sess(state)], prdText: () => text });
    window.location.hash = '#/features/f1/prd?repo=o/r';
    render(<App />);
    expect(await screen.findByText('old text')).toBeTruthy();
    await new Promise((r) => setTimeout(r, 3200)); // the running session is seen by a poll
    text = '# F\n\n## A\nnew text';
    state = 'done';
    expect(await screen.findByText('new text', {}, { timeout: 5000 })).toBeTruthy();
  }, 15000);

  it('does not overwrite an edit draft when the PRD changes on disk', async () => {
    const u = userEvent.setup();
    let text = '# F\n\n## A\nold text';
    mock({ prdText: () => text });
    window.location.hash = '#/features/f1/prd?repo=o/r';
    render(<App />);
    await screen.findByText('old text');
    await u.click(screen.getByRole('button', { name: 'Edit' }));
    const box = (await screen.findByLabelText('PRD markdown')) as HTMLTextAreaElement;
    await u.type(box, ' mine');
    const draft = box.value;
    text = '# F\n\n## A\nnew text';
    window.dispatchEvent(new Event('focus'));
    await new Promise((r) => setTimeout(r, 300));
    expect(box.value).toBe(draft);
  });
});
