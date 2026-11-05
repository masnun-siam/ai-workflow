import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfirmProvider, Toaster } from '../components';
import { CreateRepoDialog } from '../repos/CreateRepoDialog';
import { PublishDialog } from '../repos/PublishDialog';
import { SettingsPage } from '../pages/SettingsPage';
import { OnboardingPage } from '../pages/OnboardingPage';
import { QueryProvider } from '../QueryProvider';

type Call = { method: string; url: string; body: Record<string, unknown> | null };
let calls: Call[];
type Reply = [number, unknown];
let handlers: Record<string, (body: Record<string, unknown> | null) => Reply | Promise<Reply>>;

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
const sent = (method: string, url: string) => calls.filter((c) => c.method === method && c.url === url).map((c) => c.body);

const EVENTS = [
  ['waiting', 'A session is waiting on you', 'Needs you'], ['failed', 'A session failed', 'Needs you'],
  ['dispatch', 'A dispatch needs you', 'Needs you'], ['panel-cap', 'Review panel hit its cap', 'Needs you'],
  ['prd-comment', 'Reviewers commented on a PRD', 'Needs you'],
  ['pr-ready', 'PR is ready for review', 'Pull requests'], ['needs-cleanup', 'Merged issue needs cleanup', 'Pull requests'],
  ['grind-paused', 'Grind paused', 'Pull requests'], ['grind-done', 'Grind finished', 'Pull requests'],
  ['done', 'A session is done', 'Finished'], ['pipeline', 'Pipeline finished', 'Finished'], ['afk', 'Away mode ended', 'Finished'],
].map(([key, label, group]) => ({ key, label, group }));
const matrix = () => Object.fromEntries(EVENTS.map((e) => [e.key, { browser: e.group !== 'Finished', ntfy: true, mac: e.group !== 'Finished' }]));

const GET: Record<string, unknown> = {
  '/api/repos': {
    repos: [{ slug: 'o/r', name: 'R', path: '/x/r' }, { slug: 'local/idea', name: 'local/idea', path: '/x/idea' }],
    can_browse: true,
    scan_roots: ['/x'],
  },
  '/api/settings': {
    commands: [{ label: 'claude', cmd: 'claude', builtin: true, harness: 'claude' }, { label: 'Masum', cmd: 'cc masum', harness: 'claude' }],
    default: 'claude',
    harnesses: [
      { id: 'claude', label: 'Claude Code', models: ['opus', 'sonnet', 'haiku'], efforts: ['low', 'medium', 'high', 'xhigh', 'max'], usage: true },
      { id: 'codex', label: 'Codex', models: null, efforts: ['low', 'medium', 'high', 'xhigh'], usage: false },
    ],
    repos: { 'o/r': { auto_grind: false, slack_channel: 'C0B8385GKNK' } },
    slack_channels: [{ id: 'C0B8385GKNK', name: '#reviews' }, { id: 'C0123ABCD', name: '#ops' }],
    reviewers: [
      { id: 'r-aaaaaaaa', name: 'Blubird AI Agent', slack_id: 'U0BS34962FK', github_login: 'blubird-ai-agent' },
      { id: 'r-bbbbbbbb', name: 'Masum', slack_id: 'U0373SRT22G', github_login: 'gsm-masum' },
      { id: 'r-cccccccc', name: 'Copilot', slack_id: '', github_login: 'copilot' },
    ],
    active_reviewers: ['r-bbbbbbbb'],
    bot_label: 'Review bot',
    vault_dir: '/vault',
    use_jev: true,
    jev_installed: true,
  },
  '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: {}, gh: { ok: false, error: 'not logged in' } },
  '/api/settings/notify': { server: 'https://ntfy.sh', topic: 't', user: '', public_url: '', token_set: true, password_set: false, env: ['topic'],
    ntfy_ready: true,
    mac: { available: true, notifier: true, clickable: false },
    events: EVENTS,
    matrix: matrix(),
  },
  '/api/settings/review': {
    max_rounds: 5,
    default_lenses: ['critical'],
    lenses: { critical: 'be critical', cto: 'cto edited' },
    shipped: { max_rounds: 5, default_lenses: ['critical'], lenses: { critical: 'be critical', cto: 'cto default' } },
    overridden: true,
  },
  '/api/github/owners': { owners: ['me', 'org'] },
  '/api/vault/prd': { exists: true, status: 'Approved', title: 'Gym' },
};

const SETTINGS = GET['/api/settings'] as Record<string, unknown>;
const withSettings = (patch: Record<string, unknown>) => { GET['/api/settings'] = { ...SETTINGS, ...patch }; };

function mockApi() {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    const path = String(url).split('?')[0];
    calls.push({ method, url: path, body });
    if (method === 'GET') return path in GET ? json(GET[path]) : json({ error: 'nope' }, 404);
    const h = handlers[`${method} ${path}`];
    return Promise.resolve(h ? h(body) : ([200, {}] as Reply)).then(([status, res]) => json(res, status));
  }));
}

function page(ui: ReactNode, at = '/settings/repos') {
  render(
    <QueryProvider>
      <ConfirmProvider>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route path="/settings/:section" element={ui} />
            <Route path="*" element={ui} />
          </Routes>
          <Toaster />
        </MemoryRouter>
      </ConfirmProvider>
    </QueryProvider>,
  );
}

beforeEach(() => {
  calls = [];
  handlers = {};
  mockApi();
});
afterEach(() => {
  GET['/api/settings'] = SETTINGS;
  cleanup();
  vi.unstubAllGlobals();
});

