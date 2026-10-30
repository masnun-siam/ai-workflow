import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScrollJump } from './ScrollJump';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function setup(scrollHeight: number, scrollTop = 0) {
  const el = document.createElement('div');
  el.id = 'main-content';
  document.body.appendChild(el);
  const dims = { scrollHeight, clientHeight: 500, scrollTop };
  for (const k of Object.keys(dims) as (keyof typeof dims)[]) {
    Object.defineProperty(el, k, { configurable: true, get: () => dims[k], set: (v) => { dims[k] = v; } });
  }
  el.scrollTo = vi.fn() as unknown as typeof el.scrollTo;
  render(<MemoryRouter><ScrollJump /></MemoryRouter>);
  const scrollTo = (top: number) => act(() => { dims.scrollTop = top; fireEvent.scroll(el); });
  return { el, scrollTo };
}
const top = () => screen.queryByRole('button', { name: 'Jump to top' });
const bottom = () => screen.queryByRole('button', { name: 'Jump to bottom' });

describe('ScrollJump', () => {
  afterEach(() => document.getElementById('main-content')?.remove());

  it('renders nothing when the page fits', () => {
    setup(500);
    expect(top()).toBeNull();
    expect(bottom()).toBeNull();
  });

  it('at the top shows only Jump to bottom, which scrolls smoothly to the end', () => {
    const { el } = setup(2000);
    expect(top()).toBeNull();
    fireEvent.click(bottom()!);
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 2000, behavior: 'smooth' });
  });

  it('in the middle shows both; at the end only Jump to top, which scrolls to 0', () => {
    const { el, scrollTo } = setup(2000);
    scrollTo(300);
    expect(top()).not.toBeNull();
    expect(bottom()).not.toBeNull();
    scrollTo(1500);
    expect(bottom()).toBeNull();
    fireEvent.click(top()!);
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });
  });

  it('jumps instantly under reduced motion', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }));
    const { el } = setup(2000);
    fireEvent.click(bottom()!);
    expect(el.scrollTo).toHaveBeenCalledWith({ top: 2000, behavior: 'auto' });
  });
});
