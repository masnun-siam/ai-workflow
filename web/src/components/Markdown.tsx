import { useEffect, useMemo, useRef } from "preact/hooks";
import DOMPurify from "dompurify";
import { marked } from "marked";

let mermaidLoad: Promise<typeof import("mermaid").default> | null = null;
const dark = () => document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

/** The anchor id Markdown gives a heading, so a table of contents can link to it. */
export const slug = (t: string): string => t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
/** Headings (levels 1-3) of a markdown text, outside code fences. */
export function headings(text: string): { level: number; text: string; id: string }[] {
  let fence = false;
  const seen = new Map<string, number>();
  const out: { level: number; text: string; id: string }[] = [];
  for (const line of text.split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) { fence = !fence; continue; }
    const m = !fence && /^(#{1,3})\s+(.+?)\s*#*$/.exec(line);
    if (!m) continue;
    const base = slug(m[2]!) || "section";
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    out.push({ level: m[1]!.length, text: m[2]!.replace(/[`*_]/g, ""), id: n ? `${base}-${n}` : base });
  }
  return out;
}

/** Renders repo markdown (sanitized); ```mermaid blocks become diagrams, mermaid loads only when a page has one. */
export function Markdown({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const html = useMemo(() => {
    // Without a DOM (server render, tests) DOMPurify cannot sanitize: show the text escaped instead.
    if (!DOMPurify.isSupported) return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
    const raw = marked.parse(text, { gfm: true, async: false });
    return DOMPurify.sanitize(raw);
  }, [text]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const seen = new Map<string, number>();
    el.querySelectorAll<HTMLElement>("h1,h2,h3").forEach((h) => {
      const base = slug(h.textContent ?? "") || "section";
      const n = seen.get(base) ?? 0;
      seen.set(base, n + 1);
      h.id = n ? `${base}-${n}` : base;
    });
    el.querySelectorAll("a[href]").forEach((a) => {
      if (/^https?:/.test(a.getAttribute("href") ?? "")) { a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener noreferrer"); }
    });
    const blocks = [...el.querySelectorAll<HTMLElement>("pre > code.language-mermaid")];
    if (!blocks.length) return;
    let gone = false;
    mermaidLoad ??= import("mermaid").then((m) => m.default);
    void mermaidLoad.then(async (mermaid) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark() ? "dark" : "default" });
      for (const [i, code] of blocks.entries()) {
        if (gone) return;
        const pre = code.parentElement!;
        try {
          const { svg } = await mermaid.render(`mmd-${Date.now()}-${i}`, code.textContent ?? "");
          const fig = document.createElement("div");
          fig.className = "mmd";
          fig.innerHTML = svg;
          pre.replaceWith(fig);
        } catch (e) {
          pre.insertAdjacentHTML("beforebegin", `<div class="dim">Diagram did not render: ${DOMPurify.sanitize(String((e as Error).message ?? e))}</div>`);
        }
      }
    });
    return () => { gone = true; };
  }, [html]);
  return <div class="md" ref={ref} dangerouslySetInnerHTML={{ __html: html }} />;
}
