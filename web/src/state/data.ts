import { signal, computed } from "@preact/signals";
import { http } from "../api/http";
import type { RegistryStep, SessionList } from "../api/extra";
import type {
  ChangesList, Coordinator, Dispatch, FeatureList, GrindStatus, InboxList, Me, NotifySettings, Ops, Panel, Product, Repo, ReleaseRepo,
  Release, ReviewConfig, River, Settings, Status, Transcript, TranscriptEvent, Session, Blubird, Slug,
} from "../api/types";
import type { LoadKey, View } from "./refetch";
import { describeError } from "./actions";
import { lsGet, lsSet } from "./prefs";
import { route } from "./route";
import { toast } from "./ui";

export const status = signal<Status | null>(null);
export const river = signal<River | null>(null);
export const inbox = signal<InboxList | null>(null);
export const sessionList = signal<SessionList | null>(null);
export const sessionOne = signal<Session | null>(null);
export const transcript = signal<{ id: string; events: TranscriptEvent[]; offset: number }>({ id: "", events: [], offset: 0 });
export const releases = signal<{ repos: ReleaseRepo[]; releases: Release[] } | null>(null);
export const ops = signal<Ops | null>(null);
export const me = signal<Me | null>(null);
export const settings = signal<Settings | null>(null);
export const notify = signal<NotifySettings | null>(null);
export const reviewCfg = signal<ReviewConfig | null>(null);
export const blubird = signal<Blubird | null>(null);
export const products = signal<Product[] | null>(null);
export const repos = signal<{ repos: Repo[]; can_browse: boolean; scan_roots: string[] } | null>(null);
export const dispatches = signal<Dispatch[] | null>(null);
export const coordinators = signal<Coordinator[] | null>(null);
export const grinds = signal<GrindStatus[] | null>(null);
export const panels = signal<Panel[] | null>(null);
export const registry = signal<RegistryStep[]>([]);
/** Features of every product (old aiw opened Features on all repos; the page filters by `?only=`). */
export const features = signal<FeatureList[] | null>(null);
export const changes = signal<ChangesList | null>(null);
export const loadErrors = signal<Record<string, string>>({});
export type ActivityTab = "sessions" | "coordinators" | "grinds" | "panels";
export const activityTab = signal<ActivityTab>("sessions");

/** Ids optimistically hidden after an action with `clears`; reset when the list reloads. */
export const dropped = signal<ReadonlySet<string>>(new Set());
export const drop = (id: string) => (dropped.value = new Set([...dropped.value, id]));

const PRODUCT_KEY = "setu.product";
export const productSel = signal<Slug | null>(lsGet(PRODUCT_KEY));
export const product = computed<Slug | null>(() => {
  const list = products.value ?? [];
  const s = productSel.value;
  if (s && list.some((p) => p.docs_repo === s)) return s;
  return list[0]?.docs_repo ?? null;
});
export function chooseProduct(s: Slug): void {
  if (productSel.peek() === s && product.peek() === s) return;
  productSel.value = s;
  lsSet(PRODUCT_KEY, s);
  void load("river"); void load("releases"); void load("ops");
}

/** The current repo (old aiw FR-3): `?repo=` in the URL, else the remembered one, else the first registered.
 *  It is the default "where" for new runs and picks the product River, Releases and Ops show. */
const REPO_KEY = "setu.repo";
export const repoSel = signal<Slug | null>(lsGet(REPO_KEY));
export const repoList = computed(() => repos.value?.repos ?? []);
export const currentRepo = computed<Slug | null>(() => {
  const fromUrl = route.value.query.repo;
  if (fromUrl) return fromUrl;
  const list = repoList.value;
  const s = repoSel.value;
  if (s && (!repos.value || list.some((r) => r.slug === s))) return s;
  return list[0]?.slug ?? null;
});
export function chooseRepo(s: Slug): void {
  repoSel.value = s;
  lsSet(REPO_KEY, s);
  const p = repoList.peek().find((r) => r.slug === s)?.product;
  if (p) chooseProduct(p);
}

/** The page's repo filter (old aiw FR-1): `?only=owner/name`, independent of the current repo. "" = all repos. */
export const only = computed<Slug>(() => {
  const raw = route.value.query.only ?? "";
  if (!raw || !repos.value) return raw;
  return repoList.value.find((r) => r.slug.toLowerCase() === raw.toLowerCase())?.slug ?? "";
});
const sameRepo = (a: string | null | undefined, b: string) => !!a && a.toLowerCase() === b.toLowerCase();
/** True when `repo` passes the page filter. Items without a repo always pass. */
export const inScope = (repo: string | null | undefined): boolean => !only.value || !repo || sameRepo(repo, only.value);