describe('Settings: repositories', () => {
  it('autosaves a row with only that repo and reverts when the server refuses', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'auto_grind must be a boolean' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sw = await screen.findByRole('switch', { name: 'Auto-grind o/r' });
    expect(sw.getAttribute('aria-checked')).toBe('false');
    await user.click(sw);
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: true, slack_channel: 'C0B8385GKNK' } } }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Auto-grind o/r' }).getAttribute('aria-checked')).toBe('false'));
    expect(await screen.findByText(/auto_grind must be a boolean/)).toBeTruthy();
  });

  it('the Slack channel select lists None and the channels, and saves a pick on change', async () => {
    handlers['PUT /api/settings'] = (b) => [200, { ...SETTINGS, repos: b?.repos }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sel = (await screen.findByRole('combobox', { name: 'Slack channel for o/r' })) as HTMLSelectElement;
    expect(sel.value).toBe('C0B8385GKNK');
    expect(within(sel).getAllByRole('option').map((o) => o.textContent)).toEqual(['None', '#reviews', '#ops']);
    await user.selectOptions(sel, '#ops');
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: false, slack_channel: 'C0123ABCD' } } }]));
    expect(await screen.findByText('Saved o/r')).toBeTruthy();
  });

  it('the select is disabled while its save is in flight', async () => {
    let finish: (r: Reply) => void = () => {};
    handlers['PUT /api/settings'] = () => new Promise<Reply>((r) => { finish = r; });
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sel = (await screen.findByRole('combobox', { name: 'Slack channel for local/idea' })) as HTMLSelectElement;
    await user.selectOptions(sel, '#ops');
    await waitFor(() => expect(sel.disabled).toBe(true));
    expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'local/idea': { auto_grind: false, slack_channel: 'C0123ABCD' } } }]);
    finish([200, SETTINGS]);
    await waitFor(() => expect(sel.disabled).toBe(false));
  });

  it('a refused pick puts the old channel back and shows the error', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'repo o/r: slack_channel C0123ABCD is not listed' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sel = (await screen.findByRole('combobox', { name: 'Slack channel for o/r' })) as HTMLSelectElement;
    await user.selectOptions(sel, 'None');
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect(await screen.findByText(/C0123ABCD is not listed/)).toBeTruthy();
    await waitFor(() => expect(sel.value).toBe('C0B8385GKNK'));
    expect(sel.disabled).toBe(false);
  });

  it('a legacy channel shows the invalid chip, and an Auto-grind save keeps it unchanged', async () => {
    withSettings({ repos: { 'o/r': { auto_grind: false, slack_channel: '#rev', channel_invalid: true, path: '/x/r' } } });
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sel = (await screen.findByRole('combobox', { name: 'Slack channel for o/r' })) as HTMLSelectElement;
    expect(sel.value).toBe('#rev');
    expect((within(sel).getByRole('option', { name: '#rev' }) as HTMLOptionElement).disabled).toBe(true);
    expect(screen.getByText('invalid')).toBeTruthy();
    expect(screen.getByText('Not a channel id. Pick a channel; grinds skip until then.')).toBeTruthy();
    await user.click(screen.getByRole('switch', { name: 'Auto-grind o/r' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: true, slack_channel: '#rev' } } }]));
  });

  it('with no saved channels the select holds only None', async () => {
    withSettings({ slack_channels: [], repos: {} });
    page(<SettingsPage />);
    const sel = await screen.findByRole('combobox', { name: 'Slack channel for o/r' });
    expect(within(sel).getAllByRole('option').map((o) => o.textContent)).toEqual(['None']);
  });

  it('a local repo offers Publish; Remove asks first', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'Publish' }));
    expect(await screen.findByRole('dialog', { name: 'Publish to GitHub' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Publish to GitHub' })).toBeNull());
    await user.click(screen.getByRole('button', { name: 'More actions for o/r' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Remove' }));
    expect(sent('POST', '/api/repos/remove')).toEqual([]); // not before the confirm
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(sent('POST', '/api/repos/remove')).toEqual([{ slug: 'o/r' }]));
  });

  it('a failed Remove neither toasts success nor rejects unhandled', async () => {
    handlers['POST /api/repos/remove'] = () => [500, { error: 'boom' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'More actions for local/idea' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Remove' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(sent('POST', '/api/repos/remove')).toHaveLength(1));
    await new Promise((r) => setTimeout(r, 20));
    expect(await screen.findByText('boom')).toBeTruthy(); // the cache toasts the error
    expect(screen.queryByText('Removed local/idea')).toBeNull(); // toasts are global, so this repo is used by no other test
  });

  it('Local review defaults to Single with its hint', async () => {
    page(<SettingsPage />);
    const single = (await screen.findByRole('radio', { name: 'Single' })) as HTMLInputElement;
    expect(single.checked).toBe(true);
    expect((screen.getByRole('radio', { name: 'Loop' }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole('group', { name: 'Local review for every implement-issue run' })).toBeTruthy();
    expect(screen.getByText('Single: fix Critical/Major, re-review new commits')).toBeTruthy();
  });

  it('picking Loop sends only review_mode, toasts and shows the Loop hint', async () => {
    handlers['PUT /api/settings'] = (b) => { withSettings(b ?? {}); return [200, GET['/api/settings']]; };
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('radio', { name: 'Loop' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ review_mode: 'loop' }]));
    expect(await screen.findByText('Local review is loop')).toBeTruthy();
    expect(screen.getByText('Loop: re-review until nothing new, then check and push once')).toBeTruthy();
    await waitFor(() => expect((screen.getByRole('radio', { name: 'Loop' }) as HTMLInputElement).checked).toBe(true));
  });

  it('the Local review radios are disabled while the save is in flight', async () => {
    let finish: (r: Reply) => void = () => {};
    handlers['PUT /api/settings'] = () => new Promise<Reply>((r) => { finish = r; });
    const user = userEvent.setup();
    page(<SettingsPage />);
    const loop = (await screen.findByRole('radio', { name: 'Loop' })) as HTMLInputElement;
    const single = screen.getByRole('radio', { name: 'Single' }) as HTMLInputElement;
    await user.click(loop);
    await waitFor(() => expect(loop.disabled && single.disabled).toBe(true));
    finish([200, { ...SETTINGS, review_mode: 'loop' }]);
    await waitFor(() => expect(loop.disabled || single.disabled).toBe(false));
  });

  it('a refused Local review save puts Single back and shows the error', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'review_mode must be single or loop' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('radio', { name: 'Loop' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect(await screen.findByText('review_mode must be single or loop')).toBeTruthy();
    await waitFor(() => expect((screen.getByRole('radio', { name: 'Single' }) as HTMLInputElement).checked).toBe(true));
  });

  it('the Grinding radios still send only grind_mode', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('radio', { name: 'Simple' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ grind_mode: 'simple' }]));
  });

  it('Find repos posts the folders and reports what it added', async () => {
    handlers['POST /api/repos/scan'] = () => [200, { added: [{ slug: 'a/b', path: '/x/b' }], duplicates: [], repos: [] }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: /Find repos/ }));
    await waitFor(() => expect(sent('POST', '/api/repos/scan')).toEqual([{ roots: ['/x'] }]));
    expect(await screen.findByText('Registered 1 new repo.')).toBeTruthy();
  });
});

