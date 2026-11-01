import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildAnswer, displayLabel, initialAnswers } from './QuestionForm';
import { QuestionForm } from './QuestionForm';
import type { Question } from '../api/types';

const Q1: Question = { question: 'Which DB?', header: 'DB', multiSelect: false, allowFreeText: true, recommended: 'Postgres (Recommended)', options: [{ label: 'SQLite' }, { label: 'Postgres (Recommended)', description: 'robust' }] };
const Q2: Question = { question: 'Extras?', multiSelect: true, allowFreeText: false, options: [{ label: 'A' }, { label: 'B' }] };

const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } }));
function setup(session: Record<string, unknown>, answer: () => Promise<Response> = () => json({}), props: { autoFocus?: boolean; onEscape?: () => void } = {}) {
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => (init?.method === 'POST' ? answer() : json(session)));
  vi.stubGlobal('fetch', fetchMock);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><MemoryRouter><QuestionForm sessionId="s1" {...props} /></MemoryRouter></QueryClientProvider>);
  return fetchMock;
}
const sess = (over: Record<string, unknown> = {}, qs = [Q1]) => ({ id: 's1', outcome: 'waiting', waiting: true, ended_at: '2026-01-01T00:00:00Z', pending_question: { id: 'r1', questions: qs }, ...over });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('QuestionForm logic', () => {
  it('pre-selects the recommended option and strips the suffix', () => {
    expect(initialAnswers([Q1, Q2])).toEqual([{ labels: ['Postgres (Recommended)'], other: '', useOther: false, none: false }, { labels: [], other: '', useOther: false, none: false }]);
    expect(displayLabel('Postgres (Recommended)')).toBe('Postgres');
  });
  it('builds one of labels|other per question and validates', () => {
    const a = initialAnswers([Q1, Q2]);
    expect(buildAnswer('r', [Q1, Q2], a)).toEqual({ error: 'Please answer "Extras?"' });
    a[1].labels = ['A', 'B'];
    expect(buildAnswer('r', [Q1, Q2], a)).toEqual({ round_id: 'r', answers: { 0: { labels: ['Postgres (Recommended)'] }, 1: { labels: ['A', 'B'] } } });
    a[0] = { labels: [], other: 'x'.repeat(4001), useOther: true, none: false };
    expect(buildAnswer('r', [Q1, Q2], a)).toHaveProperty('error');
  });
});

