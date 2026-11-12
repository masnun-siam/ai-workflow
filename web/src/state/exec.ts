import { http } from "../api/http";
import type { Action } from "../api/types";
import { runAction } from "./actions";
import { currentView, drop, loadMany } from "./data";
import { nav } from "./route";
import { visibleKeys } from "./refetch";
import { askConfirm, toast } from "./ui";

export function navigateTo(target: string): void {
  if (target.startsWith("#")) nav(target);
  else window.open(target, "_blank", "noopener,noreferrer");
}

/** Runs a server-built action with the real client; `dropId` hides the row when the action clears it. */
export function exec(a: Action, dropId?: string): Promise<boolean> {
  return runAction(a, {
    send: (m, p, b) => http.send(m, p, b),
    confirm: askConfirm,
    navigate: navigateTo,
    toast,
    onClears: () => dropId && drop(dropId),
    after: () => void loadMany(visibleKeys(currentView())),
  });
}
