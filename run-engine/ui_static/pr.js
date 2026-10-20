import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { formatWhen } from './fmt.js';
import { Peek, PeekLink, Md, Labels, Who } from './peek.js';

const html = htm.bind(h);

const PR_URL = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/;

// A PR link that opens the popup; a URL that is not a GitHub PR stays a plain new-tab link.
export function PrLink({ url, children, ...rest }) {
  const m = PR_URL.exec(url || '');
  if (!m) return html`<a href=${url} target="_blank" rel="noopener noreferrer" ...${rest}>${children}</a>`;
  return html`<${PeekLink} kind="pr" owner=${m[1]} repo=${m[2]} n=${m[3]} href=${url} ...${rest}>${children}<//>`;
}

const STATE = { open: ['PR open', 'iss-open'], draft: ['Draft', 'iss-draft'], merged: ['Merged', 'iss-merged'], closed: ['PR closed', 'iss-declined'] };
const info = (d) => ({ title: d.title, state: STATE[d.state]?.[0] || d.state, stateClass: STATE[d.state]?.[1] || '', url: d.url });

const VERDICT = { APPROVED: ['approved', 'ok'], CHANGES_REQUESTED: ['requested changes', 'bad'], COMMENTED: ['reviewed', ''], DISMISSED: ['dismissed review', ''] };
const FILE_MARK = { added: ['new', 'ok'], removed: ['deleted', 'bad'], renamed: ['renamed', ''] };

export const PrDialog = ({ owner, repo, pr, onClose }) => html`
  <${Peek} api=${`/api/pulls/${owner}/${repo}/${pr}`} refText=${`${owner}/${repo} #${pr}`} fallbackTitle=${`Pull request #${pr}`}
    fallbackUrl=${`https://github.com/${owner}/${repo}/pull/${pr}`} info=${info} wide onClose=${onClose}>${(d) => html`<${PrBody} d=${d} />`}<//>`;

const TABS = (d) => [
  ['overview', 'Overview'],
  ['conversation', `Conversation${d.conversation.length ? ` ${d.conversation.length}` : ''}`],
  ['files', `Files ${d.file_count}`],
  ['commits', `Commits ${d.commit_count}`],
];

class PrBody extends Component {
  state = { tab: 'overview' };

  render({ d }, { tab }) {
    return html`<div class="pk-tabs" role="tablist" aria-label="Pull request">
        ${TABS(d).map(([k, label]) => html`<button type="button" role="tab" id=${`pk-${k}`} aria-controls="pk-panel" aria-selected=${tab === k} onClick=${() => this.setState({ tab: k })}>${label}</button>`)}
      </div>
      <div class="iss-scroll" role="tabpanel" id="pk-panel" aria-labelledby=${`pk-${tab}`} tabindex="0">
        ${tab === 'overview' && html`<${Overview} d=${d} />`}
        ${tab === 'conversation' && html`<${Conversation} d=${d} />`}
        ${tab === 'files' && html`<${Files} d=${d} />`}
        ${tab === 'commits' && html`<${Commits} d=${d} />`}
      </div>`;
  }
}

function Overview({ d }) {
  const people = [`${d.author} opened ${formatWhen(d.created_at)}`, d.assignees.length && `assigned to ${d.assignees.join(', ')}`, d.milestone && `milestone ${d.milestone}`].filter(Boolean);
  return html`
    <p class="pk-branch mono"><span>${d.head}</span> into <span>${d.base}</span><b class="pk-add">+${d.additions}</b><b class="pk-del">−${d.deletions}</b></p>
    <p class="iss-meta muted">${people.join(' · ')}</p>
    <${Labels} labels=${d.labels} />
    <${Checks} checks=${d.checks} />
    ${d.body_html ? html`<${Md} htmlText=${d.body_html} />` : html`<p class="muted">No description.</p>`}`;
}

const CHECK_TEXT = { green: 'passed', red: 'failed', pending: 'running' };

