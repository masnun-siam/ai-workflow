/** Features (old aiw): every PRD as a strip with its stage, issue bar and next step, in bays by who
 *  it waits on. The feature page (`#/features/<slug>?product=`) is FeaturePage. */
import { useState } from "preact/hooks";
import type { Feature, FeatureStage } from "../api/types";
import { features, inbox, loadErrors, only, products, repoList } from "../state/data";
import { nav, route } from "../state/route";
import { lsGet, lsSet } from "../state/prefs";
import { shortRepo } from "../state/format";
import { openCreate } from "../state/ui";
import { exec } from "../state/exec";
import { Header } from "../components/Header";
import { Btn, Empty } from "../components/ui";
import { FeaturePage } from "./FeaturePage";

export const STAGES: [FeatureStage, string][] = [["draft", "PRD draft"], ["review", "PRD review"], ["approved", "Approved"], ["tasks", "Tasks"], ["building", "Building"], ["shipped", "Shipped"]];
const BAYS: [Feature["bay"], string][] = [["you", "Stopped on you"], ["go", "Waiting for your go"], ["running", "Running on their own"]];

export const featureHref = (f: Feature, tab?: string) => `#/features/${encodeURIComponent(f.slug)}?product=${f.product}${tab ? `&tab=${tab}` : ""}`;

/** Every feature in view: the products the `?only=` repo belongs to, or all. */
export function scopedFeatures(): Feature[] {
  const o = only.value;
  const prod = o ? repoList.value.find((r) => r.slug === o)?.product ?? null : null;
  return (features.value ?? []).filter((l) => !o || l.product === prod || l.product === o || (products.value ?? []).some((p) => p.docs_repo === l.product && p.repos.some((r) => r.repo === o)))
    .flatMap((l) => l.features);
}

export function StageTicks({ stage }: { stage: FeatureStage }) {
  const at = STAGES.findIndex(([s]) => s === stage);
  return (
    <ol class="ticks" aria-label={`Stage: ${STAGES[at]?.[1] ?? stage}`}>
      {STAGES.map(([s, l], i) => <li key={s} class={i < at ? "done" : i === at ? "now" : ""} title={l} aria-current={i === at ? "step" : undefined}><span>{l}</span></li>)}
    </ol>
  );
}

/** Every issue of the epic is done and the epic is still open. */
export const readyToClose = (f: Feature): boolean => !!f.epic && f.counts.open === 0 && f.counts.done > 0 && f.stage !== "shipped";

export function IssueBar({ f }: { f: Feature }) {
  const c = f.counts;
  const total = c.open + c.done;
  if (!total) return null;
  const seg = (n: number, cls: string, label: string) => (n ? <i class={cls} style={{ flexGrow: n }} title={`${n} ${label}`} /> : null);
  const other = c.open - c.unrefined - c.ready - c.review - c.mergeable;
  return (
    <div class="ibar" role="img" aria-label={`${c.done} of ${total} issues done`}>
      {seg(c.done, "b-done", "done")}{seg(c.mergeable, "b-merge", "ready to merge")}{seg(c.review, "b-review", "in review")}
      {seg(Math.max(0, other), "b-work", "in progress")}{seg(c.ready, "b-ready", "ready")}{seg(c.unrefined, "b-todo", "unrefined")}
    </div>
  );
}

/** One line per feature, for long lists. */
function FeatureRow({ f }: { f: Feature }) {
  const next = f.actions.find((a) => a.primary && a.label !== "Read PRD");
  return (
    <div class={`frow bay-${f.bay}`}>
      <a class="fs-title" href={featureHref(f)}>{f.title}</a>
      {readyToClose(f) && <span class="tag c-o">ready to close</span>}
      <span class="dim">{STAGES.find(([s]) => s === f.stage)?.[1] ?? f.stage}</span>
      <span class="mu t">{f.next}</span>
      {next && <Btn small primary onClick={() => exec(next)}>{next.label}</Btn>}
    </div>
  );
}