export function currentView(): View {
  const r = route.value;
  return { screen: r.screen, sessionId: r.screen === "activity" ? r.id : undefined, tab: activityTab.value };
}

const q = (p: Slug | null) => (p ? `?product=${encodeURIComponent(p)}` : "");
type Loader = () => Promise<unknown>;
const loaders: Record<LoadKey, Loader> = {
  status: async () => (status.value = await http.get<Status>("/api/status")),
  river: async () => { river.value = await http.get<River>(`/api/river${q(product.value)}`); dropped.value = new Set(); },
  inbox: async () => { inbox.value = await http.get<InboxList>("/api/inbox"); dropped.value = new Set(); },
  sessions: async () => (sessionList.value = await http.get<SessionList>("/api/sessions?limit=500")),
  session: async () => { const id = route.value.id; if (id) sessionOne.value = await http.get<Session>(`/api/sessions/${id}`); },
  stream: async () => { await loadStream(route.value.id); },
  releases: async () => (releases.value = await http.get(`/api/releases${q(product.value)}`)),
  ops: async () => (ops.value = await http.get<Ops>(`/api/ops${q(product.value)}`)),
  me: async () => (me.value = await http.get<Me>("/api/me")),
  settings: async () => (settings.value = await http.get<Settings>("/api/settings")),
  notify: async () => (notify.value = await http.get<NotifySettings>("/api/settings/notify")),
  review: async () => (reviewCfg.value = await http.get<ReviewConfig>("/api/settings/review")),
  blubird: async () => (blubird.value = await http.get<Blubird>("/api/blubird")),
  products: async () => (products.value = (await http.get<{ products: Product[] }>("/api/products")).products),
  repos: async () => (repos.value = await http.get("/api/repos")),
  dispatches: async () => (dispatches.value = (await http.get<{ dispatches: Dispatch[] }>("/api/dispatches")).dispatches),
  coordinators: async () => (coordinators.value = (await http.get<{ coordinators: Coordinator[] }>("/api/coordinators")).coordinators),
  grinds: async () => (grinds.value = (await http.get<{ grinds: GrindStatus[] }>("/api/grinds")).grinds),
  panels: async () => (panels.value = (await http.get<{ panels: Panel[] }>("/api/review")).panels),
  registry: async () => (registry.value = (await http.get<{ steps: RegistryStep[] }>("/api/registry")).steps),
  changes: async () => { const o = only.peek(); changes.value = await http.get<ChangesList>(`/api/changes${o ? `?repo=${encodeURIComponent(o)}` : ""}`); },
  features: async () => {
    const ps = products.value ?? (await http.get<{ products: Product[] }>("/api/products")).products;
    features.value = await Promise.all(ps.map((p) => http.get<FeatureList>(`/api/features?product=${encodeURIComponent(p.docs_repo)}`)));
  },
};

const MAX_EVENTS = 1500; // bounded buffer: older transcript lines are dropped from memory
export async function loadStream(id: string | undefined): Promise<void> {
  if (!id) return;
  const cur = transcript.peek();
  const from = cur.id === id ? cur.offset : 0;
  const t = await http.get<Transcript>(`/api/sessions/${id}/stream?offset=${from}`);
  const base = cur.id === id ? cur.events : [];
  transcript.value = { id, events: [...base, ...t.events].slice(-MAX_EVENTS), offset: t.offset };
}

const inflight = new Map<LoadKey, boolean>(); // value: another load was requested meanwhile
export async function load(key: LoadKey): Promise<void> {
  if (inflight.has(key)) { inflight.set(key, true); return; }
  inflight.set(key, false);
  try {
    await loaders[key]();
    if (loadErrors.peek()[key]) { const { [key]: _, ...rest } = loadErrors.peek(); loadErrors.value = rest; }
  } catch (e) {
    loadErrors.value = { ...loadErrors.peek(), [key]: describeError(e) };
  } finally {
    const again = inflight.get(key);
    inflight.delete(key);
    if (again) void load(key);
  }
}
export const loadMany = (keys: LoadKey[]) => Promise.all(keys.map(load)).then(() => undefined);

/** One-shot mutation helper for forms: runs, toasts the result or the error, then reloads `keys`. */
export async function mutate<T>(fn: () => Promise<T>, okMsg: string | null, keys: LoadKey[] = []): Promise<T | undefined> {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg);
    void loadMany(keys);
    return r;
  } catch (e) {
    toast(describeError(e), "error");
    return undefined;
  }
}
