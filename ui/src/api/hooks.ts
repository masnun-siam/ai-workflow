// TanStack Query hooks, one per resource, with the PRD's polling intervals, and mutation helpers that
// invalidate what they touch. Polling pauses while the tab is hidden unless browser notifications are on.
import { useMutation, useQuery, useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './client';
import { api } from './endpoints';
import type { AfkState, DispatchSettings, DispatchTarget, EndAction, InboxItem, LaneAction, NotifyChannel, SessionsResponse, StreamEvent } from './types';
import { mergeStream } from '../lib/md';
import { showNotification, step } from '../lib/notifier';

export const POLL = { sessions: 3000, inbox: 5000, boards: 15000, stream: 1000, dispatch: 5000 } as const;

const notificationsOn = () => typeof Notification !== 'undefined' && Notification.permission === 'granted';
/** refetch options for a poll: keep going in the background only when notifications are granted. */
const poll = (ms: number) => ({ refetchInterval: ms, refetchIntervalInBackground: notificationsOn() });

export const keys = {
  sessions: ['sessions'] as const,
  session: (id: string) => ['session', id] as const,
  inbox: (repo?: string) => ['inbox', repo ?? ''] as const,
  planning: (repo: string) => ['planning', repo] as const,
  delivery: (repo: string) => ['delivery', repo] as const,
  repos: ['repos'] as const,
  settings: ['settings'] as const,
  notify: ['settings', 'notify'] as const,
  review: ['settings', 'review'] as const,
  offers: ['peer-review'] as const,
  owners: ['owners'] as const,
  branches: (repo: string) => ['branches', repo] as const,
  vaultFolders: ['vault', 'folders'] as const,
  vaultPrd: (folder: string) => ['vault', 'prd', folder] as const,
  cleanup: ['cleanup'] as const,
  prd: (repo: string, path: string) => ['prd', repo, path] as const,
  issue: (repo: string, n: number) => ['issue', repo, n] as const,
  pull: (repo: string, n: number) => ['pull', repo, n] as const,
  open: (repo: string, kind: string) => ['open', repo, kind] as const,
  dispatches: ['dispatches'] as const,
  dispatch: (id: string) => ['dispatch', id] as const,
  dispatchLane: (id: string, key: string) => ['dispatch', id, 'lane', key] as const,
};

/** App-wide browser notifier (FR-6): polls the feed while permission is granted and shows each new event. */
export function useBrowserNotifier() {
  const last = useRef<number | null>(null);
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: () => api.notifications(last.current), enabled: notificationsOn(), retry: false, ...poll(POLL.inbox) });
  useEffect(() => {
    if (!data) return;
    const next = step(last.current, data);
    last.current = next.last;
    if (notificationsOn()) next.show.forEach((e) => showNotification(e.title, { body: e.body, tag: e.tag, path: e.path }));
  }, [data]);
  // a click handled by the service worker asks this window to navigate
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;
    const onMessage = (e: MessageEvent) => {
      if (e.data?.type === 'aiw-open' && String(e.data.path).startsWith('#/')) window.location.hash = e.data.path;
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, []);
}

// ---- reads --------------------------------------------------------------------------------------
/** Sessions, limits, usage, afk, gh: polled every 3 s. Its failure is the app's "offline" signal. */
export const useSessions = () => useQuery({ queryKey: keys.sessions, queryFn: api.sessions, ...poll(POLL.sessions), retry: false });
export const useInbox = (repo?: string) => useQuery({ queryKey: keys.inbox(repo), queryFn: () => api.inbox(repo), ...poll(POLL.inbox), retry: false });
export const useSession = (id: string) => useQuery({ queryKey: keys.session(id), queryFn: () => api.session(id), ...poll(POLL.sessions), retry: false });
export const usePlanning = (repo: string) =>
  useQuery({ queryKey: keys.planning(repo), queryFn: () => api.planning(repo), enabled: !!repo, ...poll(POLL.boards) });
export const useDelivery = (repo: string) =>
  useQuery({ queryKey: keys.delivery(repo), queryFn: () => api.delivery(repo), enabled: !!repo, ...poll(POLL.boards) });
