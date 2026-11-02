import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useListSelection, nextSelection } from './useListSelection';
import { useGlobalShortcuts, useAction, KeyScope } from '../shell/shortcuts';
import { PanelProvider, usePanel, type PanelTarget } from '../panels/PanelContext';
import { DetailPanel } from '../panels/DetailPanel';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../panels/WorkPanel', () => ({ WorkPanel: () => <PanelBody /> }));

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

const ran: string[] = [];
function PanelBody() {
  useAction({ key: 'm', label: 'panel m', run: () => ran.push('panel') });
  return null;
}

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
  it('arrows scroll the page unless focus is on a row; j still moves from anywhere', async () => {
    const u = userEvent.setup();
    render(ui({ keys: abc, onOpen: () => {} }));
    expect(fireEvent.keyDown(document.body, { key: 'ArrowDown' })).toBe(true);
    expect(selected()).toBeNull();
    await u.keyboard('j');
    expect(selected()).toBe(screen.getByText('a'));
    expect(fireEvent.keyDown(screen.getByText('a'), { key: 'ArrowDown' })).toBe(false);
    expect(selected()).toBe(screen.getByText('b'));
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

describe('panel follows the selection', () => {
  const pr = (n: number): PanelTarget => ({ kind: 'pr', repo: 'o/r', n });
  const targets: Record<string, PanelTarget | null> = { a: pr(1), b: pr(2), c: null };
  function Row({ k, selected }: { k: string; selected: boolean }) {
    useAction({ key: 'm', label: 'row m', run: () => ran.push('row') });
    return <>{k}{selected ? '*' : ''}</>;
  }
  function Probe() {
    const { target } = usePanel();
    return <output data-testid="t">{target && 'n' in target ? target.n : 'none'}</output>;
  }
  function Open() {
    const panel = usePanel();
    return <button onClick={() => panel.open(pr(1))}>open</button>;
  }
  function Fixture() {
    useGlobalShortcuts();
    const { rowProps, selected } = useListSelection({ keys: abc, onOpen: () => {}, panelTarget: (k) => targets[k] });
    return (
      <>
        <Open /><Probe />
        <ul>{abc.map((k) => <li key={k} {...rowProps(k)}><KeyScope level="row" active={selected === k}><Row k={k} selected={selected === k} /></KeyScope></li>)}</ul>
        <DetailPanel />
      </>
    );
  }
  const mount = () => render(<MemoryRouter><PanelProvider><Fixture /></PanelProvider></MemoryRouter>);
  const t = () => screen.getByTestId('t').textContent;

  it('J retargets the open panel, Esc closes it and keeps the row selected and focused', async () => {
    const u = userEvent.setup();
    mount();
    await u.keyboard('j');
    await u.click(screen.getByText('open'));
    expect(t()).toBe('1');
    await u.keyboard('j');
    expect(t()).toBe('2');
    expect(document.activeElement).toBe(screen.getByText('b*').closest('li'));
    await u.keyboard('{Escape}');
    expect(t()).toBe('none');
    expect(selected()).toBe(screen.getByText('b*').closest('li'));
    expect(document.activeElement).toBe(selected());
  });
  it('a row without a target closes the panel and keeps focus on the row', async () => {
    const u = userEvent.setup();
    mount();
    await u.keyboard('jj');
    await u.click(screen.getByText('open'));
    await u.keyboard('j');
    expect(t()).toBe('none');
    expect(document.activeElement).toBe(screen.getByText('c*').closest('li'));
  });
  it('J does not open a closed panel', async () => {
    const u = userEvent.setup();
    mount();
    await u.keyboard('jj');
    expect(t()).toBe('none');
  });
  it('panel keys beat the selected row\'s keys while the panel is open', async () => {
    const u = userEvent.setup();
    ran.length = 0;
    mount();
    await u.keyboard('j');
    await u.keyboard('m');
    expect(ran).toEqual(['row']);
    await u.click(screen.getByText('open'));
    await u.keyboard('m');
    expect(ran).toEqual(['row', 'panel']);
  });
});
