import { h } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';

const html = htm.bind(h);

const APPROVAL = {
  APPROVED: ['approved', 'ok'],
  CHANGES_REQUESTED: ['changes requested', 'bad'],
  REVIEW_REQUIRED: ['review required', 'warn'],
};
const CI = { green: 'ci passing', red: 'ci failing', pending: 'ci running' };
const CI_TONE = { green: 'ok', red: 'bad', pending: 'warn' };

// Status chips for a card's `gh` block: [{text, tone}]. Order: issue, ci, approval.
export function ghChips(gh, labels = false) {
  if (!gh) return [];
  const chips = [];
  if (gh.issue && gh.issue.state) {
    const closed = gh.issue.state === 'CLOSED';
    chips.push({ text: 'issue ' + (closed ? 'closed' : 'open'), tone: closed ? 'ok' : 'neutral' });
    if (labels) for (const label of gh.issue.labels || []) chips.push({ text: label, tone: 'neutral' });
  }
  const pr = gh.pr;
  if (pr) {
    if (pr.state === 'MERGED' || pr.state === 'CLOSED') chips.push({ text: 'pr ' + pr.state.toLowerCase(), tone: pr.state === 'MERGED' ? 'ok' : 'bad' });
    else {
      if (pr.ci) chips.push({ text: CI[pr.ci], tone: CI_TONE[pr.ci] });
      const a = APPROVAL[pr.approval];
      chips.push(a ? { text: a[0], tone: a[1] } : { text: 'no review', tone: 'neutral' });
    }
  }
  return chips;
}

export function issueUrl(owner, repo, issue) {
  return `https://github.com/${owner}/${repo}/issues/${issue}`;
}

export function GhChips({ gh, labels }) {
  return ghChips(gh, labels).map((c) => html`<span class=${'chip gh-' + c.tone + (gh.stale ? ' gh-stale' : '')} title=${gh.stale ? 'GitHub status unknown, showing last known value' : ''}>${c.text}</span>`);
}

// Issue + PR links, rendered outside the card anchor (anchors can't nest).
export function GhLinks({ owner, repo, issue, pr, gh }) {
  const prUrl = (gh && gh.pr && gh.pr.url) || pr;
  const num = gh && gh.pr && gh.pr.number;
  return html`<div class="card-links">
    <a href=${issueUrl(owner, repo, issue)} target="_blank" rel="noopener noreferrer">Issue #${issue}</a>
    ${prUrl && html`<a href=${prUrl} target="_blank" rel="noopener noreferrer">PR${num ? ' #' + num : ''}</a>`}
  </div>`;
}

// Failing CI checks for the run header: [{name, link}] -> links.
export function FailingChecks({ gh }) {
  const failing = (gh && gh.pr && gh.pr.failing) || [];
  if (!failing.length) return null;
  return html`<p class="note gh-failing">Failing checks: ${failing.map((f, i) => html`${i ? ', ' : ''}${/^https:/.test(f.link || '') ? html`<a href=${f.link} target="_blank" rel="noopener noreferrer">${f.name}</a>` : f.name}`)}</p>`;
}

// Mirrors ui_cleanup.STALE_SECONDS: a session-less unfinished run may be a live CLI run until it goes quiet.
export const STALE_SECONDS = 3600;
export function quiet(updated, status) {
  return status !== 'escalated' && typeof updated === 'number' && Date.now() / 1000 - updated > STALE_SECONDS;
}
