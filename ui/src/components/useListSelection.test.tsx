import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useListSelection, nextSelection } from './useListSelection';
import { useGlobalShortcuts } from '../shell/shortcuts';
import { MemoryRouter } from 'react-router-dom';

describe('nextSelection', () => {
  const abc = ['a', 'b', 'c'];
  it('keeps the key and moves its index', () => expect(nextSelection({ key: 'b', index: 1 }, ['x', 'a', 'b'])).toEqual({ key: 'b', index: 2 }));
  it('takes the same index when the key is removed in the middle', () => expect(nextSelection({ key: 'b', index: 1 }, ['a', 'c'])).toEqual({ key: 'c', index: 1 }));
  it('takes the new last row when removed at the end', () => expect(nextSelection({ key: 'c', index: 2 }, ['a', 'b'])).toEqual({ key: 'b', index: 1 }));
  it('clears when emptied or unselected', () => {
    expect(nextSelection({ key: 'a', index: 0 }, [])).toBeNull();
    expect(nextSelection(null, abc)).toBeNull();
  });
});

function List({ keys, onOpen, reset }: { keys: string[]; onOpen: (k: string) => void; reset?: unknown }) {
  const { rowProps } = useListSelection({ keys, onOpen, reset });
  return (
    <ul>
      {keys.map((k) => <li key={k} {...rowProps(k)}>{k}</li>)}
    </ul>
  );
}
function Page(p: Parameters<typeof List>[0]) {
  useGlobalShortcuts();
  return <><input aria-label="field" /><List {...p} /></>;
}
const ui = (p: Parameters<typeof List>[0]) => <MemoryRouter><Page {...p} /></MemoryRouter>;
const selected = () => document.querySelector('[data-selected]');
const abc = ['a', 'b', 'c'];

afterEach(cleanup);

describe('useListSelection', () => {
  it('the first key selects the first row; J J selects the second, which is focused', async () => {
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen: () => {} }));
    expect(selected()).toBeNull();
    await u.keyboard('jj');
    expect(selected()).toBe(screen.getByText('b'));
    expect(document.activeElement).toBe(screen.getByText('b'));
    await u.keyboard('jk');
    expect(selected()).toBe(screen.getByText('b'));
  });
  it('stops at the ends', async () => {
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen: () => {} }));
    await u.keyboard('k');
    expect(selected()).toBe(screen.getByText('a'));
    await u.keyboard('kk');
    expect(selected()).toBe(screen.getByText('a'));
    await u.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}j');
    expect(selected()).toBe(screen.getByText('c'));
  });
  it('ignores key repeat', async () => {
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen: () => {} }));
    await u.keyboard('j');
    await u.keyboard('{j>3/}');
    expect(selected()).toBe(screen.getByText('b'));
  });
  it('selects on click and opens on Enter', async () => {
    const onOpen = vi.fn();
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen }));
    await u.click(screen.getByText('c'));
    expect(selected()).toBe(screen.getByText('c'));
    await u.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith('c');
  });
  it('keeps the index when the selected row disappears', async () => {
    const u = userEvent.setup();
    const { rerender } = render(ui({ keys: abc, onOpen: () => {} }));
    await u.keyboard('jj');
    rerender(ui({ keys: ['a', 'c'], onOpen: () => {} }));
    expect(selected()).toBe(screen.getByText('c'));
    rerender(ui({ keys: [], onOpen: () => {} }));
    expect(selected()).toBeNull();
  });
  it('clears when reset changes', async () => {
    const u = userEvent.setup();
    const { rerender } = render(ui({ keys: abc, onOpen: () => {}, reset: 'x' }));
    await u.keyboard('j');
    rerender(ui({ keys: abc, onOpen: () => {}, reset: 'y' }));
    expect(selected()).toBeNull();
  });
  it('does nothing while typing in a field', async () => {
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen: () => {} }));
    await u.click(screen.getByLabelText('field'));
    await u.keyboard('jk');
    expect(selected()).toBeNull();
  });
});
