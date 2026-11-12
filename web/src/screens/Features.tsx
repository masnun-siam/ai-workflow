/** Features (old aiw): every PRD as a strip with its stage, issue bar and next step, in bays by who
 *  it waits on. The feature page (`#/features/<slug>?product=`) is FeaturePage. */
import { useState } from "preact/hooks";
import type { Feature, FeatureStage } from "../api/types";
import { features, inbox, loadErrors, only, products, repoList } from "../state/data";
import { nav, route } from "../state/route";
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
      {STAGES.map(([s, l], i) => <li key={s} class={i < at ? "done" : i === at ? "now" : ""} title={l}><span>{l}</span></li>)}
    </ol>
  );
}

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

export function FeatureStrip({ f, link = true }: { f: Feature; link?: boolean }) {
  const c = f.counts;
  return (
    <div class={`fstrip bay-${f.bay}`}>
      <div class="fs-head">
        {link ? <a class="fs-title" href={featureHref(f)}>{f.title}</a> : <b class="fs-title">{f.title}</b>}
        <span class="dim mono">{shortRepo(f.product)}{f.module ? ` · ${f.module}` : ""}{f.epic ? ` · epic #${f.epic.n}` : ""}</span>
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

function FeatureList() {
  const [shipped, setShipped] = useState(false);
  const list = scopedFeatures();
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
      {features.value && !list.length && (
        <Empty>{(products.value ?? []).length ? "No PRDs yet." : <>No product with a docs repo yet. Add one in <a href="#/settings?pane=products">Settings → products and repos</a>.</>}</Empty>
      )}
      {BAYS.map(([b, name]) => {
        const rows = by(b);
        if (!rows.length) return null;
        return (
          <section key={b} class="bay" aria-label={name}>
            <h2 class="bay-h">{name} <span class="dim">{rows.length}</span></h2>
            {rows.map((f) => <FeatureStrip key={`${f.product}:${f.path}`} f={f} />)}
          </section>
        );
      })}
      <button type="button" class="describe" onClick={() => openCreate()}><span class="c-w">+</span> Describe a feature or a fix <kbd>n</kbd></button>
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