export const useRepos = () => useQuery({ queryKey: keys.repos, queryFn: api.repos, staleTime: 30_000 });
export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: api.settings, staleTime: 30_000 });
export const useNotifySettings = () => useQuery({ queryKey: keys.notify, queryFn: api.notify });
export const useReviewSettings = () => useQuery({ queryKey: keys.review, queryFn: api.review });
export const usePeerReviewOffers = () => useQuery({ queryKey: keys.offers, queryFn: api.peerReviewOffers, staleTime: 60_000 });
export const useOwners = (enabled = true) => useQuery({ queryKey: keys.owners, queryFn: api.owners, enabled });
/** The repo's branches, default first; refetched on every dialog opening so a new branch shows. */
export const useBranches = (repo: string | null) =>
  useQuery({ queryKey: keys.branches(repo ?? ''), queryFn: () => api.branches(repo!), enabled: !!repo, gcTime: 0 });
export const useVaultFolders = (enabled = true) => useQuery({ queryKey: keys.vaultFolders, queryFn: api.vaultFolders, enabled });
export const useVaultPrd = (folder: string) => useQuery({ queryKey: keys.vaultPrd(folder), queryFn: () => api.vaultPrd(folder), enabled: !!folder });
export const useCleanupTargets = (enabled = true) => useQuery({ queryKey: keys.cleanup, queryFn: api.cleanupTargets, enabled, gcTime: 0 });
export const usePrd = (repo: string, path: string) =>
  useQuery({ queryKey: keys.prd(repo, path), queryFn: () => api.prd(repo, path), enabled: !!repo && !!path, staleTime: Infinity, gcTime: 0 });
export const useIssue = (repo: string, n: number) =>
  useQuery({ queryKey: keys.issue(repo, n), queryFn: () => api.issue(repo, n), enabled: !!repo && n > 0 });
export const usePull = (repo: string, n: number) =>
  useQuery({ queryKey: keys.pull(repo, n), queryFn: () => api.pull(repo, n), enabled: !!repo && n > 0 });
/** The repo's open issues or PRs (palette, Start pickers). */
export const useOpenItems = (repo: string, kind: 'issue' | 'pr', enabled = true) =>
  useQuery({ queryKey: keys.open(repo, kind), queryFn: () => api.open(repo, kind), enabled: enabled && !!repo && repo.includes('/'), staleTime: 30_000 });

export const useDispatches = () => useQuery({ queryKey: keys.dispatches, queryFn: api.dispatches, ...poll(POLL.dispatch) });
export const useDispatch = (id: string) => useQuery({ queryKey: keys.dispatch(id), queryFn: () => api.dispatch(id), enabled: !!id, ...poll(POLL.dispatch), retry: false });
/** A herdr lane's pane text (or a headless lane's session id), polled while the lane panel is open. */
export const useDispatchLane = (id: string, key: string, enabled: boolean) =>
  useQuery({ queryKey: keys.dispatchLane(id, key), queryFn: () => api.dispatchLane(id, key), enabled: enabled && !!id && !!key, ...poll(3000), retry: false });

/**
 * A session's transcript. Appends events from /stream every second while live (the server answers with
 * {events, offset}); stops polling once the session is over and the tail has been read.
 */
export function useTranscript(id: string, live: boolean) {
  const [state, setState] = useState<{ events: StreamEvent[]; offset: number }>({ events: [], offset: 0 });
  const [error, setError] = useState<ApiError | null>(null);
  const ref = useRef(state);
  ref.current = state;
  useEffect(() => {
    setState({ events: [], offset: 0 });
    ref.current = { events: [], offset: 0 };
  }, [id]);
  const tick = useCallback(async () => {
    try {
      const r = await api.stream(id, ref.current.offset);
      setError(null);
      const next = mergeStream(ref.current, r);
      if (next !== ref.current) setState(next);
      return r.events.length > 0;
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      return false;
    }
  }, [id]);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      const more = await tick();
      // a finished session is read until the server has nothing more, then left alone
      if (stop || (!live && !more)) return;
      const bg = document.hidden && !notificationsOn();
      timer = setTimeout(loop, bg ? 5000 : POLL.stream);
    };
    void loop();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [tick, live]);
  return { events: state.events, error };
}

// ---- derived ------------------------------------------------------------------------------------
/** True when the last /api/sessions poll failed: the aiw server is unreachable. */
export function useOffline(): boolean {
  const q = useSessions();
  return q.isError && q.error instanceof ApiError && q.error.offline;
}
/** The Inbox badge: every item except Waiting (FR-7). */
export const needsYouCount = (items: InboxItem[] | undefined) => (items ?? []).filter((i) => i.group !== 'wait').length;

