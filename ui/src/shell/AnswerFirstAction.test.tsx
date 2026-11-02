import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Palette } from '../palette/Palette';
import { AnswerFirstAction } from './AnswerFirstAction';

let sessions: unknown[] = [];
vi.mock('../api/hooks', () => {
  const q = { data: undefined };
  const m = { mutate: () => {} };
  return { useAfkStart: () => m, useAfkStop: () => m, useOpenItems: () => q, usePlanning: () => q, useDelivery: () => q, useSettings: () => q, useSessions: () => ({ data: { sessions } }) };
});
vi.mock('./useRepo', () => ({ useRepo: () => ({ repo: 'o/r', repos: [], setRepo: () => {}, link: (p: string) => p }) }));
vi.mock('../start/StartContext', () => ({ useStart: () => ({ open: () => {} }) }));
vi.mock('../panels/PanelContext', () => ({ usePanel: () => ({ open: () => {} }) }));

const Where = () => <p data-testid="at">{useLocation().pathname}</p>;
const s = (id: string, started_at: string, waiting = true, pending_question: unknown = { questions: [] }) => ({ id, started_at, waiting, pending_question });
const mount = () => render(<MemoryRouter><AnswerFirstAction /><Where /><Palette onClose={() => {}} /></MemoryRouter>);
const LABEL = 'Answer the first waiting question';

afterEach(cleanup);

describe('Answer the first waiting question', () => {
  it('opens the oldest waiting session', async () => {
    sessions = [s('new', '2026-11-02'), s('old', '2026-11-01'), s('idle', '2026-10-01', false, null)];
    mount();
    fireEvent.click(await screen.findByText(LABEL));
    expect(screen.getByTestId('at').textContent).toBe('/sessions/old');
  });

  it('is absent with no waiting session', async () => {
    sessions = [s('idle', '2026-10-01', false, null)];
    mount();
    await screen.findByText('Inbox');
    expect(screen.queryByText(LABEL)).toBeNull();
  });
});
