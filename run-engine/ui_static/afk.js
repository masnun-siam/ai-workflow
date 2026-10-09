// AFK mode (#178): the header control that starts/extends/ends autopilot, and the summary shown when it ends.
// The server runs the autopilot; this only shows its state (polled with /api/sessions) and posts to /api/afk.
import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { clockText } from './fmt.js';
import { toast } from './toast.js';

const html = htm.bind(h);

export const PRESETS = [[30, '30 min'], [60, '1 hour'], [120, '2 hours'], [240, '4 hours']];
const KIND = { answer: 'Answered', 'skip-ci': 'Skipped CI', retry: 'Retried' };

// "1:23:45" or "12:05" for the seconds left; "0:00" once over.
export function countdownText(sec) {
  const s = Math.max(0, Math.floor(sec));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
}

// Epoch seconds of the next local "HH:MM" (tomorrow when it already passed today), or null.
export function untilClock(value, now = new Date()) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(value || ''));
  if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) return null;
  const t = new Date(now);
  t.setHours(Number(m[1]), Number(m[2]), 0, 0);
  if (t <= now) t.setDate(t.getDate() + 1);
  return Math.floor(t.getTime() / 1000);
}

// Where a log entry links: its run when it has one, else its session.
export function entryHref(e) {
  const l = e && e.link;
  if (l && l.owner && l.repo && l.issue) return `#/run/${encodeURIComponent(l.owner)}/${encodeURIComponent(l.repo)}/${l.issue}`;
  return e && e.sid ? `#/session/${encodeURIComponent(e.sid)}` : null;
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

export async function afkPost(path, body = {}) {
  try {
    const res = await fetch(`/api/afk${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data;
    toast(data.error || `Autopilot request failed (HTTP ${res.status})`);
  } catch (e) {
    toast(`Autopilot request failed: ${e?.message || e}`);
  }
  return null;
}

const POP = 'afk-pop';

// Header button (off) or countdown chip (on); both open the same popover.
export class AfkControl extends Component {
  state = { now: Date.now(), clock: '' };

  componentDidMount() {
    this.timer = setInterval(() => this.props.afk?.active && this.setState({ now: Date.now() }), 1000);
    addEventListener('aiw:afk', this.open);
  }

  componentWillUnmount() {
    clearInterval(this.timer);
    removeEventListener('aiw:afk', this.open);
  }

  open = () => document.getElementById(POP)?.showPopover?.();

  close = () => document.getElementById(POP)?.hidePopover?.();

  go = async (path, body) => {
    const r = await afkPost(path, body);
    if (r) {
      this.close();
      this.props.onChange(r);
    }
  };

  startFor = (min) => this.go('', { until: Math.floor(Date.now() / 1000) + min * 60 });

  startUntil = (e) => {
    e.preventDefault();
    const until = untilClock(this.state.clock);
    if (until) this.go('', { until });
  };

  render({ afk }, { now, clock }) {
    const on = !!afk?.active;
    const left = on ? afk.until - now / 1000 : 0;
    const total = on ? afk.until - afk.started : 1;
    if (typeof document !== 'undefined') document.documentElement.style.setProperty('--afk-left', on ? String(Math.max(0, Math.min(1, left / total))) : '0');
    return html`
      ${on
        ? html`<button type="button" class="afk-chip" popovertarget=${POP} aria-label=${`Autopilot on, ${countdownText(left)} left${afk.held ? `, ${afk.held} held` : ''}`}>
            <span class="afk-pulse" aria-hidden="true"></span>Autopilot<span class="afk-time mono">${countdownText(left)}</span>
            ${afk.held > 0 && html`<span class="afk-held">${afk.held} held</span>`}
          </button>`
        : html`<button type="button" class="afk-btn" popovertarget=${POP} title="Hand the runs to autopilot while you're away">AFK</button>`}
      <div id=${POP} class="afk-pop" popover="auto" role="dialog" aria-labelledby="afk-pop-h">
        ${on
          ? html`<h2 id="afk-pop-h">Autopilot is on until ${clockText(afk.until)}</h2>
              <p class="note">${plural(afk.decisions, 'decision')} made so far. ${afk.held ? `${afk.held} waiting for you when you're back.` : 'Nothing waiting for you.'}</p>
              <div class="afk-row">
                <button type="button" class="btn" onClick=${() => this.go('', { until: afk.until + 1800 })}>+30 min</button>
                <button type="button" class="btn btn--primary" onClick=${() => this.go('/stop')}>I'm back</button>
              </div>`
          : html`<h2 id="afk-pop-h">Go AFK</h2>
              <p class="note">Until you're back, plans are approved, recommended answers are picked, grinds stuck on CI skip it, and failed runs are retried. Anything without a recommendation waits for you.</p>
              <div class="afk-row">
                ${PRESETS.map(([min, label]) => html`<button type="button" class="btn" onClick=${() => this.startFor(min)}>${label}</button>`)}
              </div>
              <form class="afk-until" onSubmit=${this.startUntil}>
                <label for="afk-clock">Until</label>
                <input id="afk-clock" type="time" class="field" value=${clock} onInput=${(e) => this.setState({ clock: e.target.value })} />
                <button type="submit" class="btn" disabled=${!untilClock(clock)}>Start</button>
              </form>`}
      </div>`;
  }
}

// Shown on every page after a window ends, until dismissed.
export function AfkSummary({ summary, onDismiss }) {
  const log = summary.log || [];
  return html`<section class="panel afk-summary" aria-labelledby="afk-sum-h">
    <div class="afk-sum-top">
      <div>
        <h2 id="afk-sum-h">While you were away</h2>
        <p class="note">Autopilot ran ${clockText(summary.started)}–${clockText(summary.ended)} and made ${plural(log.length, 'decision')}. ${summary.held ? `${plural(summary.held, 'thing')} still ${summary.held === 1 ? 'needs' : 'need'} you.` : 'Nothing is waiting for you.'}</p>
      </div>
      <button type="button" class="btn" onClick=${onDismiss}>Dismiss</button>
    </div>
    ${log.length > 0 && html`<ol class="afk-log">
      ${log.map((e, i) => {
        const href = entryHref(e);
        const what = e.link?.issue ? `${e.repo ? e.repo.split('/').pop() : ''}#${e.link.issue}` : (e.command || 'session');
        return html`<li key=${i}>
          <time class="mono">${clockText(e.at)}</time>
          <span class=${`afk-kind k-${e.kind}`}>${KIND[e.kind] || e.kind}</span>
          <span class="afk-what">${href ? html`<a href=${href}>${what}</a>` : what}</span>
          <span class="afk-q" title=${e.question}>${e.question}</span>
          <span class="afk-pick">${e.picked}</span>
        </li>`;
      })}
    </ol>`}
  </section>`;
}
