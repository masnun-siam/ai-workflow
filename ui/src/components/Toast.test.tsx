import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Toaster, toast } from './Toast';

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  act(() => { vi.runAllTimers(); });
  vi.useRealTimers();
  cleanup();
});

const show = (msg: string, o?: Parameters<typeof toast>[1]) => {
  render(<Toaster />);
  act(() => { toast(msg, o); });
  return screen.getByText(msg).closest('.toast') as HTMLElement;
};
const wait = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

describe('Toast', () => {
  it('dismisses after its duration', () => {
    show('plain');
    wait(4199);
    expect(screen.queryByText('plain')).not.toBeNull();
    wait(2);
    expect(screen.queryByText('plain')).toBeNull();
  });

  it('keeps action and error toasts for 7 s', () => {
    show('err', { tone: 'bad' });
    wait(6999);
    expect(screen.queryByText('err')).not.toBeNull();
    wait(2);
    expect(screen.queryByText('err')).toBeNull();
  });

  it('stays while hovered and restarts its timer on leave', () => {
    const el = show('hover');
    fireEvent.mouseEnter(el);
    wait(20000);
    expect(screen.queryByText('hover')).not.toBeNull();
    fireEvent.mouseLeave(el);
    wait(4199);
    expect(screen.queryByText('hover')).not.toBeNull();
    wait(2);
    expect(screen.queryByText('hover')).toBeNull();
  });

  it('stays while focus is inside and restarts on blur', () => {
    const el = show('focus', { action: { label: 'Undo', onClick: () => {} } });
    fireEvent.focus(el);
    wait(20000);
    expect(screen.queryByText('focus')).not.toBeNull();
    fireEvent.blur(el);
    wait(7001);
    expect(screen.queryByText('focus')).toBeNull();
  });
});
