// Joins /api/planning (the PRD) with /api/delivery (the lane whose epic matches) into one Feature (no server endpoint).
import type { DeliveryCard, DeliveryLane, PanelRef, PlanningPrd } from '../api/types';
import { issueStatus, type IssueStatus, type StageId } from './vocab';

export interface FeatureIssue extends DeliveryCard {
  status: IssueStatus;
}
export interface Feature {
  slug: string;
  title: string;
  prd: PlanningPrd;
  lane: DeliveryLane | null;
  epic: number | null;
  stage: StageId;
  issues: FeatureIssue[];
  panel: PanelRef | null;
  autobuild: boolean;
  cap: number;
}

/** Both board snapshots have been fetched; before that the stage and next step would be guesses. */
export const snapshotsReady = (...metas: ({ fetched_at: number | null } | undefined)[]) => metas.every((m) => m?.fetched_at != null);

export const mergeable = (pr: DeliveryCard['pr']) =>
  !!pr && !pr.draft && pr.ci === 'success' && pr.review === 'approved';

export function countBy(issues: { status: IssueStatus }[]): Partial<Record<IssueStatus, number>> {
  const m: Partial<Record<IssueStatus, number>> = {};
  for (const i of issues) m[i.status] = (m[i.status] ?? 0) + 1;
  return m;
}

/**
 * Stage from server data:
 * - a PRD with a peer-review panel, or whose status is "In review", is in PRD review
 * - Draft with no panel is PRD draft; Approved with no open children is Approved
 * - with children: Tasks while some need refinement and nothing has started, else Building
 * - Shipped: the epic's lane holds only merged cards and no child is still open
 */
export function stageOf(prd: PlanningPrd, lane: DeliveryLane | null): StageId {
  if (prd.status === 'Draft' || prd.status === 'In review') {
    return prd.panel || prd.status === 'In review' ? 'review' : 'draft';
  }
  const cards = lane?.cards ?? [];
  const started = cards.some((c) => c.column !== 'unrefined' && c.column !== 'ready');
  if (prd.issues === 0) return cards.length > 0 && cards.every((c) => c.column === 'merged') ? 'shipped' : 'approved';
  if (prd.unrefined.length > 0 && !started) return 'tasks';
  return 'building';
}

export function joinFeatures(prds: PlanningPrd[], lanes: DeliveryLane[]): Feature[] {
  return prds.map((prd) => {
    const lane = prd.epic != null ? (lanes.find((l) => l.epic === prd.epic) ?? null) : null;
    return {
      slug: prd.slug,
      title: prd.title,
      prd,
      lane,
      epic: prd.epic,
      stage: stageOf(prd, lane),
      issues: (lane?.cards ?? []).map((c) => ({ ...c, status: issueStatus(c) })),
      panel: prd.panel,
      autobuild: lane?.autopilot ?? false,
      cap: lane?.cap ?? 2,
    };
  });
}
