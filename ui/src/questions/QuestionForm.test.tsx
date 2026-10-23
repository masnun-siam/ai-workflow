import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildAnswer, displayLabel, initialAnswers } from './QuestionForm';
import { QuestionForm } from './QuestionForm';
import type { Question } from '../api/types';

const Q1: Question = { question: 'Which DB?', header: 'DB', multiSelect: false, allowFreeText: true, recommended: 'Postgres (Recommended)', options: [{ label: 'SQLite' }, { label: 'Postgres (Recommended)', description: 'robust' }] };
const Q2: Question = { question: 'Extras?', multiSelect: true, allowFreeText: false, options: [{ label: 'A' }, { label: 'B' }] };

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
function setup(session: Record<string, unknown>, answer: () => Promise<Response> = () => json({})) {
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => (init?.method === 'POST' ? answer() : json(session)));
  vi.stubGlobal('fetch', fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><QuestionForm sessionId="s1" /></MemoryRouter></QueryClientProvider>);
  return fetchMock;
}
const sess = (over: Record<string, unknown> = {}, qs = [Q1]) => ({ id: 's1', outcome: 'waiting', waiting: true, ended_at: '2026-01-01T00:00:00Z', pending_question: { id: 'r1', questions: qs }, ...over });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('QuestionForm logic', () => {
  it('pre-selects the recommended option and strips the suffix', () => {
    expect(initialAnswers([Q1, Q2])).toEqual([{ labels: ['Postgres (Recommended)'], other: '', useOther: false }, { labels: [], other: '', useOther: false }]);
    expect(displayLabel('Postgres (Recommended)')).toBe('Postgres');
  });
  it('builds one of labels|other per question and validates', () => {
    const a = initialAnswers([Q1, Q2]);
    expect(buildAnswer('r', [Q1, Q2], a)).toEqual({ error: 'Please answer "Extras?"' });
    a[1].labels = ['A', 'B'];
    expect(buildAnswer('r', [Q1, Q2], a)).toEqual({ round_id: 'r', answers: { 0: { labels: ['Postgres (Recommended)'] }, 1: { labels: ['A', 'B'] } } });
    a[0] = { labels: [], other: 'x'.repeat(4001), useOther: true };
    expect(buildAnswer('r', [Q1, Q2], a)).toHaveProperty('error');
  });
});

describe('QuestionForm', () => {
  it('shows the recommended tag and sends the pre-selected answer', async () => {
    const f = setup(sess());
    const user = userEvent.setup();
    expect(await screen.findByText('Recommended')).toBeTruthy();
    expect((screen.getByRole('radio', { name: /Postgres/ }) as HTMLInputElement).checked).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Send answer and resume' }));
    await waitFor(() => expect(f.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true));
    const post = f.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(String(post[0])).toBe('/api/sessions/s1/answer');
    expect(JSON.parse(post[1]!.body as string)).toEqual({ round_id: 'r1', answers: { 0: { labels: ['Postgres (Recommended)'] } } });
  });

  it('free text replaces the choice', async () => {
    const f = setup(sess());
    const user = userEvent.setup();
    await user.click(await screen.findByRole('radio', { name: /Something else/ }));
    await user.type(screen.getByRole('textbox'), 'Mongo');
    await user.click(screen.getByRole('button', { name: 'Send answer and resume' }));
    await waitFor(() => expect(f.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true));
    expect(JSON.parse(f.mock.calls.find(([, i]) => i?.method === 'POST')![1]!.body as string).answers).toEqual({ 0: { other: 'Mongo' } });
  });

  it('counts answers in the submit label', async () => {
    setup(sess({}, [Q1, Q2]));
    expect(await screen.findByRole('button', { name: 'Send 2 answers and resume' })).toBeTruthy();
  });

  it('locks while the process is alive and unlocks when it exits', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let alive = true;
    vi.stubGlobal('fetch', vi.fn(() => json(sess({ ended_at: alive ? null : '2026-01-01T00:00:00Z' }))));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><MemoryRouter><QuestionForm sessionId="s1" /></MemoryRouter></QueryClientProvider>);
    const btn = await screen.findByRole('button', { name: 'Send answer and resume' });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/still finishing its turn/)).toBeTruthy();
    alive = false;
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect((screen.getByRole('button', { name: 'Send answer and resume' }) as HTMLButtonElement).disabled).toBe(false));
    vi.useRealTimers();
  });

  it('409 says Already answered with a reload', async () => {
    setup(sess(), () => json({ error: 'session is not waiting for an answer' }, 409));
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Send answer and resume' }));
    expect(await screen.findByText(/Already answered/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeTruthy();
  });

  describe('markdown and previews', () => {
    const BOX = '+---+\n| A |\n+---+';
    const MD: Question = {
      question: 'Pick `code` and **bold**:\n\n- one\n- two\n\nSee https://example.com/x <script>window.__x=1</script>',
      multiSelect: false,
      allowFreeText: false,
      options: [
        { label: 'Use **X**', description: 'has `tick` <script>1</script>', preview: BOX },
        { label: 'Plain' },
      ],
    };
    const mount = async () => {
      const f = setup(sess({}, [MD]));
      await screen.findByText('Plain');
      return f;
    };

    it('renders question text and descriptions as markdown, escaped', async () => {
      await mount();
      const t = document.querySelector('.q-text')!;
      expect(t.querySelector('code')!.textContent).toBe('code');
      expect(t.querySelector('strong')!.textContent).toBe('bold');
      expect(t.querySelectorAll('li').length).toBe(2);
      const a = t.querySelector('a[href^="https"]')!;
      expect(a.getAttribute('target')).toBe('_blank');
      expect(t.querySelector('script')).toBeNull();
      expect(t.textContent).toContain('<script>');
      expect(document.querySelector('.opt .d code')!.textContent).toBe('tick');
      expect(document.querySelector('.opt script')).toBeNull();
    });

    it('shows a preview verbatim and no block without one', async () => {
      await mount();
      const pres = document.querySelectorAll('pre.q-preview');
      expect(pres.length).toBe(1);
      expect(pres[0].textContent).toBe(BOX);
    });

    it('renders nothing for empty question text or description', async () => {
      setup(sess({}, [{ ...Q2, question: '', options: [{ label: 'A', description: '' }] }]));
      await screen.findByText('A');
      expect(document.querySelector('.q-text')).toBeNull();
      expect(document.querySelector('.opt .d')).toBeNull();
    });

    it('keeps labels plain and sends the exact label', async () => {
      const f = await mount();
      expect(screen.getByText('Use **X**')).toBeTruthy();
      const user = userEvent.setup();
      await user.click(screen.getByRole('radio', { name: /Use \*\*X\*\*/ }));
      await user.click(screen.getByRole('button', { name: 'Send answer and resume' }));
      await waitFor(() => expect(f.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true));
      expect(JSON.parse(f.mock.calls.find(([, i]) => i?.method === 'POST')![1]!.body as string).answers).toEqual({ 0: { labels: ['Use **X**'] } });
    });
  });
});
