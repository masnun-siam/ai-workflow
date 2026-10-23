// Every endpoint the UI calls, as plain typed functions. Hooks in hooks.ts wrap these with caching and invalidation.
import { enc, get, post, put, qs, splitRepo } from './client';
import type {
  AnswerBody, AfkState, Dispatch, DispatchPlan, DispatchSettings, DispatchState, EndAction, LaneAction, BoardStartBody, BoardStartResponse, CleanupItem, DeliveryResponse, InboxResponse,
  IssueDetail, NotifyChannel, NotifySettings, OpenItem, PeerReviewOffers, PlanningResponse, PrDetail, PrdFile, ReposResponse,
  ReviewSettings, Session, SessionStartBody, SessionsResponse, Settings, StreamResponse, VaultFolders, VaultPrd,
} from './types';

export const api = {
  // ---- reads
  sessions: () => get<SessionsResponse>('/api/sessions'),
  session: (id: string) => get<Session>(`/api/sessions/${enc(id)}`),
  stream: (id: string, offset: number) => get<StreamResponse>(`/api/sessions/${enc(id)}/stream${qs({ offset })}`),
  inbox: (repo?: string) => get<InboxResponse>(`/api/inbox${qs({ repo })}`),
  planning: (repo: string, refresh = false) => get<PlanningResponse>(`/api/planning${qs({ repo, refresh: refresh ? 1 : undefined })}`),
  delivery: (repo: string, refresh = false) => get<DeliveryResponse>(`/api/delivery${qs({ repo, refresh: refresh ? 1 : undefined })}`),
  repos: () => get<ReposResponse>('/api/repos'),
  settings: () => get<Settings>('/api/settings'),
  notify: () => get<NotifySettings>('/api/settings/notify'),
  review: () => get<ReviewSettings>('/api/settings/review'),
  peerReviewOffers: () => get<PeerReviewOffers>('/api/peer-review'),
  owners: () => get<{ owners: string[] }>('/api/github/owners'),
  vaultFolders: () => get<VaultFolders>('/api/vault/folders'),
  vaultPrd: (folder: string) => get<VaultPrd>(`/api/vault/prd${qs({ folder })}`),
  cleanupTargets: () => get<{ items: CleanupItem[] }>('/api/sessions/cleanup'),
  prd: (repo: string, path: string) => get<PrdFile>(`/api/prd${qs({ repo, path })}`),
  issue: (repo: string, n: number) => get<IssueDetail>(`/api/issues/${splitRepo(repo).join('/')}/${n}`),
  pull: (repo: string, n: number) => get<PrDetail>(`/api/pulls/${splitRepo(repo).join('/')}/${n}`),
  open: (repo: string, kind: 'issue' | 'pr') => get<{ items: OpenItem[] }>(`/api/repos/${splitRepo(repo).join('/')}/open${qs({ kind })}`),

  // ---- sessions
  startSession: (b: SessionStartBody) => post<Session>('/api/sessions', b),
  startBoard: (b: BoardStartBody) => post<BoardStartResponse>('/api/start', b),
  rerun: (id: string) => post<Session>(`/api/sessions/${enc(id)}/rerun`),
  startNow: (id: string) => post<Session>(`/api/sessions/${enc(id)}/start-now`),
  stop: (id: string) => post<Session>(`/api/sessions/${enc(id)}/stop`),
  resume: (id: string, claude_cmd?: string) => post<Session>(`/api/sessions/${enc(id)}/resume`, claude_cmd ? { claude_cmd } : {}),
  cancelAuto: (id: string) => post<Session>(`/api/sessions/${enc(id)}/cancel-auto`),
  answer: (id: string, b: AnswerBody) => post<Session>(`/api/sessions/${enc(id)}/answer`, b),
  prompt: (id: string, text: string) => post<{ state: 'sent' | 'queued' | string }>(`/api/sessions/${enc(id)}/prompt`, { text }),
  cleanupSessions: (keys: string[]) => post<{ removed: number }>('/api/sessions/cleanup', { keys }),

  // ---- away mode
  afkStart: (until: number) => post<AfkState>('/api/afk', { until }),
  afkStop: () => post<AfkState>('/api/afk/stop'),
  afkDismiss: () => post<AfkState>('/api/afk/dismiss'),

  // ---- delivery
  closeEpic: (repo: string, epic: number) => post('/api/epics/close', { repo, epic }),
  cleanupIssue: (repo: string, issue: number) => post('/api/cleanup', { repo, issue, confirm: true }),
  skipCi: (repo: string, pr: number) => post('/api/grind/skip-ci', { repo, pr }),
  stopGrind: (repo: string, pr: number) => post('/api/grind/stop', { repo, pr }),
  grindIssue: (repo: string, issue: number, on: boolean) => post('/api/grind/issue', { repo, issue, on }),
  merge: (repo: string, n: number) => post(`/api/pulls/${splitRepo(repo).join('/')}/${n}/merge`),
  comment: (kind: 'issues' | 'pulls', repo: string, n: number, text: string) =>
    post(`/api/${kind}/${splitRepo(repo).join('/')}/${n}/comment`, { text }),
  setIssueState: (repo: string, n: number, state: 'closed' | 'open', reason?: 'completed' | 'not_planned') =>
    post(`/api/issues/${splitRepo(repo).join('/')}/${n}/state`, { state, reason }),

  // ---- PRDs and peer review
  savePrd: (repo: string, path: string, text: string, base_sha?: string) => post<PrdFile>('/api/prd', { repo, path, text, base_sha }),
  startReview: (repo: string, artifact: string, lenses: string[], root_session?: string) =>
    post<{ panel: string }>('/api/review', { repo, artifact, lenses, root_session }),
  reviewLens: (panel: string, lens: string, action: 'retry' | 'drop' | string) => post(`/api/review/${enc(panel)}/lens`, { lens, action }),
  reviewRounds: (panel: string, add: number) => post(`/api/review/${enc(panel)}/rounds`, { add }),

  // ---- dispatches
  dispatches: () => get<{ dispatches: Dispatch[] }>('/api/dispatches'),
  dispatch: (id: string) => get<Dispatch>(`/api/dispatches/${enc(id)}`),
  dispatchLane: (id: string, key: string) => get<{ text?: string; session?: string }>(`/api/dispatches/${enc(id)}/lane${qs({ key })}`),
  planDispatch: (epic: string, settings: Partial<DispatchSettings>) => post<DispatchPlan>('/api/dispatches/plan', { epic, settings }),
  startDispatch: (epic: string, settings: Partial<DispatchSettings>) => post<Dispatch>('/api/dispatches', { epic, settings }),
  dispatchSettings: (id: string, s: Partial<DispatchSettings>) => post<Dispatch>(`/api/dispatches/${enc(id)}/settings`, s),
  dispatchState: (id: string, state: Exclude<DispatchState, 'done'>) => post<Dispatch>(`/api/dispatches/${enc(id)}/state`, { state }),
  laneAction: (id: string, lane: string, action: LaneAction, text?: string) => post<Dispatch>(`/api/dispatches/${enc(id)}/lane`, { lane, action, text }),
  endAction: (id: string, action: EndAction) => post<Dispatch>(`/api/dispatches/${enc(id)}/end`, { action }),
  dispatchSeen: (id: string) => post<Dispatch>(`/api/dispatches/${enc(id)}/seen`),

  // ---- repos and settings
  registerRepo: (slug: string, path: string) => post<{ path: string; repos: ReposResponse['repos'] }>('/api/repos/register', { slug, path }),
  removeRepo: (slug: string) => post('/api/repos/remove', { slug }),
  checkRepos: () => post<{ problems: Record<string, string | null> }>('/api/repos/check'),
  scanRepos: (roots?: string[]) => post('/api/repos/scan', roots ? { roots } : {}),
  browse: (start?: string) => post<{ path: string | null }>('/api/repos/browse', { start }),
  createRepo: (parent: string, name: string, prd_folder?: string) => post<{ slug?: string; path?: string }>('/api/repos/create', { parent, name, prd_folder }),
  publishRepo: (slug: string, owner: string, name: string, priv: boolean) => post('/api/repos/publish', { slug, owner, name, private: priv }),
  suggestFolder: (text: string) => post<Record<string, unknown>>('/api/vault/suggest', { text }),
  saveSettings: (s: Partial<Settings>) => put<Settings>('/api/settings', s),
  notifyChannel: (event: string, channel: NotifyChannel, on: boolean) => post<NotifySettings>('/api/settings/notify/channel', { event, channel, on }),
  saveNotify: (b: Record<string, unknown>) => post<NotifySettings>('/api/settings/notify', b),
  saveReview: (b: Record<string, unknown>) => post<ReviewSettings>('/api/settings/review', b),
  testAccount: (cmd: string) => post<{ ok: boolean; message: string }>('/api/settings/test', { cmd }),
};
