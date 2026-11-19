import { http, type MapChoice } from "../api/http";
import type { Session } from "../api/types";
import { describeError } from "./actions";
import { loadMany } from "./data";
import { nav } from "./route";
import { askRepoMap, toast } from "./ui";

/** The chooser `http` asks when a start needs a repo map. "Run agentic-onboard" starts that skill in the repo
 *  here, so `api/` stays free of state and UI; the original start is then declined. */
export async function chooseRepoMap(repo: string): Promise<MapChoice> {
  const c = await askRepoMap(repo);
  if (c === "onboard") await startOnboard(repo);
  return c;
}

async function startOnboard(repo: string): Promise<void> {
  try {
    const s = await http.send<Session>("POST", "/api/sessions", { step: "agentic-onboard", repo, guard: true });
    toast(s.status === "queued" ? "Queued agentic-onboard" : "Started agentic-onboard");
    void loadMany(["sessions", "inbox"]);
    nav(`#/sessions/${s.id}`);
  } catch (e) {
    toast(describeError(e), "error");
  }
}
