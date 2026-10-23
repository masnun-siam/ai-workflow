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
}

/** Both board snapshots have been fetched; before that the stage and next step would be guesses. */
export const snapshotsReady = (...metas: ({ fetched_at: number | null } | undefined)[]) => metas.every((m) => m?.fetched_at != null);

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
 * - Shipped: the server's `done` column (epic closed, or every sub-issue closed), or the epic's lane
 *   holds only merged cards and no child is still open
 */
export function stageOf(prd: PlanningPrd, lane: DeliveryLane | null): StageId {
  if (prd.status === 'Draft' || prd.status === 'In review') {
    return prd.panel || prd.status === 'In review' ? 'review' : 'draft';
  }
  if (prd.column === 'done') return 'shipped';
  const cards = lane?.cards ?? [];
  const started = cards.some((c) => c.column !== 'unrefined' && c.column !== 'ready');
  if (prd.issues === 0) return (cards.length > 0 || prd.closed_children?.length) && cards.every((c) => c.column === 'merged') ? 'shipped' : 'approved';
  if (prd.unrefined.length > 0 && !started) return 'tasks';
  return 'building';
}

export function joinFeatures(prds: PlanningPrd[], lanes: DeliveryLane[]): Feature[] {
  return prds.map((prd) => {
    const lane = prd.epic != null ? (lanes.find((l) => l.epic === prd.epic) ?? null) : null;
    // no open epic (closed, or never filed): the PRD's open children sit in other lanes, e.g. the no-epic one
    const kids = new Set(prd.children.map((c) => c.n));
    const open = lane?.cards ?? lanes.flatMap((l) => l.cards.filter((c) => kids.has(c.n)));
    // finished children: closed on GitHub, no merged card of their own (older than the board's 7 days, or closed by hand)
    const shown = new Set(open.map((c) => c.n));
    const done = (prd.closed_children ?? []).filter((c) => !shown.has(c.n)).map((c): DeliveryCard => ({
      n: c.n, title: c.title, column: 'merged', priority: null, blocked_by: [], pr: null, session: null, needs_cleanup: null,
    }));
    const cards = [...open, ...done];
    return {
      slug: prd.slug,
      title: prd.title,
      prd,
      lane,
      epic: prd.epic,
      stage: stageOf(prd, lane),
      issues: cards.map((c) => ({ ...c, status: issueStatus(c) })),
      panel: prd.panel,
    };
  });
}
