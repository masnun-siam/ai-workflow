import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import type { BootstrapRun } from '../api/types';
import { PhaseStrip } from './PhaseStrip';

const NAMES = ['audit', 'decide', 'constitution', 'guides', 'gates', 'docs'];
const run = (states: string[], state: BootstrapRun['state']): BootstrapRun => ({
  id: 'r1', repo: 'o/r', issue: 5, branch: 'b', state, error: null, created_at: '', updated_at: '',
  phases: NAMES.map((name, i) => ({ name, state: states[i] as never, session_id: states[i] === 'pending' ? null : `s${i}` })),
});
const draw = (r: BootstrapRun, here?: string) => render(<MemoryRouter><PhaseStrip run={r} here={here} /></MemoryRouter>);
afterEach(cleanup);

describe('PhaseStrip', () => {
  it('lists six phases in order with state words, links for started ones and one current step', () => {
    draw(run(['done', 'done', 'done', 'done', 'running', 'pending'], 'running'));
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual(['auditDone', 'decideDone', 'constitutionDone', 'guidesDone', 'gatesRunning', 'docsPending']);
    expect(within(items[0]).getByRole('link').getAttribute('href')).toBe('/sessions/s0');
    expect(within(items[5]).queryByRole('link')).toBeNull();
    expect(items.filter((li) => li.getAttribute('aria-current') === 'step').map((li) => li.textContent)).toEqual(['gatesRunning']);
  });
  it('marks the first pending phase of a waiting run and the failed one of a stopped run', () => {
    draw(run(['done', 'pending', 'pending', 'pending', 'pending', 'pending'], 'waiting'));
    expect(document.querySelector('[aria-current="step"]')?.textContent).toBe('decidePending');
    cleanup();
    draw(run(['done', 'done', 'failed', 'pending', 'pending', 'pending'], 'stopped'));
    expect(document.querySelector('[aria-current="step"]')?.textContent).toBe('constitutionFailed');
  });
  it('marks the here session as this session, without a link to itself', () => {
    draw(run(['done', 'done', 'done', 'done', 'running', 'pending'], 'running'), 's4');
    const items = screen.getAllByRole('listitem');
    expect(items[4].textContent).toBe('gates (this session)Running');
    expect(within(items[4]).queryByRole('link')).toBeNull();
    expect(within(items[3]).getByRole('link').getAttribute('href')).toBe('/sessions/s3');
  });
  it('marks no step on a finished run', () => {
    draw(run(Array(6).fill('done'), 'done'));
    expect(document.querySelector('[aria-current]')).toBeNull();
  });
});
