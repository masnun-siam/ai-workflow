import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useTranscript } from '../api/hooks';
import type { StreamEvent } from '../api/types';
import * as md from '../lib/md';
import { shortPaths, Transcript } from './Transcript';

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

  it('folds a run of tool calls into one row that opens, and Show every step lists them flat', async () => {
    const tool = (c: string) => ({ kind: 'tool', name: 'Bash', input: { command: c } }) as StreamEvent;
    const evs = [text('hello'), tool('ls'), tool('pwd'), { kind: 'tool', name: 'Read', input: { file_path: 'a' } } as StreamEvent, text('bye')];
    render(<Transcript events={evs} live={false} working={false} />);
    expect(screen.getByText('3 steps')).toBeTruthy();
    expect(screen.getByText(/Bash ×2, Read/)).toBeTruthy();
    expect(screen.queryByText('ls')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /3 steps/ }));
    expect(screen.getByText('ls')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /3 steps/ }));
    await userEvent.click(screen.getByLabelText('Show every step'));
    expect(screen.queryByText('3 steps')).toBeNull();
    expect(screen.getByText('pwd')).toBeTruthy();
  });

  it('drops a final message the result repeats, and points up when the page shows the summary', () => {
    const evs = [text('all done'), { kind: 'result', text: 'all done', cost: 1 } as StreamEvent];
    render(<Transcript events={evs} live={false} working={false} summaryAbove={1} />);
    expect(screen.queryByText('all done')).toBeNull();
    expect(screen.getByText(/the summary is at the top/)).toBeTruthy();
  });

  it('cuts worktree and repo prefixes from tool paths', () => {
    expect(shortPaths('cd /u/x/.worktrees/12-a && cat /u/x/.worktrees/12-a/src/f.ts')).toBe('cd /u/x/.worktrees/12-a && cat src/f.ts');
    expect(shortPaths('Read /repo/src/f.ts', '/repo')).toBe('Read src/f.ts');
  });

  it('shows Jump to latest only while live and off the end; clicking scrolls and re-enables Auto-scroll', async () => {
    let cb: (en: { isIntersecting: boolean }[]) => void = () => {};
    vi.stubGlobal('IntersectionObserver', class { constructor(c: typeof cb) { cb = c; } observe() {} disconnect() {} });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const { rerender } = render(<Transcript events={[text('a')]} live working={false} />);
    expect(screen.queryByText('Jump to latest')).toBeNull();
    await act(async () => cb([{ isIntersecting: false }]));
    await userEvent.click(screen.getByLabelText('Auto-scroll'));
    expect((screen.getByLabelText('Auto-scroll') as HTMLInputElement).checked).toBe(false);
    scroll.mockClear();
    await userEvent.click(screen.getByText('Jump to latest'));
    expect(scroll).toHaveBeenCalled();
    expect((screen.getByLabelText('Auto-scroll') as HTMLInputElement).checked).toBe(true);
    rerender(<Transcript events={[text('a')]} live={false} working={false} />);
    expect(screen.queryByText('Jump to latest')).toBeNull();
  });
});
