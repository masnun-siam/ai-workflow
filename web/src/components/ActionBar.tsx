import type { Action } from "../api/types";
import { exec } from "../state/exec";
import { Btn } from "./ui";

/** Renders server-built actions generically. The key letter is the keyboard shortcut. */
export function ActionBar({ actions, dropId }: { actions: readonly Action[]; dropId?: string }) {
  if (!actions.length) return null;
  return (
    <div class="acts">
      {actions.map((a) => (
        <Btn key={a.key + a.label} k={a.key} primary={a.primary} onClick={() => exec(a, dropId)}>{a.label}</Btn>
      ))}
    </div>
  );
}
