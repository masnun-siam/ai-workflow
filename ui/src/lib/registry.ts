// The app's view of the skill registry (GET /api/registry): which skill each UI step runs. Step ids are the
// only skill-like strings the app holds, and they live only in STEP; commands come from the registry.
import { parseSkill } from './format';

export type RegistryEntry = { plugin: string; skill: string; runs_in: 'docs' | 'issue' | 'any'; command: string };
export type Registry = Record<string, RegistryEntry>;

/** Every step id the app names, keyed for code (ids equal the server's skill_registry.json keys). */
export const STEP = {
  writePrd: 'create-prd',
  createTasks: 'create-tasks',
  smallChange: 'small-change',
  refine: 'refine-issues',
  implement: 'implement-issue',
  afterMerge: 'after-merge',
  review: 'pr-review',
  reviewUnmapped: 'pr-review-unmapped',
  verify: 'verifier-locally',
  docs: 'docs-updater',
  reproduceBug: 'reproduce-bug',
  securitySweep: 'security-sweep',
  mapPrds: 'map-prds',
  onboard: 'agentic-onboard',
  ciOptimize: 'ci-optimize',
  skillFeedback: 'skill-feedback',
  releasePr: 'release-pr',
  faq: 'faq-updater',
  grind: 'pr-grind',
  peerReview: 'peer-review',
  dump: 'dump',
  worklog: 'worklog',
} as const;
export type StepId = (typeof STEP)[keyof typeof STEP];

// ponytail: module value filled by useRegistry, so non-hook code can call commandOf/isStep; pass `reg` if a caller needs it before load
let current: Registry = {};
export const setRegistry = (r: Registry) => { current = r; };

/** The command the server starts for a step, e.g. "/blubird:create-prd"; '' when the registry has no such step. */
export const commandOf = (step: string, reg: Registry = current) => reg[step]?.command ?? '';

/** True when a session's command runs the skill behind `step`, in either spelling ("/s x" or "/plugin:s x"). */
export const isStep = (command: string, step: string, reg: Registry = current) =>
  !!reg[step] && parseSkill(command)?.skill === reg[step].skill;
