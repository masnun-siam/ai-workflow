// In-memory stand-in for the setu server (API.md section 5), used only by `npm run dev:mock` and tests.
import * as F from "./fixtures";
import type { Session, Release, Away, Dispatch } from "../src/api/types";
import type { EventSourceLike } from "../src/api/sse";

type Db = ReturnType<typeof fresh>;
const fresh = () => structuredClone({
  sessions: F.sessions, river: F.river, inbox: F.inboxItems, status: F.status, products: F.products, repos: F.repos, ops: F.ops, me: F.me,
  grinds: F.grinds, releaseRepos: F.releaseRepos, releases: F.releases, dispatches: F.dispatches, coordinators: F.coordinators, panels: F.panels,
  settings: F.settings, notify: F.notify, review: F.reviewCfg, registry: F.registry,
});
export let db: Db = fresh();
export const resetMock = () => { db = fresh(); };

type Listener = (topic: string, data: unknown) => void;
const listeners = new Set<Listener>();
const emit = (topic: string, data: unknown) => listeners.forEach((l) => l(topic, data));

/** A fake EventSource: says hello, then forwards mock events. */
export function createMockEventSource(): EventSourceLike {
  const handlers = new Map<string, ((ev: MessageEvent) => void)[]>();
  const fire = (t: string, d: unknown) => handlers.get(t)?.forEach((h) => h({ data: JSON.stringify(d) } as MessageEvent));
  const l: Listener = fire;
  listeners.add(l);
  const es: EventSourceLike = {
    addEventListener: (t, fn) => handlers.set(t, [...(handlers.get(t) ?? []), fn]),
    onerror: null, onopen: null, readyState: 1,
    close: () => { listeners.delete(l); },
  };
  setTimeout(() => fire("hello", { version: "0.1.0", boot_id: "boot1", resync: false }), 0);
  return es;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const fail = (status: number, error: string, extra: object = {}) => json({ error, ...extra }, status);
type Ctx = { m: string[]; q: URLSearchParams; body: Record<string, any> };
type H = (c: Ctx) => unknown | Response;
const sess = (id: string) => db.sessions.find((s) => s.id === id);
let seq = 100;

function patchSession(id: string, p: Partial<Session>): Session | undefined {
  const s = sess(id);
  if (s) { Object.assign(s, p); emit("sessions", { id, status: s.status, change: "record" }); }
  return s;
}
function clearNeed(sessionId: string): void {
  db.inbox = db.inbox.filter((i) => i.session_id !== sessionId);
  for (const st of db.river.stages) for (const c of st.cards) if (c.ask?.session_id === sessionId || c.id === `session:${sessionId}`) { c.need = false; c.ask = null; c.need_kind = null; c.tag = "running"; c.tone = "c-q"; c.live = true; }
  emit("inbox", { count: db.inbox.filter((i) => i.group !== "wait").length });
}
function startSession(b: Record<string, any>): Session {
  const id = `20261112T1${String(seq++).padStart(2, "0")}0000000Z-${String(seq).padStart(8, "0")}`.slice(0, 29);
  const s: Session = { ...structuredClone(F.sessions[1]!), id, step: b.step ?? null, title: b.text ?? `${b.step} ${b.args ?? ""}`.trim(), command: b.text ?? `/${b.step} ${b.args ?? ""}`.trim(),
    repo: b.repo ?? null, status: "running", started_at: new Date().toISOString(), cost: 0, duration_s: 0 };
  db.sessions.unshift(s);
  emit("sessions", { id, status: "running", change: "record" });
  return s;
}
const rel = (id: string) => db.releases.find((r) => r.id === id);
function patchRelease(id: string, p: Partial<Release>) {
  const r = rel(id); if (!r) return undefined;
  Object.assign(r, p, { updated_at: new Date().toISOString() });
  emit("products", { kind: "release" }); return r;
}
const disp = (id: string) => db.dispatches.find((d) => d.id === id);
const sessionSub = (action: string): H => ({ m }) => {
  const s = sess(m[1]!); if (!s) return fail(404, "not found");
  const map: Record<string, Partial<Session>> = { stop: { status: "stopped" }, hold: { hold: true }, release: { hold: false }, "start-now": { status: "running" }, dismiss: { dismissed: true }, "cancel-auto": { auto_resume: false }, resume: { status: "running", error: null } };
  return patchSession(s.id, map[action] ?? {});
};

const routes: [string, RegExp, H][] = [
  ["GET", /^\/api\/health$/, () => ({ ok: true })],
  ["GET", /^\/api\/status$/, () => db.status],
  ["GET", /^\/api\/registry$/, () => ({ steps: db.registry })],
  ["GET", /^\/api\/sessions$/, ({ q }) => {
    const st = q.get("status")?.split(","); const repo = q.get("repo");
    return { sessions: db.sessions.filter((s) => (!st || st.includes(s.status)) && (!repo || s.repo === repo)), stats: F.me.cost, limits: {} };
  }],
  ["POST", /^\/api\/sessions$/, ({ body }) => {
    if (!body.step && !body.text) return fail(400, "step or text required");
    if (body.guard && body.step === "implement-issue" && body.args === "1013") return fail(409, "implement-issue already running for acme/wasensi-backend#1013 (session x)", { id: F.sessions[1]!.id, href: `#/sessions/${F.sessions[1]!.id}` });
    if (body.step === "create-prd" && String(body.args).includes("approve")) { db.river.stages[0]!.cards = db.river.stages[0]!.cards.filter((c) => c.id !== "prd:pay"); db.inbox = db.inbox.filter((i) => i.type !== "prd_approval"); emit("inbox", { count: 1 }); }
    return startSession(body);
  }],
  ["GET", /^\/api\/sessions\/cleanup$/, () => ({ items: [] })],
  ["GET", /^\/api\/sessions\/([^/]+)$/, ({ m }) => sess(m[1]!) ?? fail(404, "not found")],
  ["GET", /^\/api\/sessions\/([^/]+)\/stream$/, ({ m, q }) => {
    const ev = F.transcripts[m[1]!] ?? [{ kind: "text" as const, text: "Working on it." }];
    const off = Number(q.get("offset") ?? 0); return { events: ev.slice(off), offset: ev.length };
  }],
  ["POST", /^\/api\/sessions\/([^/]+)\/answer$/, ({ m, body }) => {
    const s = sess(m[1]!); if (!s?.pending_question) return fail(409, "no pending question");
    if (body.round_id !== s.pending_question.id) return fail(409, "stale round");
    clearNeed(s.id);
    return patchSession(s.id, { status: "running", waiting: false, pending_question: null });
  }],
  ["POST", /^\/api\/sessions\/([^/]+)\/prompt$/, ({ body }) => (body.text ? { state: "sent" } : fail(400, "text required"))],
  ["POST", /^\/api\/sessions\/([^/]+)\/rerun$/, ({ m }) => startSession({ step: sess(m[1]!)?.step, repo: sess(m[1]!)?.repo })],
  ["POST", /^\/api\/sessions\/([^/]+)\/(stop|resume|hold|release|start-now|dismiss|cancel-auto)$/, (c) => sessionSub(c.m[2]!)(c)],
  ["GET", /^\/api\/repos$/, () => ({ repos: db.repos, can_browse: true, scan_roots: ["/code"] })],
  ["POST", /^\/api\/repos$/, ({ body }) => { const r = { slug: body.slug, path: body.path, product: null }; db.repos.push(r); return { repo: r, repos: db.repos }; }],
  ["DELETE", /^\/api\/repos\/([^/]+)\/([^/]+)$/, ({ m }) => { db.repos = db.repos.filter((r) => r.slug !== `${m[1]}/${m[2]}`); return { repos: db.repos }; }],
  ["POST", /^\/api\/repos\/scan$/, () => ({ added: [], duplicates: [], repos: db.repos })],
  ["POST", /^\/api\/repos\/check$/, () => ({ problems: Object.fromEntries(db.repos.map((r) => [r.slug, null])) })],
  ["GET", /^\/api\/products$/, () => ({ products: db.products })],
  ["POST", /^\/api\/products$/, ({ body }) => { const p = { docs_repo: "acme/new-docs", name: "New", path: body.path, repos: [] }; db.products.push(p); return json(p, 201); }],
  ["DELETE", /^\/api\/products\/([^/]+)\/([^/]+)$/, ({ m }) => { db.products = db.products.filter((p) => p.docs_repo !== `${m[1]}/${m[2]}`); return { products: db.products }; }],
  ["GET", /^\/api\/prd$/, () => F.prdFile],
  ["GET", /^\/api\/products\/([^/]+)\/([^/]+)\/prds$/, ({ m }) => ({ prds: F.prds.filter((p) => p.product === `${m[1]}/${m[2]}`) })],
  ["POST", /^\/api\/refresh$/, () => json({ ok: true }, 202)],
  ["GET", /^\/api\/river$/, () => db.river],
  ["GET", /^\/api\/inbox$/, () => ({ items: db.inbox, stale: [], count: db.inbox.filter((i) => i.group !== "wait").length })],
  ["GET", /^\/api\/ops$/, () => db.ops],
  ["GET", /^\/api\/me$/, () => db.me],
  ["GET", /^\/api\/grinds$/, () => ({ grinds: db.grinds })],
  ["POST", /^\/api\/grinds\/([^/]+)\/([^/]+)\/(\d+)\/skip-ci$/, () => ({ state: "running" })],
  ["POST", /^\/api\/grinds\/([^/]+)\/([^/]+)\/(\d+)\/stop$/, ({ m }) => { const g = db.grinds.find((x) => x.pr === Number(m[3])); if (g) g.state = "done"; emit("products", { kind: "grind" }); return g; }],
  ["GET", /^\/api\/review$/, () => ({ panels: db.panels })],
  ["GET", /^\/api\/review\/offers$/, () => ({ default: ["critical"], max_rounds: 3, kinds: { "create-prd": ["critical", "ceo", "cto", "security", "qa", "ux"], custom: ["critical", "cto", "security"] } })],
  ["GET", /^\/api\/repos\/([^/]+)\/([^/]+)\/open$/, ({ q }) => ({ items: q.get("kind") === "pr" ? F.openPRs : F.openIssues })],
  ["POST", /^\/api\/vault\/suggest$/, () => ({ project: "wasensi", feature: "payouts", new_project: false, new_feature: false, why: "matches the payouts notes" })],
  ["POST", /^\/api\/repos\/browse$/, () => ({ path: "/code/elsewhere" })],
  ["GET", /^\/api\/dispatches$/, () => ({ dispatches: db.dispatches })],
  ["POST", /^\/api\/dispatches$/, ({ body }) => {
    const d: Dispatch = { ...structuredClone(F.dispatches[0]!), id: "ddddeeeeffff", epic: body.epic ?? null, title: body.epic ?? "Issues", lanes: [] };
    db.dispatches.unshift(d); emit("dispatch", { id: d.id, change: "record" }); return json(d, 201);
  }],
  ["POST", /^\/api\/dispatches\/plan$/, ({ body }) => ({ title: String(body.epic ?? "Plan"), waves: [["acme/wasensi-backend#942"], ["acme/wasensi-backend#943"]],
    lanes: [{ key: "acme/wasensi-backend#942", title: "Cache table", refined: true, deps: [] }, { key: "acme/wasensi-backend#943", title: "Cache reader", refined: false, deps: ["acme/wasensi-backend#942"] }], warnings: ["#943 is not refined"] })],
  ["GET", /^\/api\/dispatches\/([0-9a-f]{12})$/, ({ m }) => disp(m[1]!) ?? fail(404, "not found")],
  ["POST", /^\/api\/dispatches\/([0-9a-f]{12})\/(settings|state|lane|lanes|retry-failed|seen|end)$/, ({ m, body }) => {
    const d = disp(m[1]!); if (!d) return fail(404, "not found");
    if (m[2] === "settings") Object.assign(d.settings, body);
    if (m[2] === "state") d.state = body.state === "cancelled" ? "cancelled" : body.state;
    if (m[2] === "lane") { const l = d.lanes.find((x) => x.key === body.lane); if (l) { if (body.action === "pause") l.paused = true; if (body.action === "resume") l.paused = false; if (body.action === "skip") l.stage = "skipped"; if (body.action === "hold") l.hold_merge = true; if (body.action === "unhold") l.hold_merge = false; } }
    emit("dispatch", { id: d.id, change: "record" }); return d;
  }],
  ["GET", /^\/api\/coordinators$/, () => ({ coordinators: db.coordinators })],
  ["POST", /^\/api\/coordinators\/([^/]+)\/stop$/, ({ m }) => { db.coordinators = db.coordinators.filter((c) => c.run !== m[1]); emit("products", { kind: "coordinator" }); return { ok: true }; }],
  ["POST", /^\/api\/away$/, ({ body }) => { const a: Away = { active: true, until: body.until, started: Math.floor(Date.now() / 1000), decisions: 0, held: 0, summary: null }; db.status.away = a; emit("usage", { kind: "away" }); return a; }],
  ["POST", /^\/api\/away\/(stop|dismiss)$/, () => { db.status.away = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null }; emit("usage", { kind: "away" }); return db.status.away; }],
  ["GET", /^\/api\/vault\/folders$/, () => F.vault],
  ["GET", /^\/api\/releases$/, () => ({ repos: db.releaseRepos, releases: db.releases })],
  ["POST", /^\/api\/releases$/, ({ body }) => {
    if (db.releases.some((r) => r.repo === body.repo && !["done", "skipped", "failed"].includes(r.stage))) return fail(409, "a release is in flight", { id: "r-x" });
    const r: Release = { ...structuredClone(F.releases[1]!), id: `r-20261112T1${seq++}00Z-cccccc`, repo: body.repo, stage: body.dry_run ? "dry_run" : "cut", dry_run: !!body.dry_run, pr: null, grind: null };
    db.releases.unshift(r); emit("products", { kind: "release" }); return json(r, 201);
  }],
  ["POST", /^\/api\/releases\/([^/]+)\/grind$/, ({ m }) => patchRelease(m[1]!, { stage: "grind" }) ?? fail(404, "not found")],
  ["POST", /^\/api\/releases\/([^/]+)\/note$/, ({ m }) => { const r = rel(m[1]!); if (!r) return fail(404, "not found"); if (r.note_posted_at) return fail(409, "already posted"); return patchRelease(m[1]!, { note: r.note ?? F.note }); }],
  ["PUT", /^\/api\/releases\/([^/]+)\/note$/, ({ m, body }) => { const r = rel(m[1]!); if (r?.note_posted_at) return fail(409, "already posted"); return patchRelease(m[1]!, { note: body.text }) ?? fail(404, "not found"); }],
  ["POST", /^\/api\/releases\/([^/]+)\/post$/, ({ m }) => {
    const r = rel(m[1]!); if (!r) return fail(404, "not found"); if (r.note_posted_at) return fail(409, "already posted"); if (!r.note) return fail(409, "no note");
    db.inbox = db.inbox.filter((i) => i.type !== "release_note"); for (const c of db.river.stages[6]!.cards) { c.need = false; c.tag = "done"; c.tone = "c-o"; }
    return patchRelease(m[1]!, { stage: "done", note_posted_at: new Date().toISOString() });
  }],
  ["POST", /^\/api\/releases\/([^/]+)\/skip$/, ({ m }) => patchRelease(m[1]!, { stage: "skipped" }) ?? fail(404, "not found")],
  ["GET", /^\/api\/settings$/, () => db.settings],
  ["PUT", /^\/api\/settings$/, ({ body }) => { Object.assign(db.settings, body); emit("usage", { kind: "settings" }); return db.settings; }],
  ["POST", /^\/api\/settings\/test-account$/, ({ body }) => ({ ok: body.label === "work", message: body.label === "work" ? "logged in" : "not logged in" })],
  ["GET", /^\/api\/settings\/review$/, () => db.review],
  ["PUT", /^\/api\/settings\/review$/, ({ body }) => { if (body.reset) db.review = { ...db.review, ...db.review.shipped, overridden: false }; else Object.assign(db.review, body, { overridden: true }); return db.review; }],
  ["GET", /^\/api\/settings\/notify$/, () => db.notify],
  ["PUT", /^\/api\/settings\/notify$/, ({ body }) => { if (body.public_url !== undefined) db.notify.public_url = body.public_url; if (body.cell) (db.notify.matrix as any)[body.cell.event][body.cell.channel] = body.cell.on; return db.notify; }],
  ["POST", /^\/api\/settings\/notify\/test$/, ({ body }) => (body.channel === "mac" ? { ok: true } : { ok: false, error: "no subscriptions" })],
  ["GET", /^\/api\/blubird$/, () => db.status.blubird],
  ["POST", /^\/api\/blubird\/(install|update)$/, () => { db.status.blubird.busy = "updating"; setTimeout(() => { db.status.blubird.busy = ""; emit("products", { kind: "blubird" }); emit("toast", { id: 1, event: "info", title: "blubird", body: "up to date", path: "#/settings", level: "info" }); }, 800); emit("products", { kind: "blubird" }); return json(db.status.blubird, 202); }],
];

/** `fetch`-shaped entry point. */
export async function mockFetch(input: string, init?: RequestInit): Promise<Response> {
  const method = init?.method ?? "GET";
  const [path = "", qs = ""] = input.split("?");
  let body: Record<string, any> = {};
  if (typeof init?.body === "string") { try { body = JSON.parse(init.body); } catch { return fail(400, "body must be a JSON object"); } }
  for (const [m, re, h] of routes) {
    if (m !== method) continue;
    const match = re.exec(path);
    if (!match) continue;
    const out = h({ m: [...match], q: new URLSearchParams(qs), body });
    return out instanceof Response ? out : json(out);
  }
  return fail(404, `mock: no route ${method} ${path}`);
}