describe('none of these / select all', () => {
  const Q3: Question = { question: 'Pick?', multiSelect: true, allowFreeText: true, recommended: 'A', options: [{ label: 'A' }, { label: 'B' }, { label: 'C' }] };
  const box = (n: RegExp | string) => screen.findByRole('checkbox', { name: n }) as Promise<HTMLInputElement>;
  const posts = (f: ReturnType<typeof setup>) => f.mock.calls.filter(([, i]) => i?.method === 'POST');

  it('buildAnswer sends none for multi-select, ignores it on single-select', () => {
    expect(buildAnswer('r', [Q2], [{ labels: [], other: '', useOther: false, none: true }])).toEqual({ round_id: 'r', answers: { 0: { none: true } } });
    expect(buildAnswer('r', [Q2], initialAnswers([Q2]))).toEqual({ error: 'Please answer "Extras?"' });
    expect(buildAnswer('r', [Q1], [{ labels: [], other: '', useOther: false, none: true }])).toEqual({ error: 'Please answer "Which DB?"' });
  });

  it('None of these clears the recommended pick, enables Send and posts none', async () => {
    const f = setup(sess({}, [Q3]));
    const user = userEvent.setup();
    expect((await box(/^A/)).checked).toBe(true);
    await user.click(await box('None of these'));
    expect((await box(/^A/)).checked).toBe(false);
    expect((await box('None of these')).checked).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Send answer and resume' }));
    await waitFor(() => expect(posts(f).length).toBe(1));
    expect(JSON.parse(posts(f)[0][1]!.body as string).answers).toEqual({ 0: { none: true } });
  });

  it('ticking an option or Something else unticks None; unticking None leaves Send disabled', async () => {
    setup(sess({}, [Q3]));
    const user = userEvent.setup();
    await user.click(await box('None of these'));
    await user.click(await box('B'));
    expect((await box('None of these')).checked).toBe(false);
    await user.click(await box('None of these'));
    await user.click(await box(/Something else/));
    expect((await box('None of these')).checked).toBe(false);
    await user.click(await box(/Something else/));
    await user.click(await box('None of these'));
    await user.click(await box('None of these'));
    expect((screen.getByRole('button', { name: 'Send answer and resume' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('Select all ticks every option, clears None and Something else, and is not a toggle', async () => {
    setup(sess({}, [Q3]));
    const user = userEvent.setup();
    await user.click(await box(/Something else/));
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    for (const l of ['A', 'B', 'C']) expect((await box(new RegExp(`^${l}`))).checked).toBe(true);
    expect((await box(/Something else/)).checked).toBe(false);
    await user.click(await box('None of these'));
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    await user.click(screen.getByRole('button', { name: 'Select all' }));
    expect((await box('None of these')).checked).toBe(false);
    for (const l of ['A', 'B', 'C']) expect((await box(new RegExp(`^${l}`))).checked).toBe(true);
  });

  it('single-select shows neither control; number keys map to options and 0 to Something else only', async () => {
    setup(sess());
    await screen.findByRole('radio', { name: /Postgres/ });
    expect(screen.queryByText('None of these')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Select all' })).toBeNull();
    cleanup();
    setup(sess({}, [Q3]));
    const user = userEvent.setup();
    (await box(/^A/)).focus();
    await user.keyboard('23');
    expect([(await box(/^A/)).checked, (await box('B')).checked, (await box('C')).checked]).toEqual([true, true, true]);
    await user.keyboard('4');
    expect((await box('None of these')).checked).toBe(false);
    await user.keyboard('0');
    expect((await box(/Something else/)).checked).toBe(true);
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

  describe('keyboard', () => {
    const posts = (f: ReturnType<typeof setup>) => f.mock.calls.filter(([, i]) => i?.method === 'POST');
    const QA: Question = { question: 'First?', multiSelect: false, allowFreeText: false, options: [{ label: 'A1' }, { label: 'A2' }] };
    const QB: Question = { question: 'Second?', multiSelect: false, allowFreeText: false, options: [{ label: 'B1' }, { label: 'B2' }] };

    it('answers a two-question round with 2, Tab, 1, then submit', async () => {
      const f = setup(sess({}, [QA, QB]));
      const user = userEvent.setup();
      (await screen.findByRole('radio', { name: 'A1' })).focus();
      await user.keyboard('2{Tab}1');
      expect(document.activeElement).toBe(screen.getByRole('radio', { name: 'B1' }));
      fireEvent.submit(document.querySelector('form')!);
      await waitFor(() => expect(posts(f).length).toBe(1));
      expect(JSON.parse(posts(f)[0][1]!.body as string).answers).toEqual({ 0: { labels: ['A2'] }, 1: { labels: ['B1'] } });
    });

    it('toggles a multi-select option with its number key', async () => {
      setup(sess({}, [Q2]));
      const user = userEvent.setup();
      const a = (await screen.findByRole('checkbox', { name: 'A' })) as HTMLInputElement;
      a.focus();
      await user.keyboard('1');
      expect(a.checked).toBe(true);
      await user.keyboard('1');
      expect(a.checked).toBe(false);
    });

    it('0 and O pick Something else and focus its box; digits typed there stay text', async () => {
      setup(sess());
      const user = userEvent.setup();
      (await screen.findByRole('radio', { name: /Postgres/ })).focus();
      await user.keyboard('0');
      const box = screen.getByRole('textbox') as HTMLTextAreaElement;
      expect(document.activeElement).toBe(box);
      await user.keyboard('12o');
      expect(box.value).toBe('12o');
      expect((screen.getByRole('radio', { name: /Something else/ }) as HTMLInputElement).checked).toBe(true);
    });

    it('0 does nothing without free text', async () => {
      setup(sess({}, [QA]));
      const user = userEvent.setup();
      (await screen.findByRole('radio', { name: 'A1' })).focus();
      await user.keyboard('0O');
      expect(screen.queryByRole('textbox')).toBeNull();
    });

    it('shows numbers for options 1-9 only and ignores a tenth key', async () => {
      const many: Question = { question: 'Many?', multiSelect: false, allowFreeText: false, options: Array.from({ length: 10 }, (_, i) => ({ label: `L${i + 1}` })) };
      setup(sess({}, [many]));
      await screen.findByText('L10');
      expect([...document.querySelectorAll('.opt-n')].map((n) => n.textContent)).toEqual(['1', '2', '3', '4', '5', '6', '7', '8', '9']);
      expect(document.querySelector('.opt-n')!.getAttribute('aria-hidden')).toBe('true');
    });

    it('an incomplete round sends nothing and Send stays disabled', async () => {
      const f = setup(sess({}, [QA]));
      const btn = (await screen.findByRole('button', { name: 'Send answer and resume' })) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      fireEvent.submit(document.querySelector('form')!);
      expect(posts(f).length).toBe(0);
    });

    it('autoFocus focuses the checked option; without it focus stays put', async () => {
      setup(sess(), undefined, { autoFocus: true });
      const r = await screen.findByRole('radio', { name: /Postgres/ });
      await waitFor(() => expect(document.activeElement).toBe(r));
      cleanup();
      setup(sess());
      await screen.findByRole('radio', { name: /Postgres/ });
      expect(document.activeElement).toBe(document.body);
    });

    it('Esc calls onEscape and stops the event', async () => {
      const onEscape = vi.fn();
      const outer = vi.fn();
      setup(sess(), undefined, { onEscape });
      document.body.addEventListener('keydown', outer);
      const user = userEvent.setup();
      (await screen.findByRole('radio', { name: /Postgres/ })).focus();
      await user.keyboard('{Escape}');
      document.body.removeEventListener('keydown', outer);
      expect(onEscape).toHaveBeenCalledTimes(1);
      expect(outer).not.toHaveBeenCalled();
    });
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

describe('duplicate option labels', () => {
  it('renders both options without a key warning', async () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {});
    setup(sess({}, [{ question: 'Dup?', multiSelect: false, allowFreeText: false, options: [{ label: 'Same' }, { label: 'Same' }] }]));
    expect(await screen.findAllByRole('radio', { name: /Same/ })).toHaveLength(2);
    expect(err.mock.calls.filter(([m]) => String(m).includes('same key'))).toEqual([]);
    err.mockRestore();
  });
});
