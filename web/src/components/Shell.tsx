/** The old aiw frame on the new stack: rail (pages with counts, Away, usage, theme), top bar (repo switcher,
 *  search, needs-you pill, New) and the repo pickers. */
import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Repo } from "../api/types";
import { chooseRepo, currentRepo, mutate, only, repoList, repos, settings, status } from "../state/data";
import { MODES, next, prefs, setPref } from "../state/prefs";
import { goScreen, nav, route, SCREENS, setParam, type ScreenId } from "../state/route";
import { dispatchingCount, needCount, runningCount } from "../state/select";
import { detailOpen, helpOpen, paletteOpen, repoOpen } from "../state/ui";
import { AWAY_PRESETS, awayLabel } from "../state/away";
import { clock } from "../state/format";
import { Btn, Meter } from "./ui";
import { openCreate } from "../state/ui";
import { Chevron, DdTrigger } from "./Select";

const owner = (slug: string) => slug.split("/")[0] ?? slug;
const short = (slug: string) => slug.split("/").pop() ?? slug;

export type Extra = { value: string; label: string };

/** Searchable repo list grouped by owner (`first` goes under "Current"), with fixed extra rows before and after. */
export function RepoList({ list, first, selected, extrasBefore = [], extrasAfter = [], onPick, label }: {
  list: Repo[]; first?: string | null; selected: string; extrasBefore?: Extra[]; extrasAfter?: Extra[]; onPick: (v: string) => void; label: string;
}) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const s = q.trim().toLowerCase();
  const match = (t: string) => !s || t.toLowerCase().includes(s);
  const groups = new Map<string, Repo[]>();
  const cur = list.find((r) => r.slug === first);
  if (cur && match(cur.slug)) groups.set("Current", [cur]);
  for (const r of [...list].filter((r) => r !== cur && match(r.slug)).sort((a, b) => a.slug.localeCompare(b.slug))) groups.set(owner(r.slug), [...(groups.get(owner(r.slug)) ?? []), r]);
  const before = extrasBefore.filter((e) => match(e.label));
  const after = extrasAfter.filter((e) => match(e.label));
  const flat = [...before.map((e) => e.value), ...[...groups.values()].flat().map((r) => r.slug), ...after.map((e) => e.value)];
  let n = -1;
  const extraRow = (e: Extra) => { n++; const k = n; return <button key={`x-${e.value}`} type="button" role="option" aria-selected={k === i} class={`pi${k === i ? " sel" : ""}`} onMouseMove={() => setI(k)} onClick={() => onPick(e.value)}>{e.label}{e.value === selected && <span class="r">✓</span>}</button>; };
  return (
    <div class="rp" role="dialog" aria-label={label}>
      <input ref={input} class="pal-q" placeholder={`Find a repository (${list.length})…`} aria-label={label} value={q}
        onInput={(e) => { setQ((e.target as HTMLInputElement).value); setI(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { setI(Math.min(i + 1, flat.length - 1)); e.preventDefault(); }
          else if (e.key === "ArrowUp") { setI(Math.max(i - 1, 0)); e.preventDefault(); }
          else if (e.key === "Enter" && flat[i] !== undefined) { onPick(flat[i]!); e.preventDefault(); }
        }} />
      <div class="rp-list" role="listbox">
        {before.map(extraRow)}
        {[...groups].map(([o, rs]) => (
          <div key={o} role="group" aria-label={o}>
            <div class="gh">{o}</div>
            {rs.map((r) => { n++; const k = n; return (
              <button key={r.slug} type="button" role="option" aria-selected={k === i} class={`pi${k === i ? " sel" : ""}`} onMouseMove={() => setI(k)} onClick={() => onPick(r.slug)}>
                <span class="repo-mark" aria-hidden="true">{short(r.slug)[0]?.toUpperCase()}</span>
                <b>{short(r.slug)}</b><span class="dim mono rp-path">{r.path}</span>
                {r.slug === selected && <span class="r">✓</span>}
              </button>
            ); })}
          </div>
        ))}
        {after.map(extraRow)}
        {!flat.length && <div class="empty">No repository matches.</div>}
      </div>
    </div>
  );
}

