// The registry every app test uses: one entry per STEP, shaped like GET /api/registry.
import { setRegistry, STEP, type Registry } from './lib/registry';

const SKILL: Record<string, string> = { 'small-change': 'create-tasks', 'after-merge': 'implement-issue', 'pr-review-unmapped': 'pr-review' };

const steps: Registry = Object.fromEntries(Object.values(STEP).map((id) => {
  const skill = SKILL[id] ?? id;
  const plugin = id === 'pr-review-unmapped' ? 'ai-workflow' : 'blubird';
  return [id, { plugin, skill, runs_in: 'any', command: `/${plugin}:${skill}` }];
}));

export const REGISTRY = { steps };
export const primeRegistry = () => setRegistry(REGISTRY.steps);
