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
let handlers: Record<string, (body: Record<string, unknown> | null) => [number, unknown]>;

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
    commands: [{ label: 'claude', cmd: 'claude', builtin: true }, { label: 'Masum', cmd: 'cc masum' }],
    default: 'claude',
    repos: { 'o/r': { auto_grind: false, slack_channel: '#rev' } },
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

function mockApi() {
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    const path = String(url).split('?')[0];
    calls.push({ method, url: path, body });
    if (method === 'GET') return path in GET ? json(GET[path]) : json({ error: 'nope' }, 404);
    const h = handlers[`${method} ${path}`];
    const [status, res] = h ? h(body) : [200, {}];
    return json(res, status);
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
  cleanup();
  vi.unstubAllGlobals();
});

describe('Settings: repositories', () => {
  it('autosaves a row with only that repo and reverts when the server refuses', async () => {
    handlers['PUT /api/settings'] = () => [400, { error: 'slack_channel must be a string of at most 100 characters' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sw = await screen.findByRole('switch', { name: 'Auto-grind o/r' });
    expect(sw.getAttribute('aria-checked')).toBe('false');
    await user.click(sw);
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: true, slack_channel: '#rev' } } }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Auto-grind o/r' }).getAttribute('aria-checked')).toBe('false'));
    expect(await screen.findByText(/slack_channel must be a string/)).toBeTruthy();
  });

  it('saves a changed Auto-grind and a Slack channel on blur, and confirms with a toast', async () => {
    handlers['PUT /api/settings'] = (b) => [200, { ...(GET['/api/settings'] as object), repos: b?.repos }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('switch', { name: 'Auto-grind o/r' }));
    await waitFor(() => expect(sent('PUT', '/api/settings')[0]).toEqual({ repos: { 'o/r': { auto_grind: true, slack_channel: '#rev' } } }));
    expect(await screen.findByText('Saved o/r')).toBeTruthy();
    const slack = screen.getByLabelText('Slack channel for o/r');
    await user.clear(slack);
    await user.type(slack, '#ship');
    await user.tab();
    await waitFor(() => expect(sent('PUT', '/api/settings')).toHaveLength(2));
    expect((sent('PUT', '/api/settings')[1]?.repos as Record<string, { slack_channel: string }>)['o/r'].slack_channel).toBe('#ship');
  });

  it('a local repo offers Publish; Remove asks first', async () => {
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.click(await screen.findByRole('button', { name: 'Publish' }));
    expect(await screen.findByRole('dialog', { name: 'Publish to GitHub' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Publish to GitHub' })).toBeNull());
    await user.click(screen.getByRole('button', { name: 'Remove o/r' }));
    expect(sent('POST', '/api/repos/remove')).toEqual([]); // not before the confirm
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(sent('POST', '/api/repos/remove')).toEqual([{ slug: 'o/r' }]));
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
      commands: [{ label: 'claude', cmd: 'claude', builtin: true }, { label: 'Masum', cmd: 'cc masum' }],
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
