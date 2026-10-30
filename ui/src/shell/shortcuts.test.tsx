import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ShellCtx } from './ShellContext';
import { KeyScope, ShortcutsDialog, useAction, useGlobalShortcuts, type KeyAction } from './shortcuts';

function Host({ children }: { children?: ReactNode }) {
  useGlobalShortcuts();
  return <>{children}</>;
}
const Act = ({ a }: { a: KeyAction | null }) => (useAction(a), null);
const mount = (ui: ReactNode) => render(<MemoryRouter><Host>{ui}</Host></MemoryRouter>);
const press = (key: string, init: KeyboardEventInit = {}, target: Element | Window = window) => fireEvent.keyDown(target, { key, ...init });

afterEach(cleanup);

describe('key registry', () => {
  it('runs a registered key and stops after unmount', () => {
    const run = vi.fn();
    const { unmount } = mount(<Act a={{ label: 'Merge', key: 'm', run }} />);
    press('m');
    expect(run).toHaveBeenCalledTimes(1);
    unmount();
    press('m');
    expect(run).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['input', () => document.body.appendChild(document.createElement('input'))],
    ['textarea', () => document.body.appendChild(document.createElement('textarea'))],
    ['select', () => document.body.appendChild(document.createElement('select'))],
    ['contenteditable', () => {
      const d = document.createElement('div');
      d.contentEditable = 'true';
      Object.defineProperty(d, 'isContentEditable', { value: true });
      return document.body.appendChild(d);
    }],
  ])('ignores a key typed in %s', (_n, make) => {
    const run = vi.fn();
    mount(<Act a={{ label: 'Merge', key: 'm', run }} />);
    const el = make();
    press('m', { bubbles: true }, el);
    expect(run).not.toHaveBeenCalled();
    el.remove();
  });

  it.each(['dialog', 'alertdialog', 'menu'])('ignores keys while a %s is open', (role) => {
    const run = vi.fn();
    mount(<><div role={role} /><Act a={{ label: 'Merge', key: 'm', run }} /></>);
    press('m');
    expect(run).not.toHaveBeenCalled();
  });

  it('ignores modifiers and key repeat', () => {
    const run = vi.fn();
    mount(<Act a={{ label: 'Merge', key: 'm', run }} />);
    press('m', { metaKey: true });
    press('m', { ctrlKey: true });
    press('m', { altKey: true });
    press('m', { repeat: true });
    expect(run).not.toHaveBeenCalled();
  });

  it('picks panel over row over page, primary over secondary, first on a tie', () => {
    const calls: string[] = [];
    const a = (id: string, primary = false): KeyAction => ({ label: id, key: 'm', primary, run: () => calls.push(id) });
    const { unmount } = mount(
      <>
        <Act a={a('page')} />
        <KeyScope level="row" active><Act a={a('row')} /></KeyScope>
        <KeyScope level="panel" active><Act a={a('panel')} /></KeyScope>
      </>,
    );
    press('m');
    unmount();
    mount(<><Act a={a('first')} /><Act a={a('second')} /><Act a={a('prim', true)} /></>);
    press('m');
    expect(calls).toEqual(['panel', 'prim']);
  });

  it('first registered wins a full tie', () => {
    const calls: string[] = [];
    mount(<><Act a={{ label: 'a', key: 'm', run: () => calls.push('first') }} /><Act a={{ label: 'b', key: 'm', run: () => calls.push('second') }} /></>);
    press('m');
    expect(calls).toEqual(['first']);
  });

  it('a disabled winner runs nothing and blocks lower ones', () => {
    const low = vi.fn();
    const hi = vi.fn();
    mount(
      <>
        <Act a={{ label: 'low', key: 'm', run: low }} />
        <KeyScope level="panel" active><Act a={{ label: 'hi', key: 'm', run: hi, disabled: true }} /></KeyScope>
      </>,
    );
    press('m');
    expect(hi).not.toHaveBeenCalled();
    expect(low).not.toHaveBeenCalled();
  });

  it('Enter on a focused button keeps its native activation; elsewhere it runs', () => {
    const run = vi.fn();
    mount(<><button>ok</button><Act a={{ label: 'Go', key: 'Enter', run }} /></>);
    press('Enter', {}, screen.getByText('ok'));
    expect(run).not.toHaveBeenCalled();
    press('Enter');
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('an inactive KeyScope registers nothing', () => {
    const run = vi.fn();
    mount(<KeyScope level="row" active={false}><Act a={{ label: 'Merge', key: 'm', run }} /></KeyScope>);
    press('m');
    expect(run).not.toHaveBeenCalled();
  });

  it('reserved keys are not action keys', () => {
    // @ts-expect-error 'j' is reserved
    const bad: KeyAction = { label: 'x', key: 'j', run: () => {} };
    mount(<Act a={bad} />);
    press('j');
  });

  it('the sheet lists global rows, then the registered key, without duplicates', async () => {
    function App() {
      const [open] = useState(true);
      return <><Act a={{ label: 'Merge it', key: 'm', run: () => {} }} /><Act a={{ label: 'Merge it', key: 'm', run: () => {} }} /><ShortcutsDialog open={open} onClose={() => {}} /></>;
    }
    mount(<App />);
    await act(async () => {});
    const keys = [...document.querySelectorAll('dt')].map((d) => d.textContent);
    expect(keys[0]).toBe('⌘K');
    expect(keys.filter((k) => k === 'M')).toHaveLength(1);
    expect(keys.indexOf('M')).toBeGreaterThan(keys.indexOf('⌘ Enter'));
    expect(screen.getByText('Merge it')).toBeTruthy();
  });

  describe('G then R', () => {
    const withShell = (open: () => void, ui: ReactNode) => render(
      <MemoryRouter>
        <ShellCtx.Provider value={{ openPalette: () => {}, openShortcuts: () => {}, openRepoSwitcher: open, registerRepoSwitcher: () => () => {} }}>
          <Host>{ui}</Host>
        </ShellCtx.Provider>
      </MemoryRouter>,
    );

    it('opens the switcher once and does not run the R action', () => {
      const open = vi.fn();
      const run = vi.fn();
      withShell(open, <Act a={{ label: 'Retry', key: 'r', run }} />);
      press('g');
      press('r');
      expect(open).toHaveBeenCalledTimes(1);
      expect(run).not.toHaveBeenCalled();
    });

    it('does nothing after the chord window', () => {
      vi.useFakeTimers();
      const open = vi.fn();
      withShell(open, null);
      press('g');
      vi.advanceTimersByTime(1000);
      press('r');
      vi.useRealTimers();
      expect(open).not.toHaveBeenCalled();
    });

    it('does nothing while typing or with a dialog open', () => {
      const open = vi.fn();
      withShell(open, <div role="dialog" />);
      press('g');
      press('r');
      cleanup();
      const input = document.body.appendChild(document.createElement('input'));
      withShell(open, null);
      press('g', { bubbles: true }, input);
      press('r', { bubbles: true }, input);
      input.remove();
      expect(open).not.toHaveBeenCalled();
    });

    it('is listed in the sheet', async () => {
      mount(<ShortcutsDialog open onClose={() => {}} />);
      await act(async () => {});
      expect(screen.getByText('G then R')).toBeTruthy();
    });
  });
});
