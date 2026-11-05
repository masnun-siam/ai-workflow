// jsdom lacks these; Radix, cmdk and the layout code expect them.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= RO as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= () => {};
window.matchMedia ??= ((q: string) => ({
  matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
  addListener() {}, removeListener() {}, dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;
// A loaded CI box can take longer than 1s to render a lazy page; findBy*/waitFor should not flake on that.
import { configure } from '@testing-library/react';
configure({ asyncUtilTimeout: 5000 });
