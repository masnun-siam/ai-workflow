import { h } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { linkParts } from './fmt.js';

const html = htm.bind(h);

// Plain text with http(s) URLs turned into links that open in a new tab.
export function Linked({ text }) {
  return linkParts(text).map((p) => (typeof p === 'string' ? p : html`<a href=${p.href} target="_blank" rel="noopener noreferrer">${p.href}</a>`));
}
