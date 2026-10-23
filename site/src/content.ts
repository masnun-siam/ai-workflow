// All page copy and media in one place. Media paths are relative to public/.
export const REPO = 'https://github.com/masnun-siam/ai-workflow';

export type Stage = {
  id: string;
  name: string;
  cmd: string;
  body: string;
  /** a person decides here; drawn as an amber gate on the rail */
  gate?: string;
  media: { src: string; poster?: string; kind: 'video' | 'image'; alt: string };
};

export const stages: Stage[] = [
  {
    id: 'idea',
    name: 'Idea',
    cmd: 'New feature',
    body: 'Type the idea in a sentence or two. Pick which reviewers should check the plan.',
    media: { kind: 'image', src: 'media/new-feature.webp', alt: 'The Start dialog with the idea typed and three review lenses picked' },
  },
  {
    id: 'prd',
    name: 'PRD',
    cmd: '/create-prd',
    body: 'Claude reads the code, then interviews you. Every question comes with options and a recommendation, answered right in the UI.',
    gate: 'You answer the questions',
    media: { kind: 'image', src: 'media/prd-questions.webp', alt: 'Claude asking three questions about the feature, each with a recommended option' },
  },
  {
    id: 'review',
    name: 'Peer review',
    cmd: '--review critical,cto,qa',
    body: 'Independent reviewer lenses read the PRD on their own. Claude revises after each round until every lens approves.',
    gate: 'You approve the PRD',
    media: { kind: 'image', src: 'media/peer-review.webp', alt: 'Review rounds in the session transcript, with each lens approving' },
  },
  {
    id: 'tasks',
    name: 'Tasks',
    cmd: '/create-tasks',
    body: 'The PRD becomes small GitHub issues under one epic, with real blocked-by links so work can run in parallel.',
    media: { kind: 'image', src: 'media/board.webp', alt: 'The feature board: stage stepper and issues grouped by status' },
  },
  {
    id: 'refine',
    name: 'Refine',
    cmd: '/refine-issues',
    body: 'Each issue gets a WHAT, WHY and HOW written from the PRD and the code, so whoever picks it up needs nothing else.',
    media: { kind: 'image', src: 'media/refined-issue.webp', alt: 'A refined GitHub issue with What, Why and How sections' },
  },
  {
    id: 'build',
    name: 'Implement',
    cmd: '/implement-issue',
    body: 'Its own worktree, every local check run the way CI runs it, then a draft PR. This one: 13 files, 235 tests passing.',
    media: { kind: 'video', src: 'media/implement.mp4', poster: 'media/implement.webp', alt: 'A headless Claude session implementing the issue, sped up' },
  },
  {
    id: 'pr',
    name: 'Review',
    cmd: '/pr-review',
    body: 'The PR is reviewed against the issue, the repo rules and the review guide, fixed, and marked ready only when CI is green.',
    gate: 'You merge',
    media: { kind: 'image', src: 'media/pr.webp', alt: 'Pull request #42 in the UI: 13 files changed, checks passing' },
  },
];

export const tour = [
  {
    id: 'board',
    label: 'Features',
    title: 'Every feature, one stepper',
    body: 'Each PRD and everything built from it: stage, progress, what is blocked, what is ready, and the one next step.',
    media: { kind: 'video', src: 'media/tour-board.mp4', poster: 'media/tour-board.webp' },
  },
  {
    id: 'session',
    label: 'Live session',
    title: 'Watch Claude work, or don’t',
    body: 'Every stage runs as a headless Claude Code session. Follow the transcript live, answer its questions, or send a message for its next turn.',
    media: { kind: 'video', src: 'media/tour-session.mp4', poster: 'media/tour-session.webp' },
  },
  {
    id: 'inbox',
    label: 'Inbox',
    title: 'Only what needs you',
    body: 'Questions to answer, PRDs to approve, PRs ready to merge, across every repo. Everything else keeps going on its own.',
    media: { kind: 'video', src: 'media/tour-inbox.mp4', poster: 'media/tour-inbox.webp' },
  },
  {
    id: 'dispatch',
    label: 'Dispatch',
    title: 'Run a whole epic in parallel',
    body: 'Unblocked issues build side by side in dependency order, each one ground through review, CI and the merge gate.',
    media: { kind: 'video', src: 'media/tour-dispatch.mp4', poster: 'media/tour-dispatch.webp' },
  },
] as const;

/** Real numbers from the todoman run shown on this page. */
export const run = {
  feature: 'Dump result card',
  repo: 'todoman',
  summary:
    'todoman is a personal project: it turns a free-form note into GitHub issues and calendar meetings. The ask was one small feature: after it processes a note, post a single comment with a table of everything it created. This is that run, start to finish, cut only for speed.',
  stats: [
    { value: '11.5 min', label: 'from typing the idea to a ready PR' },
    { value: '$2.96', label: 'of Claude for the whole run' },
    { value: '3 × 3', label: 'review lenses × rounds until all approved' },
    { value: '235', label: 'tests passing, 7 of them new' },
  ],
  video: { src: 'media/run.mp4', poster: 'media/run.webp' },
};