// ---- mutations ----------------------------------------------------------------------------------
type Invalidate<V, R> = QueryKey[] | ((v: V, r: R) => QueryKey[]);
const SESSION_WRITES: QueryKey[] = [['sessions'], ['inbox'], ['session']];
const BOARD_WRITES: QueryKey[] = [['planning'], ['delivery'], ['inbox']];

function invalidateAll(qc: QueryClient, ks: QueryKey[]) {
  return Promise.all(ks.map((queryKey) => qc.invalidateQueries({ queryKey })));
}

/**
 * useMutation + invalidate-after-write. Errors toast automatically (see QueryProvider) unless the call
 * passes `meta: {quiet: true}`; while the server is unreachable the write is refused before it is sent.
 */
export function useApiMutation<V = void, R = unknown>(fn: (v: V) => Promise<R>, invalidate: Invalidate<V, R>, opts: { quiet?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation<R, ApiError, V>({
    mutationFn: async (v) => {
      const s = qc.getQueryState(keys.sessions);
      if (s?.status === 'error' && s.error instanceof ApiError && s.error.offline && s.fetchStatus !== 'fetching') {
        throw new ApiError(0, 'Not sent: the aiw server is unreachable. Try again when it reconnects.');
      }
      return fn(v);
    },
    onSuccess: (r, v) => invalidateAll(qc, typeof invalidate === 'function' ? invalidate(v, r) : invalidate),
    meta: { quiet: opts.quiet },
  });
}

export const useStartSession = () => useApiMutation(api.startSession, SESSION_WRITES);
export const useStartBoard = () => useApiMutation(api.startBoard, [...SESSION_WRITES, ...BOARD_WRITES]);
// resume and rerun are quiet: callers show the error with useStartError (409 duplicate gets an "Open it" action)
export const useRerun = () => useApiMutation(api.rerun, SESSION_WRITES, { quiet: true });
export const useStartNow = () => useApiMutation(api.startNow, SESSION_WRITES);
export const useStop = () => useApiMutation(api.stop, SESSION_WRITES);
export const useResume = () => useApiMutation((v: { id: string; claude_cmd?: string }) => api.resume(v.id, v.claude_cmd), SESSION_WRITES, { quiet: true });
export const useCancelAuto = () => useApiMutation(api.cancelAuto, SESSION_WRITES);
export const useAnswer = () => useApiMutation((v: { id: string; body: Parameters<typeof api.answer>[1] }) => api.answer(v.id, v.body), SESSION_WRITES, { quiet: true });
export const usePrompt = () => useApiMutation((v: { id: string; text: string }) => api.prompt(v.id, v.text), SESSION_WRITES);
export const useCleanupSessions = () => useApiMutation(api.cleanupSessions, [['sessions'], ['cleanup']]);

/** An Away write returns the new state: show it now, since a /api/sessions refetch can take seconds under load. */
function useAfkWrite<V>(fn: (v: V) => Promise<AfkState>) {
  const qc = useQueryClient();
  return useApiMutation(async (v: V) => {
    const afk = await fn(v);
    qc.setQueryData<SessionsResponse>(keys.sessions, (d) => d && { ...d, afk });
    return afk;
  }, [['sessions'], ['inbox']]);
}
export const useAfkStart = () => useAfkWrite(api.afkStart);
export const useAfkStop = () => useAfkWrite(api.afkStop);
// quiet: the Change dialog shows its own toast and errors, like useAnswer
export const useAfkChange = () => useApiMutation(api.afkChange, [['sessions'], ['inbox']], { quiet: true });
export const useAfkDismiss = () => useAfkWrite(api.afkDismiss);

export const useCloseEpic = () => useApiMutation((v: { repo: string; epic: number }) => api.closeEpic(v.repo, v.epic), BOARD_WRITES);
export const useCleanupIssue = () => useApiMutation((v: { repo: string; issue: number }) => api.cleanupIssue(v.repo, v.issue), BOARD_WRITES);
export const useSkipCi = () => useApiMutation((v: { repo: string; pr: number }) => api.skipCi(v.repo, v.pr), [...BOARD_WRITES, ['pull']]);
export const useStopGrind = () => useApiMutation((v: { repo: string; pr: number }) => api.stopGrind(v.repo, v.pr), [...BOARD_WRITES, ['pull']]);
export const useGrindIssue = () =>
  useApiMutation((v: { repo: string; issue: number; on: boolean }) => api.grindIssue(v.repo, v.issue, v.on), [...BOARD_WRITES, ['pull']]);
export const useMerge = () =>
  useApiMutation((v: { repo: string; n: number }) => api.merge(v.repo, v.n), (v) => [...BOARD_WRITES, ['pull', v.repo, v.n], ['issue', v.repo]], { quiet: true });
export const useComment = () =>
  useApiMutation(
    (v: { kind: 'issues' | 'pulls'; repo: string; n: number; text: string }) => api.comment(v.kind, v.repo, v.n, v.text),
    (v) => [[v.kind === 'issues' ? 'issue' : 'pull', v.repo, v.n]],
  );
export const useSetIssueState = () =>
  useApiMutation(
    (v: { repo: string; n: number; state: 'closed' | 'open'; reason?: 'completed' | 'not_planned' }) => api.setIssueState(v.repo, v.n, v.state, v.reason),
    (v) => [...BOARD_WRITES, ['issue', v.repo, v.n]],
  );

export const useSavePrd = () =>
  useApiMutation(
    (v: { repo: string; path: string; text: string; base_sha?: string }) => api.savePrd(v.repo, v.path, v.text, v.base_sha),
    (v) => [keys.prd(v.repo, v.path), ['planning']],
    { quiet: true },
  );
export const useStartReview = () =>
  useApiMutation((v: { repo: string; artifact: string; lenses: string[]; root_session?: string }) => api.startReview(v.repo, v.artifact, v.lenses, v.root_session), [...BOARD_WRITES, ['sessions']]);
export const useReviewLens = () => useApiMutation((v: { panel: string; lens: string; action: string }) => api.reviewLens(v.panel, v.lens, v.action), BOARD_WRITES);
export const useReviewRounds = () => useApiMutation((v: { panel: string; add: number }) => api.reviewRounds(v.panel, v.add), BOARD_WRITES);

export const useRegisterRepo = () => useApiMutation((v: { slug: string; path: string }) => api.registerRepo(v.slug, v.path), [keys.repos, ['inbox']]);
export const useRemoveRepo = () => useApiMutation(api.removeRepo, [keys.repos, keys.settings, ['inbox']]);
export const useScanRepos = () => useApiMutation((roots?: string[]) => api.scanRepos(roots), [keys.repos]);
export const useCreateRepo = () => useApiMutation((v: { parent: string; name: string; prd_folder?: string }) => api.createRepo(v.parent, v.name, v.prd_folder), [keys.repos, ['sessions']]);
export const usePublishRepo = () => useApiMutation((v: { slug: string; owner: string; name: string; priv: boolean }) => api.publishRepo(v.slug, v.owner, v.name, v.priv), [keys.repos, ['inbox']]);
export const useSaveSettings = () => useApiMutation(api.saveSettings, [keys.settings, keys.repos]);
export const useSaveNotifyChannel = () => useApiMutation((v: { event: string; channel: NotifyChannel; on: boolean }) => api.notifyChannel(v.event, v.channel, v.on), [keys.notify]);
export const useNotifyTest = () => useApiMutation(api.notifyTest, []);
export const useSaveNotify = () => useApiMutation(api.saveNotify, [keys.notify]);
export const useSaveReview = () => useApiMutation(api.saveReview, [keys.review, keys.offers]);

const DISPATCH_WRITES: QueryKey[] = [['dispatches'], ['dispatch'], ['inbox']];
export const usePlanDispatch = () =>
  useApiMutation((v: { target: DispatchTarget; settings: Partial<DispatchSettings> }) => api.planDispatch(v.target, v.settings), [], { quiet: true });
export const useStartDispatch = () =>
  useApiMutation((v: { target: DispatchTarget; settings: Partial<DispatchSettings> }) => api.startDispatch(v.target, v.settings), [...DISPATCH_WRITES, ['sessions']]);
export const useDispatchSettings = () =>
  useApiMutation((v: { id: string; s: Partial<DispatchSettings> }) => api.dispatchSettings(v.id, v.s), DISPATCH_WRITES);
export const useDispatchState = () =>
  useApiMutation((v: { id: string; state: 'running' | 'paused' | 'cancelled' }) => api.dispatchState(v.id, v.state), DISPATCH_WRITES);
export const useLaneAction = () =>
  useApiMutation((v: { id: string; lane: string; action: LaneAction; text?: string }) => api.laneAction(v.id, v.lane, v.action, v.text), DISPATCH_WRITES);
export const useEndAction = () => useApiMutation((v: { id: string; action: EndAction }) => api.endAction(v.id, v.action), DISPATCH_WRITES);
export const useDispatchSeen = () => useApiMutation((id: string) => api.dispatchSeen(id), DISPATCH_WRITES, { quiet: true });
