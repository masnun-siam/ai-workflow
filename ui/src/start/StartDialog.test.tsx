import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryProvider } from '../QueryProvider';
import { ConfirmProvider, Toaster } from '../components';
import { COMMANDS } from '../lib/vocab';
import { StartDialog } from './StartDialog';

type Call = { method: string; url: string; body: Record<string, unknown> | null };
let calls: Call[];
let postSessions: (body: Record<string, unknown>, n: number) => [number, unknown];

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const posts = () => calls.filter((c) => c.method === 'POST' && c.url === '/api/sessions').map((c) => c.body as Record<string, unknown>);

function mockApi(over: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/api/repos': { repos: [{ slug: 'o/r', name: 'R', path: '/x' }, { slug: 'o/other', name: 'Other', path: '/y' }], can_browse: false, scan_roots: [] },
    '/api/settings': { commands: [{ label: 'claude', cmd: 'claude', builtin: true }, { label: 'Masum', cmd: 'cc masum' }], default: 'claude' },
    '/api/sessions': { sessions: [], limits: { 'cc masum': { limited_until: Math.floor(Date.now() / 1000) + 3600 } }, usage: {}, afk: {} },
    '/api/peer-review': { default: ['critical'], max_rounds: 5, kinds: { 'create-prd': ['critical', 'cto'], custom: ['critical'] } },
    '/api/repos/o/r/open': { items: [{ number: 12, title: 'Fix the login', labels: ['bug'], updated_at: '', draft: false, url: null }] },
    '/api/vault/folders': { vault: '/v', folders: [{ project: 'Gym App', feature: null, path: '05-Work/Gym App' }] },
    ...over,
  };
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, url: String(url), body });
    const path = String(url).split('?')[0];
    if (method === 'POST' && path === '/api/sessions') {
      const [status, res] = postSessions(body ?? {}, posts().length);
      return json(res, status);
    }
    return routes[path] !== undefined ? json(routes[path]) : json({ error: 'nope' }, 404);
  }));
}

const Where = () => <div data-testid="loc">{useLocation().pathname}</div>;
function open(preset: { cmd?: string; arg?: string; repo?: string } = {}) {
  const onClose = vi.fn();
  render(
    <QueryProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={['/inbox?repo=o/r']}>
          <StartDialog open preset={preset} onClose={onClose} />
          <Where />
          <Toaster />
        </MemoryRouter>
      </ConfirmProvider>
    </QueryProvider>,
  );
  return onClose;
}
const startButton = () => screen.getByRole('button', { name: /^(Start|Queue|Retry|Starting)/ });
const ready = async () => {
  await waitFor(() => expect(screen.getByRole('button', { name: /^Where: / }).textContent).toBe('r'));
  await screen.findByRole('radiogroup', { name: 'Run on' });
};

