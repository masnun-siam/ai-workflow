import { useEffect, useRef, useState } from "preact/hooks";
import { toast } from "../state/ui";
import type { TranscriptEvent } from "../api/types";
import { Markdown } from "./Markdown";

const brief = (v: unknown): string => {
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    const first = o.command ?? o.file_path ?? o.path ?? o.pattern ?? o.url;
    if (typeof first === "string") return first.length > 90 ? `${first.slice(0, 90)}…` : first;
  }
  return "";
};

function ToolCall({ ev }: { ev: Extract<TranscriptEvent, { kind: "tool" }> }) {
  const json = JSON.stringify(ev.input, null, 2);
  const copy = () => navigator.clipboard.writeText(json).then(() => toast("Copied"), () => toast("Could not copy", "error"));
  return (
    <details class="e tool"><summary>{ev.name} {brief(ev.input)}</summary>
      <button type="button" class="btn sm copy" onClick={copy} aria-label={`Copy the ${ev.name} input as JSON`}>Copy</button>
      <pre>{json}</pre>
    </details>
  );
}

/** prevText is the last text event before ev; a result repeating it shows only its status line. */
export function EventView({ ev, prevText }: { ev: TranscriptEvent; prevText?: string }) {
  switch (ev.kind) {
    case "text": return <div class="e txt"><Markdown text={ev.text} /></div>;
    case "tool":
      return <ToolCall ev={ev} />;
    case "hook":
      return <div class={`e hook${ev.blocked ? " blocked" : ""}`}>{ev.blocked ? "blocked" : "hook"} · {ev.name} ({ev.event}){ev.text && `: ${ev.text}`}</div>;
    case "result":
      return <div class={`e res${ev.is_error ? " err" : ""}`}>{ev.is_error ? "error" : "result"}{ev.cost != null && ` · $${ev.cost.toFixed(2)}`}{ev.text && ev.text.trim() !== prevText?.trim() && ` · ${ev.text}`}</div>;
  }
}

const lastText = (list: TranscriptEvent[], i: number): string | undefined => {
  for (let j = i - 1; j >= 0; j--) { const e = list[j]; if (e?.kind === "text") return e.text; }
  return undefined;
};

/** The page scrolls with the transcript (`fill`), or the box does (the drawer). "Jump to latest" shows once you scroll up. */
export function Transcript({ events, hooksOnly, fill }: { events: TranscriptEvent[]; hooksOnly?: boolean; fill?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  // The page variant opens at the top (heading, question, actions); it follows new events only once you scroll to the end.
  const stick = useRef(!fill);
  const [away, setAway] = useState(false);
  const list = hooksOnly ? events.filter((e) => e.kind === "hook") : events;
  const toEnd = () => { const el = ref.current; if (fill) window.scrollTo({ top: document.documentElement.scrollHeight }); else if (el) el.scrollTop = el.scrollHeight; };
  useEffect(() => { if (stick.current) toEnd(); }, [list.length]);
  useEffect(() => {
    if (!fill) return;
    const on = () => { const d = document.documentElement; stick.current = d.scrollHeight - window.scrollY - window.innerHeight < 80; setAway(!stick.current); };
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, [fill]);
  const jump = () => { stick.current = true; setAway(false); toEnd(); };
  return (
    <div class={`txw${fill ? " fill" : ""}`}>
      <div class="tx" ref={ref} tabIndex={0} role="log" aria-label={hooksOnly ? "Hook events" : "Transcript"}
        onScroll={fill ? undefined : (e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; setAway(!stick.current); }}>
        {list.length ? list.map((e, i) => <EventView key={i} ev={e} prevText={lastText(list, i)} />) : <span class="dim">{hooksOnly ? "No hook events." : "Nothing yet."}</span>}
      </div>
      {away && list.length > 0 && <button type="button" class="btn sm jump" onClick={jump}>↓ Jump to latest</button>}
    </div>
  );
}
