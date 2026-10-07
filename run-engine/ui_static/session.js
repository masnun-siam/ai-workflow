import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { mergeStream } from './run.js';
import { runLink, runHash } from './answer.js';
import { shortRepo } from './fmt.js';
import { LimitBanner } from './limits.js';

const html = htm.bind(h);

// Searchable text of one stream event (what the search box matches against).
export function eventText(e) {
  if (!e) return '';
  if (e.kind === 'text') return e.text || '';
  if (e.kind === 'tool') return `${e.name} ${e.input === undefined ? '' : JSON.stringify(e.input)}`;
  if (e.kind === 'result') return e.text || '';
  return '';
}

// Keeps each event's original index so list keys stay stable while filtering.
export function filterEvents(events, query) {
  const q = String(query || '').trim().toLowerCase();
  const all = (events || []).map((e, i) => ({ e, i }));
  return q ? all.filter(({ e }) => eventText(e).toLowerCase().includes(q)) : all;
}

// One-line gist of a tool call: its most telling argument, capped.
export function toolSummary(e, max = 110) {
  const input = e && e.input;
  let s = '';
  if (input && typeof input === 'object') {
    const key = ['command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt', 'skill'].find((k) => typeof input[k] === 'string' && input[k]);
    s = key ? input[key] : JSON.stringify(input);
  } else if (input !== undefined && input !== null) s = String(input);
  s = s.replace(/\s+/g, ' ').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

const isLive = (m) => !!m && (['starting', 'running'].includes(m.outcome) || (m.outcome === 'waiting' && !m.ended_at));

function Message({ e, open }) {
  if (e.kind === 'text') return html`<div class="msg msg-text"><div class="msg-role mono">claude</div><p>${e.text}</p></div>`;
  if (e.kind === 'tool') {
    return html`<details class="msg msg-tool" open=${open}>
      <summary><span class="tool-name mono">${e.name}</span><span class="tool-sum mono">${toolSummary(e)}</span></summary>
      <pre>${e.input === undefined ? '' : JSON.stringify(e.input, null, 2)}</pre>
    </details>`;
  }
  if (e.kind === 'result') {
    return html`<div class=${e.is_error ? 'msg msg-result error' : 'msg msg-result'}>
      <div class="msg-role mono">${e.is_error ? 'failed' : 'result'}${typeof e.cost === 'number' ? ` · $${e.cost.toFixed(2)}` : ''}</div>
      ${e.text ? html`<p>${e.text}</p>` : null}
    </div>`;
  }
  return null;
}

export class Session extends Component {
  state = { meta: null, notFound: false, retry: false, stream: { events: [], offset: 0 }, q: '', follow: true, openAll: false };
  stream = { events: [], offset: 0 }; // authoritative copy: poll URLs must see the latest offset
  live = null;

  componentDidMount() {
    const id = encodeURIComponent(this.props.id);
    this.stopMeta = poll(`/api/sessions/${id}`, 3000, (r) => {
      if (r.ok) {
        this.setState({ meta: r.data, notFound: false, retry: false });
        this.sync(r.data);
      } else if (r.status === 404) this.setState({ notFound: true, retry: false });
      else this.setState({ retry: true });
    });
  }

  componentDidUpdate() {
    if (this.state.follow && this.live && this.endEl) this.endEl.scrollIntoView({ block: 'end' });
  }

  componentWillUnmount() {
    this.gone = true;
    if (this.stopMeta) this.stopMeta();
    if (this.stopStream) this.stopStream();
  }

  take = (r) => {
    if (!r.ok || this.gone) return;
    const next = mergeStream(this.stream, r.data);
    if (next === this.stream) return;
    this.stream = next;
    this.setState({ stream: next });
  };

  url = () => `/api/sessions/${encodeURIComponent(this.props.id)}/stream?offset=${this.stream.offset}`;

  // Idempotent: acts only when liveness changes. Live sessions are tailed; a finished one is read once.
  sync(meta) {
    const live = isLive(meta);
    if (live === this.live) return;
    this.live = live;
    if (this.stopStream) this.stopStream();
    this.stopStream = null;
    if (live) this.stopStream = poll(this.url, 1000, this.take);
    else this.finalFetch();
  }

  async finalFetch() {
    let r;
    try {
      const res = await fetch(this.url(), { headers: { Accept: 'application/json' } });
      r = res.ok ? { ok: true, data: await res.json() } : { ok: false };
    } catch {
      r = { ok: false };
    }
    this.take(r);
  }

  render(_, { meta, notFound, retry, stream, q, follow, openAll }) {
    if (notFound) return html`<h1>Session not found</h1><p><a href="#/sessions">Back to sessions</a></p>`;
    if (!meta) return html`<h1>Transcript</h1><p role="status">Loading…</p>`;
    const shown = filterEvents(stream.events, q);
    const link = runLink(meta);
    const live = isLive(meta);
    return html`
      <section class="transcript">
        <div class="run-head">
          <div class="run-title">
            <div class="run-meta mono">${shortRepo(meta.repo)} · session ${String(meta.id).slice(-8)}</div>
            <h1>${meta.command || 'Session'}</h1>
          </div>
          <span class=${`chip chip-${meta.outcome}`}>${meta.outcome}</span>
          ${link && html`<a class="btn" href=${runHash(meta)}>Open run</a>`}
          ${meta.outcome === 'waiting' && html`<a class="btn btn--primary" href=${`#/answer/${encodeURIComponent(meta.id)}`}>Answer</a>`}
          ${retry && html`<span role="status" class="offline">Retrying…</span>`}
        </div>
        ${meta.outcome === 'limited' && html`<${LimitBanner} key=${meta.id} s=${meta} />`}
        <div class="tbar">
          <input type="search" data-search class="field" aria-label="Search transcript" placeholder="Search messages and tool calls" value=${q}
            onInput=${(e) => this.setState({ q: e.target.value })} />
          <span class="muted tcount" role="status">${q ? `${shown.length} of ${stream.events.length}` : `${stream.events.length} events`}</span>
          <button type="button" class="btn" onClick=${() => this.setState({ openAll: !openAll })}>${openAll ? 'Collapse tools' : 'Expand tools'}</button>
          ${live && html`<button type="button" class="btn" aria-pressed=${follow} onClick=${() => this.setState({ follow: !follow })}>Auto-scroll: ${follow ? 'on' : 'off'}</button>`}
        </div>
        <div class="panel tlog">
          ${shown.length
            ? shown.map(({ e, i }) => html`<${Message} key=${i} e=${e} open=${openAll} />`)
            : html`<p class="muted">${stream.events.length ? 'No events match your search' : live ? 'Waiting for output…' : 'No output recorded'}</p>`}
          ${live && html`<div class="streaming"><span class="pulse"></span>streaming events…</div>`}
          <div ref=${(el) => { this.endEl = el; }}></div>
        </div>
      </section>
    `;
  }
}