export function FeatureStrip({ f, link = true }: { f: Feature; link?: boolean }) {
  const c = f.counts;
  return (
    <div class={`fstrip bay-${f.bay}`}>
      <div class="fs-head">
        {link ? <a class="fs-title" href={featureHref(f)}>{f.title}</a> : <b class="fs-title">{f.title}</b>}
        <span class="dim mono">{shortRepo(f.product)}{f.module ? ` · ${f.module}` : ""}{f.epic ? ` · epic #${f.epic.n}` : ""}</span>
        {readyToClose(f) && <span class="tag c-o">ready to close</span>}
        {f.live > 0 && <span class="tag c-q">{f.live} running</span>}
        {f.dispatch && <a class="tag c-q" href="#/dispatches">dispatch {f.dispatch.closed}/{f.dispatch.lanes}</a>}
      </div>
      <StageTicks stage={f.stage} />
      {c.open + c.done > 0 && <div class="fs-bar"><IssueBar f={f} /><span class="dim">{c.done}/{c.open + c.done} done{c.unrefined ? ` · ${c.unrefined} to refine` : ""}{c.ready ? ` · ${c.ready} ready` : ""}{c.mergeable ? ` · ${c.mergeable} to merge` : ""}</span></div>}
      <div class="fs-next"><span class="mu">{f.next}</span>
        <span class="grow" />
        <div class="acts">{f.actions.filter((a) => a.label !== "Read PRD").map((a) => <Btn key={a.label} small primary={a.primary} onClick={() => exec(a)}>{a.label}</Btn>)}</div>
      </div>
    </div>
  );
}

export function Features() {
  return route.value.id ? <FeaturePage /> : <FeatureList />;
}

const COMPACT_KEY = "setu.features.compact";

function FeatureList() {
  const [shipped, setShipped] = useState(false);
  const [q, setQ] = useState("");
  const all = scopedFeatures();
  const [compactPref, setCompactPref] = useState<string | null>(() => lsGet(COMPACT_KEY));
  // Many features default to one line each, so 20 "Approved, Create tasks" strips do not fill the page.
  const compact = compactPref ? compactPref === "1" : all.length > 8;
  const needle = q.trim().toLowerCase();
  const list = all.filter((f) => !needle || `${f.title} ${f.product} ${f.module ?? ""} ${f.next} ${f.stage}`.toLowerCase().includes(needle));
  const by = (b: Feature["bay"]) => list.filter((f) => f.bay === b);
  const you = by("you").length, go = by("go").length;
  const waiting = inbox.value?.count ?? 0;
  const err = loadErrors.value.features;
  const stale = (features.value ?? []).flatMap((l) => l.stale);
  return (
    <>
      <Header title="Features" scope sub={features.value ? <>{you} stopped on you, {go} waiting for your go{waiting ? <> · <a href="#/inbox">{waiting} items wait in Inbox</a></> : null}</> : undefined}>
        <Btn primary onClick={() => openCreate()}>New feature</Btn>
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {stale.length > 0 && <div class="banner">GitHub data is still loading or stale for {stale.map(shortRepo).join(", ")}: issue counts may be missing.</div>}
      {!features.value && <Empty>Loading features…</Empty>}
      {features.value && all.length > 0 && (
        <div class="filters">
          <input type="search" placeholder="Filter features by title, product or stage" aria-label="Filter features" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
          <Btn small onClick={() => { const v = compact ? "0" : "1"; lsSet(COMPACT_KEY, v); setCompactPref(v); }}>{compact ? "Show full strips" : "Compact rows"}</Btn>
        </div>
      )}
      {features.value && all.length > 0 && !list.length && <Empty>No feature matches.</Empty>}
      {features.value && !all.length && (
        <Empty>{(products.value ?? []).length ? "No PRDs yet." : <>No product with a docs repo yet. Add one in <a href="#/settings?pane=products">Settings → products and repos</a>.</>}</Empty>
      )}
      {BAYS.map(([b, name]) => {
        const rows = by(b);
        if (!rows.length) return null;
        return (
          <section key={b} class="bay" aria-label={name}>
            <h2 class="bay-h">{name} <span class="dim">{rows.length}</span></h2>
            {rows.map((f) => (compact ? <FeatureRow key={`${f.product}:${f.path}`} f={f} /> : <FeatureStrip key={`${f.product}:${f.path}`} f={f} />))}
          </section>
        );
      })}
      {by("shipped").length > 0 && (
        <section class="bay">
          <button type="button" class="bay-h linkish" aria-expanded={shipped} onClick={() => setShipped(!shipped)}>{shipped ? "▾" : "▸"} {by("shipped").length} shipped</button>
          {shipped && by("shipped").map((f) => (
            <a key={`${f.product}:${f.path}`} class="row" href={featureHref(f)} onClick={(e) => { e.preventDefault(); nav(featureHref(f)); }}>
              <span class="tag c-o">shipped</span><span class="t">{f.title}</span><span class="w">{shortRepo(f.product)}{f.epic ? ` · epic #${f.epic.n}` : ""}</span>
            </a>
          ))}
        </section>
      )}
    </>
  );
}
