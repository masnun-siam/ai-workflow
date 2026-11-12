import { useEffect, useRef } from "preact/hooks";
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

/** prevText is the last text event before ev; a result repeating it shows only its status line. */
export function EventView({ ev, prevText }: { ev: TranscriptEvent; prevText?: string }) {
  switch (ev.kind) {
    case "text": return <div class="e txt"><Markdown text={ev.text} /></div>;
    case "tool":
      return <details class="e tool"><summary>{ev.name} {brief(ev.input)}</summary><pre>{JSON.stringify(ev.input, null, 2)}</pre></details>;
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

export function Transcript({ events, hooksOnly }: { events: TranscriptEvent[]; hooksOnly?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const list = hooksOnly ? events.filter((e) => e.kind === "hook") : events;
  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [list.length]);
  return (
    <div class="tx" ref={ref} tabIndex={0} role="log" aria-label={hooksOnly ? "Hook events" : "Transcript"}
      onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
      {list.length ? list.map((e, i) => <EventView key={i} ev={e} prevText={lastText(list, i)} />) : <span class="dim">{hooksOnly ? "No hook events." : "Nothing yet."}</span>}
    </div>
  );
}