/** Escape closes an open popover and stops there, so it does not also leave the page or close a drawer. */
export function closeOnEscape(e: Pick<KeyboardEvent, "key" | "stopPropagation" | "preventDefault">, setOpen: (v: boolean) => void): boolean {
  if (e.key !== "Escape") return false;
  setOpen(false); e.stopPropagation(); e.preventDefault();
  return true;
}

/** A popover anchored under its trigger; closes on outside click and Escape. */
export function Popover({ open, setOpen, trigger, children, wide, fit, inline }: { open: boolean; setOpen: (v: boolean) => void; trigger: preact.ComponentChildren; children: preact.ComponentChildren; wide?: boolean; fit?: boolean; inline?: boolean }) {
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { closeOnEscape(e, setOpen); };
    document.addEventListener("mousedown", down);
    box.current?.addEventListener("keydown", key);
    const el = box.current;
    return () => { document.removeEventListener("mousedown", down); el?.removeEventListener("keydown", key); };
  }, [open]);
  return <span class={`popw${fit ? " fit" : ""}${inline ? " inline" : ""}`} ref={box}>{trigger}{open && <div class={`pop${wide ? " wide" : ""}${fit ? " fit" : ""}`}>{children}</div>}</span>;
}

/** The current repo (g r): new runs start here, and it picks the product River, Releases and Ops show. */
export function RepoSwitcher() {
  const open = repoOpen.value;
  const setOpen = (v: boolean) => (repoOpen.value = v);
  const repo = currentRepo.value;
  const name = repo ? short(repo) : "No repo";
  return (
    <Popover open={open} setOpen={setOpen} wide trigger={
      <button type="button" class="repo-btn" aria-expanded={open} title={`${repo ?? "No repository"}. Switch repository (g then r)`} aria-label={`Repository: ${name}. Switch repository`} onClick={() => setOpen(!open)}>
        <span class="repo-mark" aria-hidden="true">{name[0]?.toUpperCase() ?? "?"}</span>
        <span class="repo-txt"><b>{name}</b><span class="dim mono">{repo ?? "add one in Settings"}</span></span>
        <Chevron />
      </button>
    }>
      <RepoList list={repoList.value} first={repo} selected={repo ?? ""} label="Switch repository"
        onPick={(s) => { setOpen(false); chooseRepo(s); if (route.peek().query.repo) setParam("repo", ""); }} />
      <button type="button" class="pi rp-add" onClick={() => { setOpen(false); nav("#/settings?pane=products"); }}>＋ Add a repository</button>
    </Popover>
  );
}

/** Filter the page to one repo or all of them (`?only=`). */
export function RepoScope({ label = "Repository filter" }: { label?: string }) {
  const [open, setOpen] = useState(false);
  const v = only.value;
  return (
    <Popover open={open} setOpen={setOpen} trigger={
      <DdTrigger compact open={open} label={`${label}: ${v ? short(v) : "All repos"}`} onClick={() => setOpen(!open)}>{v ? short(v) : "All repos"}</DdTrigger>
    }>
      <RepoList list={repoList.value} selected={v} label={label} extrasBefore={[{ value: "", label: "All repos" }]}
        onPick={(s) => { setOpen(false); setParam("only", s); }} />
    </Popover>
  );
}

/** The searchable repo picker as a form field, with fixed extra rows ("Another folder…", "No repo yet: notes vault"). */
export function RepoField({ value, onChange, label, extrasBefore, extrasAfter }: { value: string; onChange: (v: string) => void; label: string; extrasBefore?: Extra[]; extrasAfter?: Extra[] }) {
  const [open, setOpen] = useState(false);
  const shown = [...(extrasBefore ?? []), ...(extrasAfter ?? [])].find((e) => e.value === value)?.label ?? (value ? short(value) : "Pick a repository");
  return (
    <Popover open={open} setOpen={setOpen} wide fit trigger={
      <DdTrigger open={open} label={`${label}: ${shown}`} onClick={() => setOpen(!open)}
        aside={value && !value.startsWith(":") && value.includes("/") && !value.startsWith("/") ? <span class="mono">{owner(value)}</span> : undefined}>{shown}</DdTrigger>
    }>
      <RepoList list={repoList.value} first={currentRepo.value} selected={value} label={label} extrasBefore={extrasBefore} extrasAfter={extrasAfter} onPick={(v) => { setOpen(false); onChange(v); }} />
    </Popover>
  );
}

