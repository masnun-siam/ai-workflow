// Port of the old UI markdown renderer: same escaping, same output. Only http(s) URLs become links.

type Stream = { events: unknown[]; offset: number };
/** Drops responses whose offset is not past ours, so overlapping polls never duplicate events. */
export function mergeStream<T extends Stream>(state: T, resp: { events?: unknown[]; offset?: number } | null): T {
  if (!resp || !Array.isArray(resp.events) || !((resp.offset as number) > state.offset)) return state;
  return { events: state.events.concat(resp.events), offset: resp.offset as number } as T;
}

const esc = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// Runs on already-escaped text, so it must not swallow an escaped quote or angle bracket.
const URL_RE = /https?:\/\/(?:(?!&(?:quot|#39|gt|lt);)[^\s<])+/g;

function inline(s: string): string {
  // Code spans are lifted out first so bold can wrap them and nothing inside them is touched.
  const codes: string[] = [];
  const links: [string, string][] = [];
  const lifted = s.replace(/`([^`]+)`/g, (_, c: string) => `\u0000${codes.push(c) - 1}\u0000`);
  // [text](url) is lifted too, so URL_RE never re-links it; non-http(s) targets (repo-relative paths) keep just the text.
  return lifted
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t: string, u: string) =>
      /^https?:\/\//.test(u) ? `\u0001${links.push([u, t]) - 1}\u0001` : t)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>')
    .replace(URL_RE, (u) => {
      const href = u.replace(/[.,;:!?)\]}]+$/, '');
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>${u.slice(href.length)}`;
    })
    .replace(/\u0001(\d+)\u0001/g, (_, i: string) => `<a href="${links[Number(i)][0]}" target="_blank" rel="noopener noreferrer">${links[Number(i)][1]}</a>`)
    .replace(/\u0000(\d+)\u0000/g, (_, i: string) => `<code>${codes[Number(i)]}</code>`);
}

// Escape first, then transform: every tag in the output is one we emit here.
export function mdToHtml(md: unknown): string {
  if (!md) return '';
  const out: string[] = [];
  let para: string[] = [];
  let list: 'ul' | 'ol' | null = null; // outermost
  let base = 0; // indent of the outermost list
  const nest: { kind: 'ul' | 'ol'; indent: number }[] = [];
  let fence: string[] | null = null;
  let lang = '';
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
    while (nest.length) out.push(`</${nest.pop()!.kind}></li>`);
    if (list) out.push(`</${list}>`);
    list = null;
  };
  const lines = esc(String(md)).split('\n');
  const cells = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n];
    if (fence) {
      if (/^\s*```/.test(line)) {
        out.push(lang === 'mermaid' ? `<pre class="mermaid">${fence.join('\n')}</pre>` : `<pre><code>${fence.join('\n')}</code></pre>`);
        fence = null;
      } else fence.push(line);
      continue;
    }
    let m: RegExpExecArray | null;
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[n + 1] ?? '')) {
      flush();
      const row = (l: string, t: string) => `<tr>${cells(l).map((c) => `<${t}>${inline(c)}</${t}>`).join('')}</tr>`;
      const body: string[] = [];
      for (n += 2; n < lines.length && /^\s*\|/.test(lines[n]); n++) body.push(row(lines[n], 'td'));
      n--;
      out.push(`<table><thead>${row(line, 'th')}</thead><tbody>${body.join('')}</tbody></table>`);
    } else if ((m = /^\s*```\s*(\w*)/.exec(line))) {
      flush();
      lang = m[1];
      fence = [];
    } else if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
      flush();
      out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
    } else if ((m = /^(\s*)(?:([-*])|\d+\.)\s+(.*)$/.exec(line))) {
      if (para.length) flush(); // a list may start right under a paragraph line
      const kind: 'ul' | 'ol' = m[2] ? 'ul' : 'ol';
      const indent = m[1].length;
      if (list && !nest.length && kind !== list && indent <= base) flush();
      if (list && indent > (nest.length ? nest[nest.length - 1].indent : base) && out[out.length - 1].endsWith('</li>')) {
        out.push(out.pop()!.slice(0, -5), `<${kind}>`); // reopen the parent item around a nested list
        nest.push({ kind, indent });
      } else {
        while (nest.length && indent < nest[nest.length - 1].indent) out.push(`</${nest.pop()!.kind}></li>`);
        if (!list) {
          out.push(`<${kind}>`);
          list = kind;
          base = indent;
        }
      }
      out.push(`<li>${inline(m[3])}</li>`);
    } else if (!line.trim()) flush();
    else {
      if (list) flush();
      para.push(line.trim());
    }
  }
  if (fence) out.push(`<pre><code>${(fence as string[]).join('\n')}</code></pre>`);
  flush();
  return out.join('\n');
}