describe('Settings: repo Reviewers cell', () => {
  const REPOS = {
    'o/r': { auto_grind: false, slack_channel: 'C0B8385GKNK', reviewers: null, path: 'slack', channel_invalid: false },
    'local/idea': { auto_grind: true, slack_channel: '', reviewers: ['r-cccccccc'], path: 'github' },
  };
  const cell = (slug: string) => screen.findByRole('button', { name: `Reviewers for ${slug}` });
  const box = (name: string) => screen.getByRole('checkbox', { name }) as HTMLInputElement;
  beforeEach(() => withSettings({ repos: REPOS }));

  it('shows Default with the active names, or the override chips', async () => {
    page(<SettingsPage />);
    expect((await cell('o/r')).textContent).toBe('Default (Masum)');
    expect(screen.getByRole('columnheader', { name: 'Reviewers' })).toBeTruthy();
    expect((await cell('local/idea')).textContent).toBe('Copilotoverride');
  });

  it('Enter and Space open the popover; Escape closes it and focus returns to the cell', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />);
    const btn = await cell('o/r');
    btn.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('checkbox', { name: 'Masum' })).toBeTruthy();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'Masum' })).toBeNull());
    expect(document.activeElement).toBe(btn);
    await user.keyboard(' ');
    expect(await screen.findByRole('checkbox', { name: 'Masum' })).toBeTruthy();
  });

  it('a first tick makes an override from the default set, disables the controls until it resolves, and never sends read-only keys', async () => {
    let finish: (r: Reply) => void = () => {};
    handlers['PUT /api/settings'] = () => new Promise<Reply>((r) => { finish = r; });
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await cell('o/r'));
    expect(box('Masum').checked).toBe(true);
    expect(box('Blubird AI Agent').checked).toBe(false);
    await user.click(box('Blubird AI Agent'));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: false, slack_channel: 'C0B8385GKNK', reviewers: ['r-bbbbbbbb', 'r-aaaaaaaa'] } } }]));
    expect(box('Blubird AI Agent').checked && box('Masum').disabled && box('Copilot').disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Use default' }) as HTMLButtonElement).disabled).toBe(true);
    finish([200, GET['/api/settings']]);
    await waitFor(() => expect(box('Masum').disabled).toBe(false));
  });

  it('a refused tick puts the old state back and toasts', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'unknown reviewer r-zzzzzzzz' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await cell('o/r'));
    await user.click(box('Copilot'));
    expect(await screen.findByText(/unknown reviewer r-zzzzzzzz/)).toBeTruthy();
    await waitFor(() => expect(box('Copilot').checked).toBe(false));
    expect(box('Copilot').disabled).toBe(false);
  });

  it('Use default sends reviewers: null', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await cell('local/idea'));
    await user.click(screen.getByRole('button', { name: 'Use default' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'local/idea': { auto_grind: true, slack_channel: '', reviewers: null } } }]));
  });

  it('dims entries the path cannot use, with the hint as text outside the dimmed name', async () => {
    withSettings({
      repos: REPOS,
      reviewers: [...(SETTINGS.reviewers as unknown[]), { id: 'r-dddddddd', name: 'Slacker', slack_id: 'U0123ABCDE', github_login: '' }],
    });
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await cell('o/r'));
    const hint = screen.getByText('not used: no Slack id');
    expect(hint.className).not.toContain('rv-off');
    expect(hint.closest('.rv-off')).toBeNull();
    expect(within(screen.getByRole('dialog')).getByText('Copilot').className).toBe('rv-off');
    expect(within(screen.getByRole('dialog')).getByText('Blubird AI Agent').className).toBe('');
    expect(screen.getByText('login learned from its first review')).toBeTruthy();
    await user.keyboard('{Escape}');
    await user.click(await cell('local/idea'));
    expect(screen.getByText('not used: no GitHub login')).toBeTruthy();
    expect(within(screen.getByRole('dialog')).getByText('Slacker').className).toBe('rv-off');
  });

  it('empty states: no reviewers, no active reviewer per path, and an empty override', async () => {
    withSettings({ repos: REPOS, reviewers: [] });
    page(<SettingsPage />);
    expect((await screen.findAllByText('Add reviewers in')).length).toBe(2);
    expect(screen.getAllByRole('link', { name: 'Settings → Reviewers' })[0].getAttribute('href')).toBe('#/settings/reviewers');
    cleanup();
    withSettings({ repos: { ...REPOS, 'local/idea': { ...REPOS['local/idea'], reviewers: null } }, active_reviewers: [] });
    page(<SettingsPage />);
    expect((await cell('o/r')).textContent).toBe('Default (none, mentions Review bot)');
    expect((await cell('local/idea')).textContent).toBe('Default (none, grinding skips)');
    cleanup();
    withSettings({ repos: { ...REPOS, 'local/idea': { ...REPOS['local/idea'], reviewers: ['r-gone'] } }, active_reviewers: [], bot_label: null });
    page(<SettingsPage />);
    expect((await cell('o/r')).textContent).toBe('Default (none, mentions the channels.json bot)');
    expect((await cell('local/idea')).textContent).toBe('override: none');
  });
});

