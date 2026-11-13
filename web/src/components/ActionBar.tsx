import type { Action } from "../api/types";
import { exec } from "../state/exec";
import { Btn } from "./ui";

/** Renders server-built actions generically. The key letter is the keyboard shortcut. */
export function ActionBar({ actions, dropId, showKey, primary }: {
  actions: readonly Action[]; dropId?: string;
  /** Hide the key hint of an action whose key does not act here (default: show every key). */
  showKey?: (a: Action) => boolean;
  /** Overrides the server's primary flag. */
  primary?: (a: Action) => boolean;
}) {
  if (!actions.length) return null;
  return (
    <div class="acts">
      {actions.map((a) => (
        <Btn key={a.key + a.label} k={!showKey || showKey(a) ? a.key : undefined} primary={primary ? primary(a) : a.primary} onClick={() => exec(a, dropId)}>{a.label}</Btn>
      ))}
    </div>
  );
}
