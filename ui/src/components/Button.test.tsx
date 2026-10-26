import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState, type ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { KeyScope, useActions, useGlobalShortcuts } from '../shell/shortcuts';
import { Button, LinkButton } from './Button';
import { Dialog } from './Dialog';
import { Menu } from './Menu';

function Host({ children }: { children?: ReactNode }) {
  useGlobalShortcuts();
  const labels = useActions().map((a) => a.label).join('|');
  return <><span data-testid="reg">{labels}</span>{children}</>;
}
const mount = (ui: ReactNode) => render(<MemoryRouter><Host>{ui}</Host></MemoryRouter>);
const press = (key: string, target: Element | Window = window) => fireEvent.keyDown(target, { key, bubbles: true });
const registered = async () => {
  await act(async () => {});
  return screen.getByTestId('reg').textContent;
};

afterEach(cleanup);

describe('Button shortcut', () => {
  it('clicks on its key and shows badge, aria-keyshortcuts and tooltip', async () => {
    const onClick = vi.fn();
    mount(<Button shortcut="m" onClick={onClick}>Merge…</Button>);
    press('m');
    expect(onClick).toHaveBeenCalledTimes(1);
    const b = screen.getByRole('button', { name: /Merge/ });
    const badge = b.querySelector('.kbd.hide-sm')!;
    expect(badge.textContent).toBe('M');
    expect(badge.getAttribute('aria-hidden')).toBe('true');
    expect(b.getAttribute('aria-keyshortcuts')).toBe('M');
    expect(b.title).toBe('Shortcut: M');
    expect(await registered()).toBe('Merge…');
  });

  it('appends the key to an existing tooltip', () => {
    mount(<Button shortcut="m" title="Merge it">Merge</Button>);
    expect(screen.getByRole('button').title).toBe('Merge it (M)');
  });

  it('ignores a disabled button and a key typed in a field', () => {
    const onClick = vi.fn();
    const { rerender } = mount(<><input aria-label="f" /><Button shortcut="m" disabled onClick={onClick}>Merge</Button></>);
    press('m');
    rerender(<MemoryRouter><Host><input aria-label="f" /><Button shortcut="m" onClick={onClick}>Merge</Button></Host></MemoryRouter>);
    press('m', screen.getByLabelText('f'));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('stops reacting after unmount', () => {
    const onClick = vi.fn();
    function Toggle() {
      const [on, set] = useState(true);
      return <>{on && <Button shortcut="m" onClick={onClick}>Merge</Button>}<button onClick={() => set(false)}>hide</button></>;
    }
    mount(<Toggle />);
    fireEvent.click(screen.getByText('hide'));
    press('m');
    expect(onClick).not.toHaveBeenCalled();
  });

  it('registers nothing in an inactive KeyScope, with noAction, in a Dialog or as a Menu trigger', async () => {
    const onClick = vi.fn();
    mount(
      <>
        <KeyScope level="row" active={false}><Button shortcut="m" onClick={onClick}>Row</Button></KeyScope>
        <Button shortcut="e" noAction onClick={onClick}>Chrome</Button>
        <Dialog open onOpenChange={() => {}} title="D"><Button shortcut="r" onClick={onClick}>InDialog</Button></Dialog>
        <Menu trigger={<Button shortcut="s">Trigger</Button>} items={[]} />
      </>,
    );
    expect(await registered()).toBe('');
    press('m');
    press('e');
    expect(onClick).not.toHaveBeenCalled();
  });

  it('LinkButton navigates on its key', () => {
    render(
      <MemoryRouter>
        <Host>
          <LinkButton shortcut="o" to="/there">Open</LinkButton>
          <Routes><Route path="/there" element={<p>arrived</p>} /></Routes>
        </Host>
      </MemoryRouter>,
    );
    press('o');
    expect(screen.getByText('arrived')).toBeTruthy();
  });
});