describe('Settings: Slack channels', () => {
  const at = '/settings/channels';
  const nameOf = (id: string) => screen.getByRole('textbox', { name: `Name of ${id}` }) as HTMLInputElement;

  it('lists the channels and adds one: the whole list is sent, the Add row clears and focus returns', async () => {
    handlers['PUT /api/settings'] = (b) => { withSettings(b ?? {}); return [200, GET['/api/settings']]; };
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    expect((await screen.findByRole('textbox', { name: 'Name of C0B8385GKNK' }) as HTMLInputElement).value).toBe('#reviews');
    expect(nameOf('C0123ABCD').value).toBe('#ops');
    expect(screen.getByText('C0123ABCD')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Delete #ops' })).toBeTruthy();
    const name = screen.getByRole('textbox', { name: 'New channel name' }) as HTMLInputElement;
    const id = screen.getByRole('textbox', { name: 'New channel id' }) as HTMLInputElement;
    await user.type(name, ' #ship ');
    await user.type(id, 'G01234ABCDE');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ slack_channels: [...(SETTINGS.slack_channels as object[]), { id: 'G01234ABCDE', name: '#ship' }] }]));
    expect(await screen.findByRole('textbox', { name: 'Name of G01234ABCDE' })).toBeTruthy();
    await waitFor(() => expect(name.value).toBe(''));
    expect(id.value).toBe('');
    expect(document.activeElement).toBe(name);
  });

  it('Enter in the id field adds too', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.type(await screen.findByRole('textbox', { name: 'New channel name' }), '#ship');
    await user.type(screen.getByRole('textbox', { name: 'New channel id' }), 'D0123456789{Enter}');
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect((sent('PUT', '/api/settings')[0]?.slack_channels as object[]).at(-1)).toEqual({ id: 'D0123456789', name: '#ship' });
  });

  it('a bad id, a listed id or an empty name shows its message and sends nothing', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    const id = await screen.findByRole('textbox', { name: 'New channel id' });
    await user.type(screen.getByRole('textbox', { name: 'New channel name' }), '#reviews');
    await user.type(id, 'reviews');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('channel id must look like C0123ABCD')).toBeTruthy();
    await user.clear(id);
    await user.type(id, 'C0B8385GKNK{Enter}');
    expect(await screen.findByText('channel C0B8385GKNK is already listed')).toBeTruthy();
    await user.clear(screen.getByRole('textbox', { name: 'New channel name' }));
    expect(await screen.findByText('channel name must be 1 to 60 characters')).toBeTruthy();
    expect(sent('PUT', '/api/settings')).toEqual([]);
  });

  it('a rename saves the whole list on blur, and not when unchanged or invalid', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    const ops = await screen.findByRole('textbox', { name: 'Name of C0123ABCD' });
    await user.click(ops);
    await user.tab();
    await user.clear(ops);
    await user.tab();
    expect(screen.getByText('channel name must be 1 to 60 characters')).toBeTruthy();
    expect(sent('PUT', '/api/settings')).toEqual([]);
    await user.type(ops, '#oncall{Enter}');
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ slack_channels: [{ id: 'C0B8385GKNK', name: '#reviews' }, { id: 'C0123ABCD', name: '#oncall' }] }]));
  });

  it('a refused delete shows the server error and keeps the row', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'channel C0B8385GKNK is used by o/r' }];
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.click(await screen.findByRole('button', { name: 'Delete #reviews' }));
    expect(sent('PUT', '/api/settings')).toEqual([]); // not before the confirm
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ slack_channels: [{ id: 'C0123ABCD', name: '#ops' }] }]));
    expect(await screen.findByText('channel C0B8385GKNK is used by o/r')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Name of C0B8385GKNK' })).toBeTruthy());
  });

  it('an empty list shows the hint and the Add row', async () => {
    withSettings({ slack_channels: [] });
    page(<SettingsPage />, at);
    expect(await screen.findByText(/No channels yet/)).toBeTruthy();
    expect(screen.getByRole('textbox', { name: 'New channel name' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add' })).toBeTruthy();
  });

  it('a 51st channel shows "at most 50" and sends nothing', async () => {
    withSettings({ slack_channels: Array.from({ length: 50 }, (_, i) => ({ id: `C${String(i).padStart(9, '0')}`, name: `#c${i}` })) });
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.type(await screen.findByRole('textbox', { name: 'New channel name' }), '#one-more');
    await user.type(screen.getByRole('textbox', { name: 'New channel id' }), 'C999999999{Enter}');
    expect(await screen.findByText('at most 50')).toBeTruthy();
    expect(sent('PUT', '/api/settings')).toEqual([]);
  });
});

describe('Settings: Reviewers', () => {
  const at = '/settings/reviewers';
  const REVIEWERS = SETTINGS.reviewers as { id: string; name: string; slack_id: string; github_login: string }[];
  const box = (name: string) => screen.getByRole('checkbox', { name: `Active: ${name}` }) as HTMLInputElement;
  const tb = (name: string) => screen.getByRole('textbox', { name }) as HTMLInputElement;

  it('lists the reviewers with their Active ticks', async () => {
    page(<SettingsPage />, at);
    expect((await screen.findByRole('checkbox', { name: 'Active: Masum' }) as HTMLInputElement).checked).toBe(true);
    expect(box('Blubird AI Agent').checked).toBe(false);
    expect(box('Copilot').checked).toBe(false);
    expect(tb('Name of Copilot').value).toBe('Copilot');
    expect(screen.getByText('U0BS34962FK')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy(); // Copilot has no Slack id
    expect(screen.getByRole('button', { name: 'Delete Masum' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Reviewers' })).toBeTruthy();
  });

  it('a tick sends only active_reviewers and disables every tick until it resolves', async () => {
    let finish: (r: Reply) => void = () => {};
    handlers['PUT /api/settings'] = () => new Promise<Reply>((r) => { finish = r; });
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.click(await screen.findByRole('checkbox', { name: 'Active: Blubird AI Agent' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ active_reviewers: ['r-bbbbbbbb', 'r-aaaaaaaa'] }]));
    expect(box('Blubird AI Agent').checked).toBe(true);
    expect(box('Masum').disabled && box('Copilot').disabled && box('Blubird AI Agent').disabled).toBe(true);
    withSettings({ active_reviewers: ['r-bbbbbbbb', 'r-aaaaaaaa'] });
    finish([200, GET['/api/settings']]);
    await waitFor(() => expect(box('Masum').disabled).toBe(false));
    expect(box('Blubird AI Agent').checked).toBe(true);
  });

  it('a failed tick puts it back and toasts', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'unknown reviewer r-zzzzzzzz' }];
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.click(await screen.findByRole('checkbox', { name: 'Active: Masum' }));
    expect(await screen.findByText('unknown reviewer r-zzzzzzzz')).toBeTruthy();
    await waitFor(() => expect(box('Masum').checked).toBe(true));
  });

  it('adds one without an id: the row appears, the Add row clears and focus returns', async () => {
    handlers['PUT /api/settings'] = (b) => {
      withSettings({ reviewers: (b?.reviewers as object[]).map((r, i) => ({ id: `r-0000000${i}`, ...r })) });
      return [200, GET['/api/settings']];
    };
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    const name = await screen.findByRole('textbox', { name: 'New reviewer name' }) as HTMLInputElement;
    await user.type(name, ' Siam ');
    await user.type(tb('New reviewer Slack id'), 'W0123456789');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ reviewers: [...REVIEWERS, { name: 'Siam', slack_id: 'W0123456789', github_login: '' }] }]));
    expect(await screen.findByRole('checkbox', { name: 'Active: Siam' })).toBeTruthy();
    await waitFor(() => expect(name.value).toBe(''));
    expect(tb('New reviewer Slack id').value).toBe('');
    expect(document.activeElement).toBe(name);
  });

  it('Enter in a field adds too', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.type(await screen.findByRole('textbox', { name: 'New reviewer name' }), 'Octo');
    await user.type(tb('New reviewer GitHub login'), 'octocat{Enter}');
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect((sent('PUT', '/api/settings')[0]?.reviewers as object[]).at(-1)).toEqual({ name: 'Octo', slack_id: '', github_login: 'octocat' });
  });

  it('shows each FR-3 message inline and sends nothing', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    const name = await screen.findByRole('textbox', { name: 'New reviewer name' });
    const slack = tb('New reviewer Slack id');
    const login = tb('New reviewer GitHub login');
    await user.type(name, 'X');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('add a Slack id or a GitHub login')).toBeTruthy();
    await user.type(slack, '@bot');
    expect(await screen.findByText('Slack id must look like U0123ABCD')).toBeTruthy();
    await user.clear(slack);
    await user.type(slack, 'U0373SRT22G');
    expect(await screen.findByText('Slack id U0373SRT22G is already listed')).toBeTruthy();
    await user.clear(slack);
    await user.type(login, 'Gsm-Masum');
    expect(await screen.findByText('login gsm-masum is already listed')).toBeTruthy();
    await user.clear(login);
    await user.type(login, 'not_a_login{Enter}');
    expect(await screen.findByText('not a GitHub login')).toBeTruthy();
    await user.clear(name);
    expect(await screen.findByText('reviewer name must be 1 to 60 characters')).toBeTruthy();
    await user.type(name, 'x'.repeat(61));
    expect(screen.getByText('reviewer name must be 1 to 60 characters')).toBeTruthy();
    expect(sent('PUT', '/api/settings')).toEqual([]);
  });

  it('a 51st entry shows "at most 50" and sends nothing', async () => {
    withSettings({ reviewers: Array.from({ length: 50 }, (_, i) => ({ id: `r-${String(i).padStart(8, '0')}`, name: `R${i}`, slack_id: '', github_login: `r${i}` })) });
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.type(await screen.findByRole('textbox', { name: 'New reviewer name' }), 'One more');
    await user.type(tb('New reviewer GitHub login'), 'one-more{Enter}');
    expect(await screen.findByText('at most 50')).toBeTruthy();
    expect(sent('PUT', '/api/settings')).toEqual([]);
  });

  it('a rename saves the whole list on blur', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    const cop = await screen.findByRole('textbox', { name: 'Name of Copilot' });
    await user.clear(cop);
    await user.type(cop, 'GitHub Copilot');
    await user.tab();
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ reviewers: [REVIEWERS[0], REVIEWERS[1], { ...REVIEWERS[2], name: 'GitHub Copilot' }] }]));
  });

  it('delete asks first, naming where the entry is used', async () => {
    withSettings({ repos: { 'o/r': { auto_grind: false, slack_channel: '', reviewers: ['r-bbbbbbbb'] } } });
    const user = userEvent.setup();
    page(<SettingsPage />, at);
    await user.click(await screen.findByRole('button', { name: 'Delete Masum' }));
    let dlg = within(await screen.findByRole('alertdialog'));
    expect(dlg.getByRole('heading', { name: 'Delete Masum?' })).toBeTruthy();
    expect(dlg.getByText('It is active and overrides o/r.')).toBeTruthy();
    await user.click(dlg.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(sent('PUT', '/api/settings')).toEqual([]);
    await user.click(screen.getByRole('button', { name: 'Delete Copilot' }));
    dlg = within(await screen.findByRole('alertdialog'));
    expect(dlg.getByRole('heading', { name: 'Delete Copilot?' })).toBeTruthy();
    expect(dlg.queryByText(/It /)).toBeNull();
    await user.click(dlg.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ reviewers: [REVIEWERS[0], REVIEWERS[1]] }]));
  });

  it('with no active reviewer it warns, naming the bot', async () => {
    withSettings({ active_reviewers: [] });
    page(<SettingsPage />, at);
    expect(await screen.findByText('No active reviewer: Slack repos mention Review bot, GitHub repos skip grinding.')).toBeTruthy();
  });

  it('with no bot label the warning names the channels.json bot', async () => {
    withSettings({ active_reviewers: [], bot_label: null });
    page(<SettingsPage />, at);
    expect(await screen.findByText('No active reviewer: Slack repos mention the channels.json bot, GitHub repos skip grinding.')).toBeTruthy();
  });

  it('an empty list shows the hint and the Add row', async () => {
    withSettings({ reviewers: [], active_reviewers: [] });
    page(<SettingsPage />, at);
    expect(await screen.findByText(/No reviewers yet/)).toBeTruthy();
    expect(tb('New reviewer name')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add' })).toBeTruthy();
  });
});

