import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTranscript } from '../api/hooks';
import type { StreamEvent } from '../api/types';
import * as md from '../lib/md';
import { Transcript } from './Transcript';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const text = (t: string): StreamEvent => ({ kind: 'text', text: t }) as StreamEvent;

function Probe({ id }: { id: string }) {
  const { events, error } = useTranscript(id, false);
  return <p data-testid="out">{events.map((e) => String(e.text)).join(',')}|{error ? 'err' : 'ok'}</p>;
}

describe('useTranscript stale guard', () => {
  it('ignores a late response (and a late failure) from the previous session', async () => {
    const late: Record<string, (r: Response | Error) => void> = {};
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      const sid = /sessions\/(\w+)\/stream/.exec(String(url))![1];
      if (sid === 'b') return Promise.resolve(reply({ events: [text('b1')], offset: 5 }));
      return new Promise((res, rej) => (late[sid] = (r) => (r instanceof Error ? rej(r) : res(r))));
    }));
    const { rerender } = render(<Probe id="a" />);
    rerender(<Probe id="b" />);
    await screen.findByText('b1|ok');
    await act(async () => late.a(reply({ events: [text('a1')], offset: 9 })));
    expect(screen.getByTestId('out').textContent).toBe('b1|ok');
    await act(async () => late.a(new Error('boom')));
    expect(screen.getByTestId('out').textContent).toBe('b1|ok');
  });
});

describe('Transcript', () => {
  it('renders markdown only for the new event when one is appended', () => {
    const spy = vi.spyOn(md, 'mdToHtml');
    const evs = [text('one'), text('two'), text('three')];
    const { rerender } = render(<Transcript events={evs} live={false} working={false} />);
    spy.mockClear();
    rerender(<Transcript events={[...evs, text('four')]} live={false} working={false} />);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('caps to the last 500 events, reveals the rest on demand, and search covers all', async () => {
    const evs = Array.from({ length: 502 }, (_, i) => text(`ev${i}`));
    render(<Transcript events={evs} live={false} working={false} />);
    expect(screen.queryByText('ev0')).toBeNull();
    expect(screen.getByText('ev501')).toBeTruthy();
    await userEvent.type(screen.getByLabelText('Search the transcript'), 'ev0');
    expect(screen.getByText('ev0')).toBeTruthy();
    await userEvent.clear(screen.getByLabelText('Search the transcript'));
    await userEvent.click(screen.getByRole('button', { name: /Show earlier events/ }));
    expect(screen.getByText('ev0')).toBeTruthy();
  });
});
