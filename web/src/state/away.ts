import type { Away } from "../api/types";
import { clock } from "./format";

/** The durations offered by the rail card and the Away pane, in minutes. */
export const AWAY_PRESETS: [number, string][] = [[30, "30 min"], [60, "1 h"], [120, "2 h"], [240, "4 h"], [480, "8 h"]];

/** One description of the Away state for the rail card, the banner and the pane. */
export function awayLabel(a: Pick<Away, "active" | "until">): string {
  if (!a.active) return "Away mode off";
  return a.until ? `Away until ${clock(a.until)}` : "Away (open-ended)";
}
