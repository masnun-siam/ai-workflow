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

const GET: Record<string, unknown> = {
  '/api/repos': {
    repos: [{ slug: 'o/r', name: 'R', path: '/x/r' }, { slug: 'local/idea', name: 'local/idea', path: '/x/idea' }],
    can_browse: true,
    scan_roots: ['/x'],
  },
  '/api/settings': {
    commands: [{ label: 'claude', cmd: 'claude', builtin: true }, { label: 'Masum', cmd: 'cc masum' }],
    default: 'claude',
    repos: { 'o/r': { auto_grind: false, autopilot_cap: 2, slack_channel: '#rev' } },
    vault_dir: '/vault',
  },
  '/api/sessions': { sessions: [], limits: {}, usage: {}, afk: {}, gh: { ok: false, error: 'not logged in' } },
  '/api/settings/notify': { server: 'https://ntfy.sh', topic: 't', user: '', public_url: '', token_set: true, password_set: false, env: ['topic'] },
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
    handlers['PUT /api/settings'] = () => [400, { error: 'autopilot_cap must be an integer from 1 to 5' }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    const sw = await screen.findByRole('switch', { name: 'Auto-grind o/r' });
    expect(sw.getAttribute('aria-checked')).toBe('false');
    await user.click(sw);
    await waitFor(() => expect(sent('PUT', '/api/settings')).toEqual([{ repos: { 'o/r': { auto_grind: true, autopilot_cap: 2, slack_channel: '#rev' } } }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Auto-grind o/r' }).getAttribute('aria-checked')).toBe('false'));
    expect(await screen.findByText(/autopilot_cap must be an integer/)).toBeTruthy();
  });

  it('saves a changed cap and a Slack channel on blur, and confirms with a toast', async () => {
    handlers['PUT /api/settings'] = (b) => [200, { ...(GET['/api/settings'] as object), repos: b?.repos }];
    const user = userEvent.setup();
    page(<SettingsPage />);
    await user.selectOptions(await screen.findByLabelText('Auto-build cap for o/r'), '4');
    await waitFor(() => expect(sent('PUT', '/api/settings')[0]).toEqual({ repos: { 'o/r': { auto_grind: false, autopilot_cap: 4, slack_channel: '#rev' } } }));
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

  it('explains how to unblock browser notifications', async () => {
    vi.stubGlobal('Notification', { permission: 'denied', requestPermission: vi.fn() });
    page(<SettingsPage />, '/settings/notifications');
    expect(await screen.findByText('Browser notifications are blocked for this site.')).toBeTruthy();
    expect(screen.getByText(/Allow them in the browser's site settings/)).toBeTruthy();
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