export function Topbar() {
  const need = needCount.value;
  return (
    <div class="topbar">
      <RepoSwitcher />
      <button type="button" class="btn search-btn" onClick={() => (paletteOpen.value = true)} aria-label="Search, jump or run a command" aria-keyshortcuts="Meta+K Control+K">
        <span aria-hidden="true">⌕</span><span class="wide-only">Search, jump or run a command</span><kbd class="wide-only">⌘K</kbd>
      </button>
      <span class="grow" />
      {need > 0 && <a class="you-pill" href="#/inbox"><i />{need} need you</a>}
      <Btn primary k="n" onClick={() => openCreate()}>New</Btn>
    </div>
  );
}

function AwayCard() {
  const a = status.value?.away;
  const [open, setOpen] = useState(false);
  const [end, setEnd] = useState("");
  const go = (until: number) => { setOpen(false); return mutate(() => http.send("POST", "/api/away", { until }), "Away mode on", ["status"]); };
  const inMin = (m: number) => Math.floor(Date.now() / 1000) + m * 60;
  if (a?.active) {
    return (
      <div class="away-card" role="status">
        <b>☾ {awayLabel(a)}</b>
        <span class="dim">Answering what it can, holding the rest. {a.held} held for you. End it from the banner above.</span>
      </div>
    );
  }
  const endEpoch = () => {
    const [h, m] = end.split(":").map(Number);
    if (h === undefined || Number.isNaN(h)) return 0;
    const d = new Date(); d.setHours(h, m || 0, 0, 0);
    if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
    return Math.floor(d.getTime() / 1000);
  };
  return (
    <div class="away-card">
      <div class="dh"><b class="grow">☾ Away mode</b><Btn small onClick={() => setOpen(!open)}>{open ? "Cancel" : "Go away"}</Btn></div>
      {open ? (
        <>
          <div class="acts">{AWAY_PRESETS.map(([m, l]) => <Btn small key={m} onClick={() => go(inMin(m))}>{l}</Btn>)}</div>
          <form class="acts" onSubmit={(e) => { e.preventDefault(); const t = endEpoch(); if (t) void go(t); }}>
            <input type="time" aria-label="Away until" value={end} onInput={(e) => setEnd((e.target as HTMLInputElement).value)} />
            <Btn small type="submit" disabled={!end}>Set</Btn>
          </form>
        </>
      ) : <span class="dim">Claude keeps going without you and saves the rest.</span>}
    </div>
  );
}

function Usage() {
  const usage = status.value?.usage ?? [];
  if (!usage.length) return null;
  return (
    <div class="usage">
      {usage.map((u) => {
        const until = u.limit.limited_until;
        const limited = !!until && until * 1000 > Date.now();
        const five = limited ? 100 : Math.round(u.five_hour?.pct ?? 0);
        const seven = Math.round(u.seven_day?.pct ?? 0);
        return (
          <div key={u.label}>
            <div class="dh"><b class="grow">{u.label}</b>
              {limited ? <span class="c-b">limited until {clock(until!)}</span> : u.error ? <span class="dim" title={u.error}>usage unavailable</span> : <span class="dim">5h {five}% · 7d {seven}%</span>}
            </div>
            {!(u.error && !u.five_hour && !limited) && <Meter pct={five} label={`${u.label} 5-hour usage`} />}
          </div>
        );
      })}
    </div>
  );
}

const ICON: Record<string, string> = { system: "◐", light: "☀", dark: "☾" };

