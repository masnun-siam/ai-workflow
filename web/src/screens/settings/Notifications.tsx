import { useEffect, useState } from "preact/hooks";
import { http } from "../../api/http";
import type { NotifyEvent, NotifySettings } from "../../api/types";
import { mutate, notify } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { pushState, subscribePush, unsubscribePush, type PushState } from "../../state/push";
import { describeError } from "../../state/actions";
import { toast } from "../../state/ui";
import { val } from "./common";

const CH = ["browser", "ntfy", "push", "mac"] as const;

export function NotificationsPane() {
  const n = notify.value;
  const [url, setUrl] = useState<string | null>(null);
  const [res, setRes] = useState("");
  const [ps, setPs] = useState<PushState>("off");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState<ReadonlySet<string>>(new Set());
  const [urlNote, setUrlNote] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { void pushState().then(setPs); }, []);
  const togglePush = async () => {
    setBusy(true);
    try { if (ps === "on") await unsubscribePush(); else await subscribePush(); setPs(await pushState()); void http.get<NotifySettings>("/api/settings/notify").then((r) => (notify.value = r)); }
    catch (e) { toast(e instanceof Error ? e.message : String(e), "error"); setPs(await pushState()); }
    finally { setBusy(false); }
  };
  if (!n) return <Pane label="notifications" wide><span class="dim">Loading…</span></Pane>;
  const put = async (body: object) => { const r = await mutate(() => http.send<NotifySettings>("PUT", "/api/settings/notify", body), null); if (r) notify.value = r; return !!r; };
  const putCell = async (event: string, channel: string, on: boolean) => {
    const k = `${event}:${channel}`;
    setSaving((cur) => new Set(cur).add(k));
    await put({ cell: { event, channel, on } });
    setSaving((cur) => { const n = new Set(cur); n.delete(k); return n; });
  };
  const savePublicUrl = async () => {
    if (url === null) return;
    try {
      notify.value = await http.send<NotifySettings>("PUT", "/api/settings/notify", { public_url: url });
      setUrl(null);
      setUrlNote({ ok: true, text: "Saved ✓" });
    } catch (e) { setUrlNote({ ok: false, text: describeError(e) }); }
  };
  const noPush = ps === "unsupported" || n.push.subscriptions === 0;
  const why = (c: string) => (c === "mac" && !n.mac.available ? "macOS notifications are not available on this machine" : c === "ntfy" && !n.ntfy_ready ? "ntfy is not configured (ui.json or SETU_NTFY_* environment variables)" : undefined);
  const test = async (channel: "push" | "mac" | "ntfy") => {
    const r = await mutate(() => http.send<{ ok: boolean; error?: string }>("POST", "/api/settings/notify/test", { channel }), null);
    if (r) setRes(`${channel}: ${r.ok ? "sent" : `failed${r.error ? ` (${r.error})` : ""}`}`);
  };
  return (
    <Pane label="notifications" wide id="set-notify">
      <div class="det">
        <div class="tablewrap"><table class="t mx"><thead><tr><th>Event</th>{CH.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>
          {n.events.map((ev) => (
            <tr key={ev.key}><td>{ev.label} <span class="dim">{ev.group}</span></td>
              {CH.map((c) => (
                <td key={c} title={why(c)}><input type="checkbox" aria-label={`${ev.label} via ${c}`} checked={n.matrix[ev.key as NotifyEvent]?.[c] ?? false}
                  disabled={!!why(c) || saving.has(`${ev.key}:${c}`)} onChange={(e) => void putCell(ev.key, c, (e.target as HTMLInputElement).checked)} /></td>
              ))}</tr>
          ))}</tbody></table></div>
        <Field label="Public URL (used in push links, e.g. your tailnet address)">
          <input value={url ?? n.public_url} onInput={(e) => { setUrl(val(e)); setUrlNote(null); }} onChange={() => void savePublicUrl()} />
        </Field>
        {urlNote && <span class={urlNote.ok ? "c-o" : "c-b"} role={urlNote.ok ? "status" : "alert"}>{urlNote.text}</span>}
        <span class="dim">macOS: {n.mac.available ? `${n.mac.notifier}${n.mac.clickable ? " (clickable)" : ""}` : "not available"} · phone push subscriptions: {n.push.subscriptions} · ntfy: {n.ntfy_ready ? `${n.server} / ${n.topic}${n.token_set ? " (token set)" : ""}` : "not configured (ui.json or SETU_NTFY_* environment variables)"}</span>
        <div class="acts"><Btn disabled={busy || ps === "unsupported" || ps === "denied"} onClick={() => togglePush()}>{ps === "on" ? "Turn off push on this device" : "Turn on push on this device"}</Btn>{ps === "unsupported" && <span class="dim">push needs https or localhost</span>}{ps === "denied" && <span class="dim">notifications are blocked in the browser</span>}</div>
        <div class="acts"><Btn disabled={noPush} title={ps === "unsupported" ? "push needs https or localhost" : n.push.subscriptions === 0 ? "No device is subscribed to push yet" : undefined} onClick={() => test("push")}>Test push</Btn><Btn disabled={!n.ntfy_ready} onClick={() => test("ntfy")}>Test ntfy</Btn><Btn disabled={!n.mac.available} onClick={() => test("mac")}>Test macOS</Btn>{res && <span role="status">{res}</span>}</div>
      </div>
    </Pane>
  );
}
