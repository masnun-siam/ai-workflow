// Response shapes of API.md section 5 that section 4 does not name.
import type { Limit, Session, SessionStats } from "./types";

/** A registry step (API.md 2 `prompts.Step` + the 5.1 additions). Optional fields tolerate JSON tag variants. */
export type RegistryStep = {
  id: string;
  source: "blubird" | "setu";
  skill: string;
  runs_in: "docs" | "issue" | "repo" | "none";
  stage: string;
  label?: string;
  args_hint?: string;
  command?: string;
  available: boolean;
  reason?: string;
};

export type SessionList = { sessions: Session[]; stats: SessionStats; limits: Record<string, Limit> };
export type CleanupList = { items: { key: string; label: string; repo: string; flags: string[] }[] };