export function Rail() {
  const cur = route.value.screen;
  const count = (id: ScreenId) => (id === "inbox" ? needCount.value : id === "activity" ? runningCount.value : id === "dispatches" ? dispatchingCount.value : 0);
  const mode = prefs.value.mode;
  return (
    <nav class="rail" aria-label="Main">
      <a class="brand" href="#/inbox"><b>setu</b><span>সেতু</span></a>
      {SCREENS.map(([id, name], i) => {
        const on = cur === id;
        const n = count(id);
        return (
          <button key={id} type="button" class={`nv${on ? " on" : ""}${i === 5 ? " sep" : ""}`} aria-current={on ? "page" : undefined}
            onClick={() => { detailOpen.value = false; goScreen(id); }}>
            <kbd>{i === 9 ? 0 : i + 1}</kbd>{name}
            {n > 0 && <span class={`n${id === "inbox" ? "" : " quiet"}`} aria-label={`${n} ${id === "inbox" ? "need you" : "running"}`}>{n}</span>}
          </button>
        );
      })}
      <div class="railfoot">
        <AwayCard />
        <Usage />
        <div class="acts">
          <Btn small title={`Theme: ${mode}`} onClick={() => setPref("mode", next(MODES, mode))}><span aria-hidden="true">{ICON[mode]}</span> {mode}</Btn>
          <Btn small k="?" onClick={() => (helpOpen.value = true)}>keys</Btn>
        </div>
      </div>
    </nav>
  );
}

/** First run (old aiw FR-29): GitHub CLI signed in, a Claude account, then scan folders for repos. */
export function Onboarding() {
  const st = status.value;
  const gh = st?.gh;
  const account = settings.value?.commands?.[0];
  const total = repoList.value.length;
  const [roots, setRoots] = useState<string | null>(null);
  const [found, setFound] = useState<{ added: Repo[] } | null>(null);
  const rootText = roots ?? (repos.value?.scan_roots ?? []).join("\n");
  const find = async () => {
    const r = await mutate(() => http.send<{ added: Repo[] }>("POST", "/api/repos/scan", { roots: rootText.split("\n").map((s) => s.trim()).filter(Boolean) }), null, ["repos", "products"]);
    if (r) setFound(r);
  };
  const check = (ok: boolean | null, title: string, body: preact.ComponentChildren) => (
    <div class="onb-item"><span class={`onb-ico ${ok === true ? "c-o" : ok === false ? "c-w" : "dim"}`} aria-hidden="true">{ok === true ? "✓" : ok === false ? "!" : "…"}</span>
      <div><b>{title}</b><div class="dim">{body}</div></div></div>
  );
  return (
    <div class="onb">
      <div><h1>Set up setu</h1><p class="mu">Two checks, then pick the folders your repositories live in.</p></div>
      {check(gh ? gh.ok : null, gh?.ok ? "GitHub CLI signed in" : gh ? "GitHub CLI is not signed in" : "Checking the GitHub CLI…",
        gh?.ok ? (gh.login ? `as ${gh.login}` : "gh is ready.") : gh ? <>Run <code>gh auth login</code> in a terminal, then come back.{gh.error ? ` (${gh.error})` : ""}</> : null)}
      {check(settings.value ? !!account : null, account ? "Claude account found" : settings.value ? "No Claude account yet" : "Checking Claude…",
        account ? <><code>{account.cmd}</code> is set up as “{account.label}”. Add more in Settings → accounts.</> : settings.value ? "Add one in Settings: a command that starts Claude, like claude." : null)}
      <div class="onb-item"><span class="onb-ico dim" aria-hidden="true">▣</span>
        <div class="form">
          <b>Add your repositories</b>
          <span class="dim">Folders to look in, one per line. Every git checkout with a GitHub origin is registered.</span>
          <textarea class="mono" rows={3} spellcheck={false} aria-label="Folders to scan" value={rootText} onInput={(e) => setRoots((e.target as HTMLTextAreaElement).value)} />
          {found && (found.added.length
            ? <div role="status"><b>Added {found.added.length} {found.added.length === 1 ? "repository" : "repositories"}</b>{found.added.map((r) => <div key={r.slug} class="mono">✓ {r.slug} <span class="dim">{r.path}</span></div>)}</div>
            : <p class="mu" role="status">{total ? "No new repos found." : "No repos found in those folders. Check the paths, or clone a repo there first."}</p>)}
          <div class="acts">
            <Btn primary={!found?.added.length} disabled={!rootText.trim()} onClick={find}>{found ? "Scan again" : "Find repos"}</Btn>
            {total > 0 && <Btn primary onClick={() => nav("#/inbox")}>Done: open the Inbox</Btn>}
          </div>
        </div>
      </div>
    </div>
  );
}