describe('Settings: accounts, vault', () => {
  it('saves only commands and default, so vault_dir is not clobbered', async () => {
    handlers['PUT /api/settings'] = () => [200, GET['/api/settings']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    const radios = await screen.findAllByRole('radio', { name: 'Default' });
    await user.click(radios[1]);
    await user.click(screen.getByRole('button', { name: 'Save accounts' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect(sent('PUT', '/api/settings')[0]).toEqual({
      commands: [{ label: 'claude', cmd: 'claude', builtin: true, harness: 'claude' }, { label: 'Masum', cmd: 'cc masum', harness: 'claude' }],
      default: 'Masum',
    });
    expect((screen.getAllByLabelText('Command')[0] as HTMLInputElement).readOnly).toBe(true);
  });

  it('Test posts the command and shows the answer', async () => {
    handlers['POST /api/settings/test'] = () => [200, { ok: true, message: 'logged in me@x.com' }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    await user.click((await screen.findAllByRole('button', { name: 'Test' }))[1]);
    expect(await screen.findByText('logged in me@x.com')).toBeTruthy();
    expect(sent('POST', '/api/settings/test')).toEqual([{ cmd: 'cc masum' }]);
  });

  const harness = (i: number) => screen.getAllByLabelText('Harness')[i] as HTMLSelectElement;
  // Stores the PUT like the server, since a save refetches settings.
  const echo = (body: Record<string, unknown> | null): Reply => [200, (GET['/api/settings'] = { ...SETTINGS, ...body })];

  it('each row has a Harness select; the built-in one is fixed to Claude Code, a new row defaults to it', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    await screen.findAllByLabelText('Harness');
    expect(within(harness(0)).getAllByRole('option').map((o) => o.textContent)).toEqual(['Claude Code', 'Codex']);
    expect(harness(0).disabled).toBe(true);
    expect(harness(0).value).toBe('claude');
    expect(harness(1).disabled).toBe(false);
    await user.click(screen.getByRole('button', { name: /Add account/ }));
    expect(harness(2).value).toBe('claude');
  });

  it('Models shows only on Codex rows and keeps its text across a harness toggle', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    await screen.findAllByLabelText('Harness');
    expect(screen.queryByLabelText('Models')).toBeNull();
    await user.selectOptions(harness(1), 'codex');
    await user.type(screen.getByLabelText('Models'), 'a, b,');
    await user.selectOptions(harness(1), 'claude');
    expect(screen.queryByLabelText('Models')).toBeNull();
    await user.selectOptions(harness(1), 'codex');
    expect((screen.getByLabelText('Models') as HTMLInputElement).value).toBe('a, b,');
  });

  it('saves harness and a trimmed models list for Codex rows, reloads from the response, and is clean again', async () => {
    handlers['PUT /api/settings'] = echo;
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    await screen.findAllByLabelText('Harness');
    const saveBtn = screen.getByRole('button', { name: 'Save accounts' }) as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
    await user.selectOptions(harness(1), 'codex');
    expect(saveBtn.disabled).toBe(false);
    await user.type(screen.getByLabelText('Models'), 'a, b,');
    await user.click(saveBtn);
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect(sent('PUT', '/api/settings')[0]).toEqual({
      commands: [{ label: 'claude', cmd: 'claude', builtin: true, harness: 'claude' }, { label: 'Masum', cmd: 'cc masum', harness: 'codex', models: ['a', 'b'] }],
      default: 'claude',
    });
    await waitFor(() => expect(saveBtn.disabled).toBe(true));
    expect((screen.getByLabelText('Models') as HTMLInputElement).value).toBe('a, b');
    expect(harness(1).value).toBe('codex');
  });

  it('a Claude row sends no models, and changing only the models makes the form dirty', async () => {
    withSettings({ commands: [{ label: 'claude', cmd: 'claude', builtin: true, harness: 'claude' }, { label: 'Cx', cmd: 'codex', harness: 'codex', models: ['o3'] }] });
    handlers['PUT /api/settings'] = echo;
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    const models = (await screen.findByLabelText('Models')) as HTMLInputElement;
    expect(models.value).toBe('o3');
    const saveBtn = screen.getByRole('button', { name: 'Save accounts' }) as HTMLButtonElement;
    await user.type(models, ', gpt-5');
    expect(saveBtn.disabled).toBe(false);
    await user.selectOptions(harness(1), 'claude');
    await user.click(saveBtn);
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(1));
    expect((sent('PUT', '/api/settings')[0]!.commands as unknown[])[1]).toEqual({ label: 'Cx', cmd: 'codex', harness: 'claude' });
  });

  it('a login-check result clears when that row\'s harness or command changes', async () => {
    handlers['POST /api/settings/test'] = () => [200, { ok: true, message: 'logged in me@x.com' }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    const test = async () => {
      await user.click(screen.getAllByRole('button', { name: 'Test' })[1]);
      expect(await screen.findByText('logged in me@x.com')).toBeTruthy();
    };
    await screen.findAllByLabelText('Harness');
    await test();
    await user.selectOptions(harness(1), 'codex');
    expect(screen.queryByText('logged in me@x.com')).toBeNull();
    await test();
    await user.type(screen.getAllByLabelText('Command')[1], 'x');
    expect(screen.queryByText('logged in me@x.com')).toBeNull();
  });

  it('a 400 from the save is toasted and the form stays dirty', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'each account needs its own command' }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/accounts');
    await screen.findAllByLabelText('Harness');
    await user.selectOptions(harness(1), 'codex');
    const saveBtn = screen.getByRole('button', { name: 'Save accounts' }) as HTMLButtonElement;
    await user.click(saveBtn);
    expect(await screen.findByText('each account needs its own command')).toBeTruthy();
    expect(saveBtn.disabled).toBe(false);
  });

  it('the section and its navigation link read "Accounts", also when settings fail to load', async () => {
    page(<SettingsPage />, '/settings/accounts');
    expect(await screen.findByRole('heading', { name: 'Accounts' })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Accounts' })).toBeTruthy();
    cleanup();
    delete GET['/api/settings'];
    page(<SettingsPage />, '/settings/accounts');
    expect(await screen.findByRole('heading', { name: 'Accounts' })).toBeTruthy();
    const h = await screen.findByRole('heading', { name: 'Accounts' });
    await waitFor(() => expect(within(h.closest('section')!).getByRole('status').textContent).not.toBe('Loading…'));
    expect(screen.getByRole('heading', { name: 'Accounts' })).toBeTruthy();
  });

  it('the vault folder saves on its own with only vault_dir', async () => {
    handlers['PUT /api/settings'] = () => [200, GET['/api/settings']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/vault');
    const box = (await screen.findByLabelText('Vault folder')) as HTMLInputElement;
    await waitFor(() => expect(box.value).toBe('/vault'));
    await user.clear(box);
    await user.type(box, '~/notes');
    await user.click(screen.getByRole('button', { name: 'Save vault folder' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ vault_dir: '~/notes' }]));
  });
});

describe('Settings: notifications', () => {
  it('an empty secret is not sent, Remove clears it, env fields are read-only and left out', async () => {
    handlers['POST /api/settings/notify'] = () => [200, GET['/api/settings/notify']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    const token = (await screen.findByLabelText(/Access token/)) as HTMLInputElement;
    expect((screen.getByLabelText(/^Topic/) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/AIW_NTFY_TOPIC/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Save notifications' }));
    await waitFor(() => expect(sent('POST', '/api/settings/notify')).toHaveLength(1));
    expect(sent('POST', '/api/settings/notify')[0]).toEqual({ server: 'https://ntfy.sh', user: '', public_url: '' });
    await user.click(screen.getByLabelText('Remove the saved access token'));
    expect(token.disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Save notifications' }));
    await waitFor(() => expect(sent('POST', '/api/settings/notify')).toHaveLength(2));
    expect(sent('POST', '/api/settings/notify')[1]).toMatchObject({ token: '' });
  });

  it('a new secret is sent as typed', async () => {
    handlers['POST /api/settings/notify'] = () => [200, GET['/api/settings/notify']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.type(await screen.findByLabelText(/Access token/), 'tk_new');
    await user.click(screen.getByRole('button', { name: 'Save notifications' }));
    await waitFor(() => expect(sent('POST', '/api/settings/notify')[0]).toMatchObject({ token: 'tk_new' }));
  });

  it('shows the matrix: 36 named switches in three groups, states from the server', async () => {
    page(<SettingsPage />, '/settings/notifications');
    expect(await screen.findAllByRole('switch')).toHaveLength(36);
    expect([...document.querySelectorAll('th[scope=rowgroup]')].map((r) => r.textContent)).toEqual(['Needs you', 'Pull requests', 'Finished']);
    expect(screen.getAllByRole('switch')[15].getAttribute('aria-label')).toBe('PR is ready for review: Browser');
    expect(screen.getByRole('switch', { name: 'A session is done: ntfy' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('switch', { name: 'A session is done: Browser' }).getAttribute('aria-checked')).toBe('false');
  });

  it('a flip saves just that cell and shows the server value', async () => {
    handlers['POST /api/settings/notify/channel'] = () => {
      const m = matrix();
      m.failed.ntfy = false;
      GET['/api/settings/notify'] = { ...(GET['/api/settings/notify'] as object), matrix: m };
      return [200, GET['/api/settings/notify']];
    };
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.click(await screen.findByRole('switch', { name: 'A session failed: ntfy' }));
    await waitFor(() => expect(sent('POST', '/api/settings/notify/channel')).toEqual([{ event: 'failed', channel: 'ntfy', on: false }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'A session failed: ntfy' }).getAttribute('aria-checked')).toBe('false'));
    GET['/api/settings/notify'] = { ...(GET['/api/settings/notify'] as object), matrix: matrix() };
  });

  it('a failed flip goes back and shows the error', async () => {
    handlers['POST /api/settings/notify/channel'] = () => [400, { error: 'unknown event' }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.click(await screen.findByRole('switch', { name: 'A session failed: ntfy' }));
    expect(await screen.findByText('unknown event')).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'A session failed: ntfy' }).getAttribute('aria-checked')).toBe('true');
  });

  it('saving the ntfy form sends no channel cell', async () => {
    handlers['POST /api/settings/notify'] = () => [200, GET['/api/settings/notify']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.click(await screen.findByRole('button', { name: 'Save notifications' }));
    await waitFor(() => expect(sent('POST', '/api/settings/notify')).toHaveLength(1));
    expect(sent('POST', '/api/settings/notify/channel')).toEqual([]);
  });

  it('explains how to unblock browser notifications', async () => {
    vi.stubGlobal('Notification', { permission: 'denied', requestPermission: vi.fn() });
    page(<SettingsPage />, '/settings/notifications');
    expect(await screen.findByText('Browser notifications are blocked for this site.')).toBeTruthy();
    expect(screen.getByText(/Allow them in the browser's site settings/)).toBeTruthy();
  });
});

describe('Settings: notification channel headers', () => {
  const notify = (over: Record<string, unknown>) => { GET['/api/settings/notify'] = { ...(GET['/api/settings/notify'] as object), ...over }; };
  const base = { ...(GET['/api/settings/notify'] as object) };
  afterEach(() => { GET['/api/settings/notify'] = base; });
  const head = async (name: string) => (await screen.findByRole('columnheader', { name: new RegExp(`^${name}`) }));

  it('Browser shows On, Off with Enable, Blocked and Not supported', async () => {
    vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('Browser')).getByText('On')).toBeTruthy();
    cleanup();
    const ask = vi.fn(async () => 'granted');
    vi.stubGlobal('Notification', { permission: 'default', requestPermission: ask });
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('Browser')).getByText('Off')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Enable' }));
    expect(ask).toHaveBeenCalled();
    expect(within(await head('Browser')).getByText('On')).toBeTruthy();
    cleanup();
    vi.stubGlobal('Notification', { permission: 'denied', requestPermission: vi.fn() });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('Browser')).getByText('Blocked')).toBeTruthy();
    cleanup();
    vi.stubGlobal('Notification', undefined);
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('Browser')).getByText('Not supported')).toBeTruthy();
  });

  it('ntfy shows Set up or Not set up and its switches stay saveable', async () => {
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('ntfy')).getByText('Set up')).toBeTruthy();
    cleanup();
    notify({ ntfy_ready: false });
    handlers['POST /api/settings/notify/channel'] = () => [200, GET['/api/settings/notify']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('ntfy')).getByText('Not set up')).toBeTruthy();
    const sw = screen.getByRole('switch', { name: 'A session failed: ntfy' }) as HTMLButtonElement;
    expect(sw.disabled).toBe(false);
    await user.click(sw);
    await waitFor(() => expect(sent('POST', '/api/settings/notify/channel')).toEqual([{ event: 'failed', channel: 'ntfy', on: false }]));
  });

  it('This Mac shows Clickable, No links, the install text and Only on macOS (all disabled)', async () => {
    notify({ mac: { available: true, notifier: true, clickable: true } });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('This Mac')).getByText('Clickable')).toBeTruthy();
    cleanup();
    notify({ mac: { available: true, notifier: true, clickable: false } });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('This Mac')).getByText('No links')).toBeTruthy();
    cleanup();
    notify({ mac: { available: true, notifier: false, clickable: false } });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('This Mac')).getByText('Install terminal-notifier to make banners clickable (brew install terminal-notifier)')).toBeTruthy();
    cleanup();
    notify({ mac: { available: false, notifier: false, clickable: false } });
    page(<SettingsPage />, '/settings/notifications');
    expect(within(await head('This Mac')).getByText('Only on macOS')).toBeTruthy();
    const macSwitches = screen.getAllByRole('switch').filter((s) => /: This Mac$/.test(s.getAttribute('aria-label') ?? ''));
    expect(macSwitches).toHaveLength(12);
    expect(macSwitches.every((s) => (s as HTMLButtonElement).disabled)).toBe(true);
    expect((screen.getByRole('button', { name: 'Send test: This Mac' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('the Browser Send test is disabled unless granted, and shows the notification without a server call', async () => {
    vi.stubGlobal('Notification', { permission: 'default', requestPermission: vi.fn() });
    page(<SettingsPage />, '/settings/notifications');
    expect(((await screen.findByRole('button', { name: 'Send test: Browser' })) as HTMLButtonElement).disabled).toBe(true);
    cleanup();
    const showNotification = vi.fn(async () => undefined);
    vi.stubGlobal('Notification', { permission: 'granted', requestPermission: vi.fn() });
    vi.stubGlobal('navigator', { ...navigator, serviceWorker: { ready: Promise.resolve({ showNotification }) } });
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.click(await screen.findByRole('button', { name: 'Send test: Browser' }));
    await waitFor(() => expect(showNotification).toHaveBeenCalledWith('aiw: test notification', expect.objectContaining({ tag: 'aiw-test' })));
    expect(calls.filter((c) => c.url.includes('/notify/test'))).toEqual([]);
  });

  it('ntfy and This Mac Send test post the channel and toast the result', async () => {
    handlers['POST /api/settings/notify/test'] = (b) => [200, b?.channel === 'ntfy' ? { ok: false, error: 'HTTP 401' } : { ok: true }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/notifications');
    await user.click(await screen.findByRole('button', { name: 'Send test: ntfy' }));
    expect(await screen.findByText('ntfy test failed: HTTP 401')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Send test: This Mac' }));
    expect(await screen.findByText('This Mac test sent')).toBeTruthy();
    expect(sent('POST', '/api/settings/notify/test')).toEqual([{ channel: 'ntfy' }, { channel: 'mac' }]);
  });
});

describe('Settings: jev', () => {
  const settings = GET['/api/settings'] as Record<string, unknown>;
  const orig = { ...settings };
  afterEach(() => { for (const k of Object.keys(settings)) delete settings[k]; Object.assign(settings, orig); });

  it('flipping the switch sends use_jev and keeps it off', async () => {
    handlers['PUT /api/settings'] = (b) => { Object.assign(settings, b); return [200, settings]; };
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/jev');
    await user.click(await screen.findByRole('switch', { name: 'Use jev' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ use_jev: false }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Use jev' }).getAttribute('aria-checked')).toBe('false'));
  });

  it('a failed save goes back and shows the error', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'use_jev must be true or false' }];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/jev');
    await user.click(await screen.findByRole('switch', { name: 'Use jev' }));
    expect(await screen.findByText('use_jev must be true or false')).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'Use jev' }).getAttribute('aria-checked')).toBe('true');
  });

  it('says whether jev is installed', async () => {
    page(<SettingsPage />, '/settings/jev');
    expect(await screen.findByText('jev found')).toBeTruthy();
    cleanup();
    settings.jev_installed = false;
    page(<SettingsPage />, '/settings/jev');
    expect(await screen.findByText('jev not found — see docs/INSTALL.md')).toBeTruthy();
  });

  it('is on, and says nothing about installation, when the server sends neither field', async () => {
    delete settings.use_jev;
    delete settings.jev_installed;
    page(<SettingsPage />, '/settings/jev');
    expect((await screen.findByRole('switch', { name: 'Use jev' })).getAttribute('aria-checked')).toBe('true');
    expect(screen.queryByText(/jev found|jev not found/)).toBeNull();
  });
});

