import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Menu } from '../components';
import { KeyScope, useAction, type KeyAction } from '../shell/shortcuts';
import { Palette } from './Palette';

vi.mock('../api/hooks', () => {
  const q = { data: undefined };
  const m = { mutate: () => {} };
  return { useAfkStart: () => m, useAfkStop: () => m, useOpenItems: () => q, usePlanning: () => q, useSessions: () => q, useDelivery: () => q };
});
vi.mock('../shell/useRepo', () => ({ useRepo: () => ({ repo: 'o/r', repos: [], setRepo: () => {}, link: (p: string) => p }) }));
vi.mock('../start/StartContext', () => ({ useStart: () => ({ open: () => {} }) }));
vi.mock('../panels/PanelContext', () => ({ usePanel: () => ({ open: () => {} }) }));

const Act = ({ a }: { a: KeyAction }) => (useAction(a), null);
const mount = (ui: ReactNode, onClose = vi.fn()) => {
  render(<MemoryRouter>{ui}<Palette onClose={onClose} /></MemoryRouter>);
  return onClose;
};
const headings = () => [...document.querySelectorAll('[cmdk-group-heading]')].map((h) => h.textContent);
const settle = () => screen.findByText('Inbox');

afterEach(cleanup);

describe('palette: Actions here', () => {
  it('lists page and row actions first, labelled as the button, and runs the chosen one', async () => {
    const run = vi.fn();
    const onClose = mount(
      <>
        <Act a={{ label: 'Resume', key: 'r', run }} />
        <KeyScope level="row" active name="PR #7"><Act a={{ label: 'Review and merge', key: 'm', run: () => {} }} /></KeyScope>
        <Act a={{ label: 'Run 2 more rounds', run: () => {} }} />
        <Act a={{ label: 'Stop', key: 's', run: () => {}, disabled: true }} />
      </>,
    );
    await settle();
    expect(headings()[0]).toBe('Actions here');
    const texts = [...document.querySelectorAll('[cmdk-item]')].map((i) => i.textContent);
    expect(texts.slice(0, 3)).toEqual(['PR #7: Review and merge (M)', 'Resume (R)', 'Run 2 more rounds']); // row before page
    expect(screen.queryByText(/Stop/)).toBeNull();
    fireEvent.click(screen.getByText('Resume (R)'));
    expect(run).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });

  it('is absent with nothing registered', async () => {
    mount(null);
    await settle();
    expect(headings()).not.toContain('Actions here');
  });

  it('filters Actions here like the other groups', async () => {
    mount(<Act a={{ label: 'Resume', key: 'r', run: () => {} }} />);
    await settle();
    fireEvent.change(screen.getByRole('combobox', { name: 'Search' }), { target: { value: 'resum' } });
    expect(screen.getByText('Resume (R)')).toBeTruthy();
    expect(screen.queryByText('Inbox')).toBeNull();
  });

  it('lists enabled Menu items with the paletteLabel prefix and no key', async () => {
    const onSelect = vi.fn();
    mount(<Menu paletteLabel="Resume on" trigger={<button>t</button>} items={[{ label: 'personal', onSelect }, { label: 'work', onSelect: () => {}, disabled: true }]} />);
    await settle();
    fireEvent.click(screen.getByText('Resume on personal'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Resume on work')).toBeNull();
  });
});
