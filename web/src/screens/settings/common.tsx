import { http } from "../../api/http";
import type { Settings } from "../../api/types";
import { mutate, settings } from "../../state/data";

/** PUT a partial settings object; the response replaces the cached settings. */
export async function saveSettings(patch: Partial<Settings>): Promise<boolean> {
  const r = await mutate(() => http.send<Settings>("PUT", "/api/settings", patch), "Saved");
  if (r) settings.value = r;
  return !!r;
}
export const csv = (s: string): string[] => s.split(",").map((x) => x.trim()).filter(Boolean);