describe('Settings: peer review', () => {
  it('marks an edited prompt and resets only after a confirm', async () => {
    handlers['POST /api/settings/review'] = () => [200, GET['/api/settings/review']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/review');
    const summaries = await screen.findAllByText(/prompt/, { selector: 'summary' });
    expect(summaries.find((s) => /CTO/.test(s.textContent ?? ''))?.textContent).toMatch(/edited/);
    expect(summaries.find((s) => /Critical/.test(s.textContent ?? ''))?.textContent).not.toMatch(/edited/);
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }));
    expect(sent('POST', '/api/settings/review')).toEqual([]);
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Reset to defaults' }));
    await waitFor(() => expect(sent('POST', '/api/settings/review')).toEqual([{ reset: true }]));
  });

  it('saves rounds, default lenses and prompts; refuses rounds outside 1 to 10', async () => {
    handlers['POST /api/settings/review'] = () => [200, GET['/api/settings/review']];
    const user = userEvent.setup();
    page(<SettingsPage />, '/settings/review');
    const rounds = await screen.findByLabelText(/Rounds before/);
    await user.clear(rounds);
    await user.type(rounds, '11');
    expect(screen.getByRole('button', { name: 'Save peer review' }).hasAttribute('disabled')).toBe(true);
    await user.clear(rounds);
    await user.type(rounds, '3');
    await user.click(screen.getByRole('button', { name: 'CTO' }));
    await user.click(screen.getByRole('button', { name: 'Save peer review' }));
    await waitFor(() => expect(sent('POST', '/api/settings/review')).toEqual([{ max_rounds: 3, default_lenses: ['critical', 'cto'], lenses: { critical: 'be critical', cto: 'cto edited' } }]));
  });
});

