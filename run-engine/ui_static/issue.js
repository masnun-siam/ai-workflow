import { h } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { formatWhen } from './fmt.js';
import { issueUrl } from './ghstatus.js';
import { Peek, PeekLink, Md, Labels, Who } from './peek.js';

const html = htm.bind(h);

export const IssueLink = ({ owner, repo, issue, children, ...rest }) =>
  html`<${PeekLink} kind="issue" owner=${owner} repo=${repo} n=${issue} href=${issueUrl(owner, repo, issue)} ...${rest}>${children}<//>`;

export function stateLabel(d) {
  if (d.is_pr) return d.state === 'open' ? 'PR open' : 'PR closed';
  if (d.state === 'open') return 'Open';
  return d.state_reason === 'not_planned' ? 'Closed as not planned' : 'Closed';
}

const info = (d) => ({ title: d.title, state: stateLabel(d), stateClass: `iss-${d.state}`, url: d.url });

export const IssueDialog = ({ owner, repo, issue, onClose }) => html`
  <${Peek} api=${`/api/issues/${owner}/${repo}/${issue}`} refText=${`${owner}/${repo} #${issue}`} fallbackTitle=${`Issue #${issue}`}
    fallbackUrl=${issueUrl(owner, repo, issue)} info=${info} onClose=${onClose}>${(d) => html`<${IssueBody} d=${d} />`}<//>`;

function IssueBody({ d }) {
  const people = [`${d.author} opened ${formatWhen(d.created_at)}`, d.assignees.length && `assigned to ${d.assignees.join(', ')}`, d.milestone && `milestone ${d.milestone}`].filter(Boolean);
  const more = d.comment_count - d.comments.length;
  return html`<div class="iss-scroll" tabindex="0">
    <p class="iss-meta muted">${people.join(' · ')}</p>
    <${Labels} labels=${d.labels} />
    ${d.body_html ? html`<${Md} htmlText=${d.body_html} />` : html`<p class="muted">No description.</p>`}
    <h3 class="iss-comments-h">${d.comment_count === 0 ? 'No comments' : `${d.comment_count} comment${d.comment_count === 1 ? '' : 's'}`}</h3>
    ${d.comments.map((c) => html`<article class="iss-comment"><${Who} author=${c.author} at=${c.created_at} /><${Md} htmlText=${c.body_html} /></article>`)}
    ${more > 0 && html`<p class="muted">${more} more comment${more === 1 ? '' : 's'} on GitHub.</p>`}
  </div>`;
}
