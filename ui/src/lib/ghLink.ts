import type { PanelTarget } from '../panels/PanelContext';

/** The panel target for a GitHub issue or PR URL, else null. `/pull/<n>/files` and other subpaths stay external. */
export function ghTarget(href: string): PanelTarget | null {
  const m = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(issues|pull)\/(\d+)\/?(?:[?#].*)?$/.exec(href);
  return m ? { kind: m[2] === 'pull' ? 'pr' : 'issue', repo: m[1], n: Number(m[3]) } : null;
}
