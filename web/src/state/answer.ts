import type { Answer, Answers, Round } from "../api/types";

/** Per question: chosen option labels and the free-text answer. */
export type Draft = { labels: string[]; other: string };

export const emptyDraft = (round: Round): Draft[] => round.questions.map(() => ({ labels: [], other: "" }));

export function toggleLabel(d: Draft, label: string, multi: boolean): Draft {
  if (!multi) return { labels: [label], other: "" };
  const has = d.labels.includes(label);
  return { ...d, labels: has ? d.labels.filter((l) => l !== label) : [...d.labels, label] };
}

const answerOf = (d: Draft): Answer | null =>
  d.other.trim() ? { other: d.other.trim() } : d.labels.length ? { labels: d.labels } : null;

export function canSubmit(drafts: Draft[]): boolean {
  return drafts.length > 0 && drafts.every((d) => answerOf(d) !== null);
}
/** Free text wins over options. Null when a question is unanswered. */
export function buildAnswers(drafts: Draft[]): Answers | null {
  const out: Answers = {};
  for (let i = 0; i < drafts.length; i++) {
    const a = answerOf(drafts[i] as Draft);
    if (!a) return null;
    out[String(i)] = a;
  }
  return out;
}
/** Single question, single select: an option press answers at once (a/b/c). */
export function quickOptions(round: Round | null | undefined): string[] {
  if (!round || round.questions.length !== 1) return [];
  const q = round.questions[0];
  return q && !q.multiSelect ? q.options.map((o) => o.label) : [];
}
export const answerKeyIndex = (k: string): number => "abc".indexOf(k);
