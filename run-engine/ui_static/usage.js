// Plan usage for every connected account: a compact header gauge (two hairline meters per account)
// that opens a popover with percentages, reset times and freshness.
import { h } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';

const html = htm.bind(h);
const POP = 'usage-pop';

export const level = (pct) => (pct >= 90 ? 'high' : pct >= 70 ? 'warn' : 'ok');

export function resetText(iso, nowMs = Date.now()) {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const mins = Math.round((t - nowMs) / 60000);
  if (mins <= 0) return 'now';
  if (mins < 60) return `in ${mins}m`;
  if (mins < 24 * 60) return `in ${Math.floor(mins / 60)}h ${mins % 60}m`;
  return new Date(t).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
}

// [{cmd, label, five, seven, error, at}] for accounts that have usage data or an error to show.
export function usageRows(usage, commands) {
  const label = (cmd) => (commands.find((c) => c.cmd === cmd) || {}).label || cmd;
  return Object.entries(usage || {})
    .map(([cmd, u]) => ({ cmd, label: label(cmd), five: u.five_hour, seven: u.seven_day, error: u.error, at: u.at }))
    .filter((r) => r.five || r.seven || r.error);
}

const ago = (at) => `${Math.max(0, Math.round((Date.now() / 1000 - at) / 60))}m`;
const pctOf = (w) => (w ? Math.max(0, Math.min(100, w.pct)) : 0);

function Meter({ w, name }) {
  return html`<span class="um" role="img" aria-label=${w ? `${name} ${Math.round(w.pct)}%` : `${name} unknown`}>
    <span class=${`um-fill um-${w ? level(w.pct) : 'none'}`} style=${`width:${pctOf(w)}%`}></span>
  </span>`;
}

function Line({ w, name }) {
  if (!w) return html`<div class="uline"><span class="uname">${name}</span><span class="note">no data</span></div>`;
  return html`<div class="uline">
    <span class="uname">${name}</span>
    <span class="ubar"><${Meter} w=${w} name=${name} /></span>
    <span class=${`upct u-${level(w.pct)}`}>${Math.round(w.pct)}%</span>
    <span class="ureset">${resetText(w.resets_at)}</span>
  </div>`;
}

export function UsageGauge({ usage, commands }) {
  const rows = usageRows(usage, commands);
  if (!rows.length) return null;
  const newest = Math.max(0, ...rows.map((r) => r.at || 0));
  const worst = Math.max(...rows.flatMap((r) => [pctOf(r.five), pctOf(r.seven)]));
  const summary = rows.map((r) => `${r.label}: 5h ${r.five ? Math.round(r.five.pct) + '%' : '?'}, 7d ${r.seven ? Math.round(r.seven.pct) + '%' : '?'}`).join('; ');
  return html`
    <button type="button" class=${`ugauge ug-${level(worst)}`} popovertarget=${POP} aria-label=${`Plan usage. ${summary}`} title=${summary}>
      ${rows.map((r) => html`<span class="ug-acct" key=${r.cmd}>
        <span class="ug-id" aria-hidden="true">${[...r.label][0]}</span>
        <span class="ug-bars" aria-hidden="true"><${Meter} w=${r.five} name="5h" /><${Meter} w=${r.seven} name="7d" /></span>
      </span>`)}
    </button>
    <div id=${POP} class="afk-pop usage-pop" popover="auto" role="dialog" aria-label="Plan usage">
      ${rows.map((r) => html`<section class="uacct" key=${r.cmd}>
        <h2>${r.label}</h2>
        <${Line} w=${r.five} name="5h" />
        <${Line} w=${r.seven} name="7d" />
        ${r.error && html`<p class="note">${r.error}${r.at ? `. Numbers are ${ago(r.at)} old.` : ''}</p>`}
      </section>`)}
      ${newest > 0 && html`<p class="note ufoot">Updated ${ago(newest)} ago</p>`}
    </div>`;
}
