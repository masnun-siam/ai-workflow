import { useEffect, useMemo, useRef } from "preact/hooks";
import DOMPurify from "dompurify";
import { marked } from "marked";

let mermaidLoad: Promise<typeof import("mermaid").default> | null = null;
const dark = () => document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

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