describe('Create and publish dialogs', () => {
  it('Create posts parent, name and the vault PRD folder, then reports the new repo', async () => {
    handlers['POST /api/repos/create'] = () => [201, { slug: 'local/gym', path: '/x/gym' }];
    const user = userEvent.setup();
    const onCreated = vi.fn();
    page(<CreateRepoDialog open vaultFolder="05-Work/Gym" onClose={() => {}} onCreated={onCreated} />, '/x');
    expect(await screen.findByText('Approved')).toBeTruthy();
    await user.type(screen.getByLabelText('Name'), 'Gym App');
    await user.click(screen.getByRole('button', { name: '/x' }));
    await user.click(screen.getByRole('button', { name: 'Create repo' }));
    await waitFor(() => expect(sent('POST', '/api/repos/create')).toEqual([{ parent: '/x', name: 'gym-app', prd_folder: '05-Work/Gym' }]));
    expect(onCreated).toHaveBeenCalledWith({ slug: 'local/gym', path: '/x/gym' });
  });

  it('Publish posts owner, name and private', async () => {
    handlers['POST /api/repos/publish'] = () => [201, { slug: 'org/idea' }];
    const user = userEvent.setup();
    const onClose = vi.fn();
    page(<PublishDialog open slug="local/idea" onClose={onClose} />, '/x');
    await screen.findByRole('option', { name: 'org' });
    await user.selectOptions(screen.getByLabelText('Owner'), 'org');
    await user.click(screen.getByLabelText('Private'));
    await user.click(screen.getByRole('button', { name: 'Publish' }));
    await waitFor(() => expect(sent('POST', '/api/repos/publish')).toEqual([{ slug: 'local/idea', owner: 'org', name: 'idea', private: false }]));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe('Onboarding', () => {
  it('shows the gh sign-in fix, scans, lists what was added and finishes', async () => {
    handlers['POST /api/repos/scan'] = () => [200, { added: [{ slug: 'a/b', path: '/x/b' }], duplicates: [], repos: [] }];
    const user = userEvent.setup();
    page(<OnboardingPage />, '/onboarding');
    expect(await screen.findByText('GitHub CLI is not signed in')).toBeTruthy();
    expect(screen.getByText('gh auth login')).toBeTruthy();
    expect(await screen.findByText('Claude account found')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Find repos/ }));
    expect(await screen.findByText('Added 1 repository')).toBeTruthy();
    expect(sent('POST', '/api/repos/scan')).toEqual([{ roots: ['/x'] }]);
  });
});
