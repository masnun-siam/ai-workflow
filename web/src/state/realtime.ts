import { connectEvents } from "../api/sse";
import { sseCreate } from "../api/http";
import { DEBOUNCED, refetchFor, type LoadKey } from "./refetch";
import { currentView, load, loadMany } from "./data";
import { connected, toast } from "./ui";

const timers = new Map<LoadKey, ReturnType<typeof setTimeout>>();
function schedule(k: LoadKey): void {
  if (!DEBOUNCED.has(k)) { void load(k); return; }
  if (timers.has(k)) return;
  timers.set(k, setTimeout(() => { timers.delete(k); void load(k); }, 1000));
}

export function startRealtime(): () => void {
  return connectEvents({
    create: sseCreate(),
    onStatus: (ok) => (connected.value = ok),
    onEvent: (topic, data) => {
      if (topic === "toast") {
        const t = data as { title?: string; body?: string; level?: "info" | "warn" | "error"; path?: string } | null;
        if (t) toast([t.title, t.body].filter(Boolean).join(": "), t.level ?? "info", t.path);
        return;
      }
      if (topic === "hello") { void loadMany(refetchFor("hello", data, currentView())); return; }
      refetchFor(topic, data, currentView()).forEach(schedule);
    },
  });
}
