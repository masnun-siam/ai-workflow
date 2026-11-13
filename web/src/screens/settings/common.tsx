import { useRef, useState } from "preact/hooks";
import { http } from "../../api/http";
import type { Settings } from "../../api/types";
import { describeError } from "../../state/actions";
import { mutate, settings } from "../../state/data";

/** PUT a partial settings object; the response replaces the cached settings. */
export async function saveSettings(patch: Partial<Settings>): Promise<boolean> {
  const r = await mutate(() => http.send<Settings>("PUT", "/api/settings", patch), "Saved");
  if (r) settings.value = r;
  return !!r;
}
export const csv = (s: string): string[] => s.split(",").map((x) => x.trim()).filter(Boolean);

type Note = { ok: boolean; text: string };

/** Instant-save fields: `save(key, patch)` PUTs settings and `note(key)` renders "Saved ✓" or the error beside that field. */
export function useInlineSave() {
  const [notes, setNotes] = useState<Record<string, Note | undefined>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const put = (key: string, n: Note | undefined) => {
    setNotes((cur) => ({ ...cur, [key]: n }));
    clearTimeout(timers.current[key]);
    if (n?.ok) timers.current[key] = setTimeout(() => setNotes((cur) => ({ ...cur, [key]: undefined })), 2500);
  };
  const save = async (key: string, patch: Partial<Settings>): Promise<boolean> => {
    try {
      settings.value = await http.send<Settings>("PUT", "/api/settings", patch);
      put(key, { ok: true, text: "Saved ✓" });
      return true;
    } catch (e) {
      put(key, { ok: false, text: describeError(e) });
      return false;
    }
  };
  const clear = (key: string) => put(key, undefined);
  const note = (key: string) => {
    const n = notes[key];
    return n ? <span class={n.ok ? "c-o" : "c-b"} role={n.ok ? "status" : "alert"}>{n.text}</span> : null;
  };
  return { save, note, clear };
}

/** Why a whole-number field is invalid, or null. An empty field is invalid, never 0. */
export function intError(raw: string, min: number, max: number): string | null {
  const t = raw.trim();
  if (t === "") return "Required";
  if (!/^-?\d+$/.test(t)) return "Enter a whole number";
  const n = Number(t);
  return n < min || n > max ? `Must be ${min} to ${max}` : null;
}

/** An input's value as typed. */
export const val = (e: Event): string => (e.target as HTMLInputElement).value;