beforeEach(() => {
  localStorage.clear();
  calls = [];
  postSessions = (_b, n) => [201, { id: `s${n}` }];
  mockApi();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Start dialog', () => {
  it('implement-issue: picks from the open list, posts the exact body and opens the session', async () => {
    const user = userEvent.setup();
    const onClose = open({ cmd: 'implement-issue' });
    await ready();
    expect(startButton().hasAttribute('disabled')).toBe(true); // an issue is required
    await user.click(await screen.findByRole('button', { name: /#12/ }));
    expect((screen.getByLabelText('Issue') as HTMLInputElement).value).toBe('12');
    await user.click(startButton());
    await waitFor(() => expect(posts()).toEqual([{ repo: 'o/r', command: 'implement-issue', args: '12', claude_cmd: 'claude' }]));
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/sessions/s1'));
    expect(onClose).toHaveBeenCalled();
    expect(localStorage.getItem('aiw.lastCommand')).toBe('implement-issue');
  });

  it('model and effort: preselected from settings, saved on change, sent with the start; Default omits them', async () => {
    mockApi({ '/api/settings': { commands: [{ label: 'claude', cmd: 'claude', builtin: true }], default: 'claude', run_model: 'sonnet' } });
    const user = userEvent.setup();
    open({ cmd: 'pr-review', arg: '5' });
    await ready().catch(() => undefined);
    const model = (await screen.findByLabelText('Model')) as HTMLSelectElement;
    await waitFor(() => expect(model.value).toBe('sonnet'));
    await user.selectOptions(model, 'opus');
    await user.selectOptions(screen.getByLabelText('Effort'), 'medium');
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT' && c.url === '/api/settings').map((c) => c.body)).toEqual([{ run_model: 'opus' }, { run_effort: 'medium' }]));
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toMatchObject({ model: 'opus', effort: 'medium' }));
  });

  it('Default model and effort are left out of the start body', async () => {
    const user = userEvent.setup();
    open({ cmd: 'pr-review', arg: '5' });
    await ready();
    await user.click(startButton());
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]).not.toHaveProperty('model');
    expect(posts()[0]).not.toHaveProperty('effort');
  });

  it('a list that cannot load still takes a typed number', async () => {
    mockApi({ '/api/repos/o/r/open': undefined });
    const user = userEvent.setup();
    open({ cmd: 'pr-review' });
    await ready();
    expect(await screen.findByText(/Type a number or URL instead/)).toBeTruthy();
    await user.type(screen.getByLabelText('Pull request'), '5');
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toMatchObject({ command: 'pr-review', args: '5' }));
  });

  it('a pasted issue URL of a registered repo switches the repo', async () => {
    const user = userEvent.setup();
    open({ cmd: 'implement-issue' });
    await ready();
    await user.type(screen.getByLabelText('Issue'), 'https://github.com/o/other/issues/3');
    await waitFor(() => expect(screen.getByRole('button', { name: /^Where: / }).textContent).toBe('other'));
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toMatchObject({ repo: 'o/other', args: 'https://github.com/o/other/issues/3' }));
  });

  it('text commands: 8 rows, ⌘↵ starts, lenses are sent as peer_review', async () => {
    const user = userEvent.setup();
    open({ cmd: 'create-prd' });
    await ready();
    const box = screen.getByLabelText('The idea') as HTMLTextAreaElement;
    expect(box.rows).toBe(8);
    await user.click(screen.getByRole('button', { name: 'CTO' }));
    await user.type(box, 'a gym app');
    await user.keyboard('{Control>}{Enter}{/Control}');
    await waitFor(() => expect(posts()).toEqual([{ repo: 'o/r', command: 'create-prd', args: 'a gym app', peer_review: ['cto'], claude_cmd: 'claude' }]));
  });

  it('No repo yet sends no_repo and the vault folder', async () => {
    const user = userEvent.setup();
    open({ cmd: 'dump' });
    await ready();
    await user.click(screen.getByRole('button', { name: /^Where: / }));
    await user.click(await screen.findByText('No repo yet: notes vault'));
    await user.type(screen.getByLabelText('What to capture'), 'a gym app bug');
    await waitFor(() => expect((screen.getByLabelText('Project') as HTMLInputElement).value).toBe('Gym App')); // keyword match
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toMatchObject({ repo: '', no_repo: true, command: 'dump', vault_folder: '05-Work/Gym App' }));
  });

  it('custom prompt posts {repo, text} and warns that permissions are skipped', async () => {
    const user = userEvent.setup();
    open({ cmd: 'custom' });
    await ready();
    expect(screen.getByText(/permission checks skipped/)).toBeTruthy();
    await user.type(screen.getByLabelText('Prompt'), '/pr-review 42');
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toEqual({ repo: 'o/r', text: '/pr-review 42', claude_cmd: 'claude' }));
  });

  it('a limited account marks itself and the button reads Queue', async () => {
    const user = userEvent.setup();
    open({ cmd: 'release-pr' });
    await ready();
    expect(startButton().textContent).toBe('Start');
    await user.click(screen.getByRole('radio', { name: /Masum · limited/ }));
    expect(startButton().textContent).toBe('Queue');
    expect(screen.getByText(/The session queues and starts at reset/)).toBeTruthy();
    await user.click(startButton());
    await waitFor(() => expect(posts()[0]).toMatchObject({ command: 'release-pr', claude_cmd: 'Masum' }));
  });

  it('a duplicate start (409) says so and offers the running session', async () => {
    postSessions = () => [409, { error: 'implement-issue already running for o/r#12', id: 'live1' }];
    const user = userEvent.setup();
    open({ cmd: 'implement-issue', arg: '12' });
    await ready();
    await user.click(startButton());
    await screen.findAllByRole('button', { name: 'Open that run' }); // the toast's and the dialog's
    const link = within(screen.getByRole('dialog')).getByRole('button', { name: 'Open that run' });
    await user.click(link);
    expect(screen.getByTestId('loc').textContent).toBe('/sessions/live1');
  });

  it('worklog range: one session per day sharing a batch, then Retry for the failed days', async () => {
    postSessions = (b, n) => (b.args === '2026-10-02' && n <= 3 ? [400, { error: 'boom' }] : [201, { id: `s${n}` }]);
    const user = userEvent.setup();
    open({ cmd: 'worklog' });
    await ready();
    await user.click(screen.getByRole('radio', { name: 'A range' }));
    await user.type(screen.getByLabelText('From'), '2026-10-01');
    await user.type(screen.getByLabelText('To'), '2026-10-03');
    expect(screen.getByText(/3 worklog runs, 3 at a time/)).toBeTruthy();
    await user.click(startButton());
    const retry = await screen.findByRole('button', { name: 'Retry 1 failed day' });
    const first = posts();
    expect(first.map((b) => b.args)).toEqual(['2026-10-01', '2026-10-02', '2026-10-03']);
    const batch = first[0].batch as string;
    expect(batch).toMatch(/^wl-/);
    expect(first.every((b) => b.batch === batch && b.command === 'worklog' && b.repo === 'o/r')).toBe(true);
    expect(screen.getByRole('alert').textContent).toMatch(/1 of 3 did not start: 2026-10-02/);
    await user.click(retry);
    await waitFor(() => expect(posts()).toHaveLength(4));
    expect(posts()[3]).toMatchObject({ args: '2026-10-02' });
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/activity'));
  });

  it('worklog today starts one session and opens it', async () => {
    const user = userEvent.setup();
    open({ cmd: 'worklog' });
    await ready();
    await user.click(startButton());
    await waitFor(() => expect(posts()).toEqual([{ repo: 'o/r', command: 'worklog', args: 'today', claude_cmd: 'claude' }]));
    await waitFor(() => expect(screen.getByTestId('loc').textContent).toBe('/sessions/s1'));
  });

  it('faq-updater: optional 8-row input, listed after docs-updater, starts empty', async () => {
    const user = userEvent.setup();
    open({ cmd: 'faq-updater' });
    await ready();
    const box = screen.getByLabelText('New questions or options (optional)') as HTMLTextAreaElement;
    expect(box.rows).toBe(8);
    expect(box.placeholder).toBe('One question per line. Options: full, --lang en,bn, --videos <playlist URL>');
    const ids = COMMANDS.find((g) => g.g === 'Maintain')?.items.map((c) => c.id) ?? [];
    expect(ids.indexOf('faq-updater')).toBe(ids.indexOf('docs-updater') + 1);
    await user.click(startButton());
    await waitFor(() => expect(posts()).toEqual([{ repo: 'o/r', command: 'faq-updater', args: '', claude_cmd: 'claude' }]));
  });

  it('repo-bootstrap: optional input, listed after faq-updater, starts empty', async () => {
    const user = userEvent.setup();
    open({ cmd: 'repo-bootstrap' });
    await ready();
    expect(screen.getByLabelText('Phase and issue (optional)')).toBeTruthy();
    const ids = COMMANDS.find((g) => g.g === 'Maintain')?.items.map((c) => c.id) ?? [];
    expect(ids.indexOf('repo-bootstrap')).toBe(ids.indexOf('faq-updater') + 1);
    expect(screen.getByText(/one branch and one PR, each phase its own session/)).toBeTruthy();
    expect((screen.getByLabelText('Phase and issue (optional)') as HTMLInputElement).placeholder).toBe('Optional: leave empty to start at the audit, or give a later phase and the bootstrap issue, e.g. guides 123');
    await user.click(startButton());
    await waitFor(() => expect(posts()).toEqual([{ repo: 'o/r', command: 'repo-bootstrap', args: '', claude_cmd: 'claude' }]));
  });

  it('repo-bootstrap: a 409 shows the message with Open that run', async () => {
    postSessions = () => [409, { error: 'A bootstrap run is already open for o/r', id: 'run-s1' }];
    const user = userEvent.setup();
    open({ cmd: 'repo-bootstrap' });
    await ready();
    await user.click(startButton());
    await screen.findAllByRole('button', { name: 'Open that run' });
    const dlg = within(screen.getByRole('dialog'));
    expect(dlg.getByText('A bootstrap run is already open for o/r')).toBeTruthy();
    await user.click(dlg.getByRole('button', { name: 'Open that run' }));
    expect(screen.getByTestId('loc').textContent).toBe('/sessions/run-s1');
  });

  it('switching to a same-kind command carries the argument over', async () => {
    const user = userEvent.setup();
    open({ cmd: 'dump', arg: 'an idea' });
    await ready();
    await user.click(screen.getByRole('button', { name: /Write a PRD/ }));
    expect((screen.getByLabelText('The idea') as HTMLTextAreaElement).value).toBe('an idea');
    await user.click(screen.getByRole('button', { name: /Review a PR/ }));
    expect((screen.getByLabelText('Pull request') as HTMLInputElement).value).toBe('');
    expect(within(screen.getByRole('navigation', { name: 'Commands' })).getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual(['Plan', 'Build', 'Review', 'Ship', 'Capture', 'Maintain']);
  });
});