function Checks({ checks }) {
  if (!checks || !checks.length) return null;
  const bad = checks.filter((c) => c.bucket === 'red').length;
  const wait = checks.filter((c) => c.bucket === 'pending').length;
  const head = bad ? `${bad} of ${checks.length} checks failing` : wait ? `${wait} of ${checks.length} checks running` : `All ${checks.length} checks passing`;
  return html`<details class="pk-checks" open=${bad > 0}>
    <summary class=${`pk-ck-${bad ? 'red' : wait ? 'pending' : 'green'}`}>${head}</summary>
    <ul>${checks.map((c) => html`<li><i class=${`pk-dot pk-ck-${c.bucket}`} aria-hidden="true"></i>
      ${/^https:/.test(c.link || '') ? html`<a href=${c.link} target="_blank" rel="noopener noreferrer">${c.name}</a>` : c.name}
      <span class="muted">${CHECK_TEXT[c.bucket]}</span></li>`)}</ul>
  </details>`;
}

function Conversation({ d }) {
  if (!d.conversation.length) return html`<p class="muted">No comments or reviews yet.</p>`;
  return d.conversation.map((c) => {
    const v = c.kind === 'review' ? VERDICT[c.verdict] || [c.verdict.toLowerCase(), ''] : null;
    return html`<article class=${`iss-comment${v && v[1] ? ` pk-${v[1]}` : ''}`}>
      <${Who} author=${c.author} at=${c.at} note=${v && v[0]} />
      ${c.body_html && html`<${Md} htmlText=${c.body_html} />`}
    </article>`;
  });
}

function Commits({ d }) {
  const more = d.commit_count - d.commits.length;
  return html`<ul class="pk-commits">${d.commits.map((c) => html`<li><span class="pk-sha mono">${c.sha}</span><span class="pk-subj">${c.subject}</span><span class="muted">${c.author} · ${formatWhen(c.at)}</span></li>`)}</ul>
    ${more > 0 && html`<p class="muted">${more} more commit${more === 1 ? '' : 's'} on GitHub.</p>`}`;
}

function Files({ d }) {
  const more = d.file_count - d.files.length;
  return html`<p class="muted pk-total">${d.file_count} file${d.file_count === 1 ? '' : 's'} changed <b class="pk-add">+${d.additions}</b> <b class="pk-del">−${d.deletions}</b></p>
    <div class="pk-files">${d.files.map((f) => html`<${FileRow} key=${f.name} f=${f} />`)}</div>
    ${more > 0 && html`<p class="muted">${more} more file${more === 1 ? '' : 's'} on GitHub.</p>`}`;
}

// Opening a row is what renders its patch, so a 100-file PR costs nothing until you look.
class FileRow extends Component {
  state = { open: false };

  render({ f }, { open }) {
    const mark = FILE_MARK[f.status];
    return html`<details class="pk-file" onToggle=${(e) => this.setState({ open: e.currentTarget.open })}>
      <summary><span class="pk-name mono">${f.from ? `${f.from} → ${f.name}` : f.name}</span>
        ${mark && html`<span class=${`pk-mark ${mark[1]}`}>${mark[0]}</span>`}
        <b class="pk-add">+${f.additions}</b><b class="pk-del">−${f.deletions}</b></summary>
      ${open && (f.patch
        ? html`<pre class="pk-diff" tabindex="0">${f.patch.split('\n').map((line) => html`<span class=${`ln ${line[0] === '+' ? 'ln-add' : line[0] === '-' ? 'ln-del' : line[0] === '@' ? 'ln-hunk' : ''}`}>${line || ' '}</span>`)}</pre>`
        : html`<p class="muted pk-nodiff">${f.patch_cut ? 'This diff is too large to show here.' : 'No text diff for this file (binary or empty).'} Use Open on GitHub to see it.</p>`)}
    </details>`;
  }
}
