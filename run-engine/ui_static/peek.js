import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { formatWhen } from './fmt.js';

const html = htm.bind(h);

const TTL = 60000;
const cache = new Map();

// Any view asks for a popup by event, so no props travel through the router. kind: 'issue' | 'pr'.
export const openPeek = (kind, owner, repo, n) => globalThis.dispatchEvent(new CustomEvent('aiw:peek', { detail: { kind, owner, repo, n } }));

// A link that opens the popup; Cmd/Ctrl/Shift/middle-click keep the plain new-tab behaviour.
export function PeekLink({ kind, owner, repo, n, href, children, ...rest }) {
  const onClick = (e) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    openPeek(kind, owner, repo, n);
  };
  return html`<a href=${href} target="_blank" rel="noopener noreferrer" onClick=${onClick} ...${rest}>${children}</a>`;
}

async function load(api, fresh) {
  const hit = cache.get(api);
  if (hit && !fresh && Date.now() - hit.at < TTL) return hit.data;
  const res = await fetch(api, { headers: { Accept: 'application/json' } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  cache.set(api, { at: Date.now(), data: body });
  return body;
}

export const Md = ({ htmlText }) => html`<div class="gh-md" dangerouslySetInnerHTML=${{ __html: htmlText }} />`;

export function Labels({ labels }) {
  if (!labels.length) return null;
  return html`<ul class="iss-labels" aria-label="Labels">${labels.map((l) => html`<li class="chip gh-label"><i style=${{ background: `#${l.color || '8791a1'}` }}></i>${l.name}</li>`)}</ul>`;
}

export const Who = ({ author, at, note }) => html`<div class="iss-who"><strong class="mono">${author}</strong>${note && html`<span class="iss-note">${note}</span>`}<time class="muted" dateTime=${at}>${formatWhen(at)}</time></div>`;

// The shared popup shell: loads `api`, shows head/title/footer, hands the data to `children(data)`.
// `info(data)` -> {title, state, stateClass, url}.
export class Peek extends Component {
  state = { data: null, error: '', busy: true };

  componentDidMount() {
    this.fetch(false);
    this.root?.querySelector('[data-autofocus]')?.focus();
  }

  componentWillUnmount() {
    this.gone = true;
  }

  fetch = async (fresh) => {
    this.setState({ busy: true, error: '' });
    try {
      const data = await load(this.props.api, fresh);
      if (!this.gone) this.setState({ data, busy: false });
    } catch (e) {
      if (!this.gone) this.setState({ busy: false, error: e.message });
    }
  };

  render({ refText, fallbackTitle, fallbackUrl, info, wide, onClose, children }, { data, error, busy }) {
    const i = data ? info(data) : { title: fallbackTitle, url: fallbackUrl };
    return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
      <div class=${`dialog issue${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="iss-title" ref=${(el) => { this.root = el; }}>
        <div class="iss-head">
          <div class="iss-ref mono">${refText}</div>
          ${data && html`<span class=${`iss-state ${i.stateClass}`}>${i.state}</span>`}
        </div>
        <h2 id="iss-title" class="iss-title">${i.title}</h2>
        ${data && children(data)}
        ${!data && html`<div class="iss-scroll" aria-busy=${busy}>
          ${busy && html`<p role="status" class="muted">Loading…</p>`}
          ${error && html`<p role="alert" class="error">${error} <button type="button" class="btn btn-sm" onClick=${() => this.fetch(true)}>Retry</button></p>`}
        </div>`}
        <div class="iss-foot">
          <button type="button" class="btn" disabled=${busy} onClick=${() => this.fetch(true)}>${busy && data ? 'Refreshing…' : 'Refresh'}</button>
          ${data && error && html`<span role="alert" class="error">${error}</span>`}
          <span class="spacer"></span>
          <button type="button" class="btn" onClick=${onClose}>Close <kbd>Esc</kbd></button>
          <a class="btn btn--primary" data-autofocus href=${i.url} target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>
        </div>
      </div>
    </div>`;
  }
}
