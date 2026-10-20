// Drops responses whose offset is not past ours, so overlapping polls never duplicate events.
export function mergeStream(state, resp) {
  if (!resp || !Array.isArray(resp.events) || !(resp.offset > state.offset)) return state;
  return { events: state.events.concat(resp.events), offset: resp.offset };
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// Runs on already-escaped text, so it must not swallow an escaped quote or angle bracket.
const URL = /https?:\/\/(?:(?!&(?:quot|#39|gt|lt);)[^\s<])+/g;

function inline(s) {
  // Code spans are lifted out first so bold can wrap them (`**use `x` here**`) and nothing inside them is touched.
  const codes = [];
  const lifted = s.replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  return lifted
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(URL, (u) => {
      const href = u.replace(/[.,;:!?)\]}]+$/, '');
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>${u.slice(href.length)}`;
    })
    .replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

// Escape first, then transform: every tag in the output is one we emit here. Only http(s) URLs become links.
export function mdToHtml(md) {
  if (!md) return '';
  const out = [];
  let para = [];
  let list = null; // 'ul' | 'ol' (outermost)
  let base = 0; // indent of the outermost list
  const nest = []; // open nested lists: [{ kind, indent }]
  let fence = null;
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
    while (nest.length) out.push(`</${nest.pop().kind}></li>`);
    if (list) out.push(`</${list}>`);
    list = null;
  };
  for (const line of esc(String(md)).split('\n')) {
    if (fence) {
      if (/^\s*```/.test(line)) {
        out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
        fence = null;
      } else fence.push(line);
      continue;
    }
    let m;
    if (/^\s*```/.test(line)) {
      flush();
      fence = [];
    } else if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
      flush();
      out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
    } else if ((m = /^(\s*)(?:([-*])|\d+\.)\s+(.*)$/.exec(line))) {
      if (para.length) flush(); // a list may start right under a paragraph line ("**Next:**\n- a")
      const kind = m[2] ? 'ul' : 'ol';
      const indent = m[1].length;
      if (list && !nest.length && kind !== list && indent <= base) flush();
      if (list && indent > (nest.length ? nest[nest.length - 1].indent : base) && out[out.length - 1].endsWith('</li>')) {
        out.push(out.pop().slice(0, -5), `<${kind}>`); // reopen the parent item around a nested list
        nest.push({ kind, indent });
      } else {
        while (nest.length && indent < nest[nest.length - 1].indent) out.push(`</${nest.pop().kind}></li>`);
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
  if (fence) out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
  flush();
  return out.join('\n');
}
