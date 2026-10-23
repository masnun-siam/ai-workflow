export const SMALL_CHANGE_MARKER = 'Small change (no PRD):';

/** Appended to every small-change arg: makes /create-tasks skip the PRD question and chain /refine-issues. */
export const SMALL_CHANGE_NOTE =
  ' Instructions: this change has no PRD and does not need one. Follow "A finding from other work" and go on without a PRD: do not search for one and do not ask which PRD it belongs to; the issue gets no prd-<slug> label and no epic parent. Still ask me to confirm before creating the issue. Once it is created, run /ai-workflow:refine-issues on its number in this same session instead of stopping at the hand-off; there is no PRD to read or update. My yes to create the issue also approves refining it, so do not ask a second time before writing the refined body. If I decline, stop and file nothing.';

export const smallChangeArg = (text: string) => `${SMALL_CHANGE_MARKER} ${text.trim().replace(/\s+/g, ' ')}${SMALL_CHANGE_NOTE}`;
