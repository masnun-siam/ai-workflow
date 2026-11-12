import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { NotifyEvent, NotifySettings } from "../../api/types";
import { mutate, notify } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";

const CH = ["browser", "ntfy", "push", "mac"] as const;

export function NotificationsPane() {
  const n = notify.value;
  const [url, setUrl] = useState<string | null>(null);
  const [res, setRes] = useState("");
  if (!n) return <Pane label="notifications" wide><span class="dim">Loading…</span></Pane>;
  const put = async (body: object) => { const r = await mutate(() => http.send<NotifySettings>("PUT", "/api/settings/notify", body), null); if (r) notify.value = r; };
  const test = async (channel: "push" | "mac" | "ntfy") => {
    const r = await mutate(() => http.send<{ ok: boolean; error?: string }>("POST", "/api/settings/notify/test", { channel }), null);
    if (r) setRes(`${channel}: ${r.ok ? "sent" : `failed${r.error ? ` (${r.error})` : ""}`}`);
  };
  return (
    <Pane label="notifications" wide>
      <div class="det">
        <div class="tablewrap"><table class="t mx"><thead><tr><th>Event</th>{CH.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>
          {n.events.map((ev) => (
            <tr key={ev.key}><td>{ev.label} <span class="dim">{ev.group}</span></td>
              {CH.map((c) => (
                <td key={c}><input type="checkbox" aria-label={`${ev.label} via ${c}`} checked={n.matrix[ev.key as NotifyEvent]?.[c] ?? false}
                  disabled={(c === "mac" && !n.mac.available) || (c === "ntfy" && !n.ntfy_ready)} onChange={(e) => void put({ cell: { event: ev.key, channel: c, on: (e.target as HTMLInputElement).checked } })} /></td>
              ))}</tr>
          ))}</tbody></table></div>
        <Field label="Public URL (used in push links, e.g. your tailnet address)">
          <input value={url ?? n.public_url} onInput={(e) => setUrl((e.target as HTMLInputElement).value)} onChange={() => url !== null && void put({ public_url: url })} />
        </Field>
        <span class="dim">macOS: {n.mac.available ? `${n.mac.notifier}${n.mac.clickable ? " (clickable)" : ""}` : "not available"} · phone push subscriptions: {n.push.subscriptions} · ntfy: {n.ntfy_ready ? `${n.server} / ${n.topic}${n.token_set ? " (token set)" : ""}` : "not configured (ui.json or SETU_NTFY_* environment variables)"}</span>
        <div class="acts"><Btn onClick={() => void test("push")}>Test push</Btn><Btn disabled={!n.ntfy_ready} onClick={() => void test("ntfy")}>Test ntfy</Btn><Btn disabled={!n.mac.available} onClick={() => void test("mac")}>Test macOS</Btn>{res && <span role="status">{res}</span>}</div>
      </div>
    </Pane>
  );
}
