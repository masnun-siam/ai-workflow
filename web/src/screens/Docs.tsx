/** Docs (blubird 1.2 FR-6, FR-8, FR-10): the selected product's business docs by module, the docs gate and the
 *  business validation epics. A doc opens full page at `#/docs/<encoded path>?product=` (DocPage). Read-only. */
import { useEffect } from "preact/hooks";
import type { BusinessDoc, BusinessGate, ValidationEpic } from "../api/types";
import { business, load, loadErrors, product, products } from "../state/data";
import { exec } from "../state/exec";
import { ago } from "../state/format";
import { route } from "../state/route";
import { Header } from "../components/Header";
import { CollectDocs, DocReader, docHref } from "../components/BusinessDoc";
import { Btn, Empty, Tag } from "../components/ui";
import { IssueRow } from "./FeaturePage";

export function Docs() {
  return route.value.id ? <DocPage /> : <DocList />;
}

const OTHER = "other";
export const moduleName = (m: string) => (m === OTHER ? "Other" : m);
/** Modules alphabetically, `other` last. */
export function moduleOrder(mods: Iterable<string>): string[] {
  return [...new Set(mods)].sort((a, b) => (a === OTHER ? 1 : b === OTHER ? -1 : a.localeCompare(b)));
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const COUNTS: [keyof BusinessDoc["counts"], string, string][] = [
  ["not_delivered", "not delivered", "c-b"], ["partly_delivered", "partly delivered", "c-w"], ["drifted", "drifted", "c-b"],
  ["built_differently", "built differently", "c-w"], ["planned", "planned", "c-q"], ["open_questions", "open question", "c-w"],
];

function GateStatus({ g }: { g: BusinessGate }) {
  const [label, tone] = g.state === "pass" ? ["Gate passes", "c-o"] : g.state === "fail" ? ["Gate fails", "c-b"] : ["Gate unavailable", "c-w"];
  const line = (
    <span class="gate-line">
      <Tag tone={tone}>{label}</Tag>
      {g.state === "unavailable" && g.reason && <span>{g.reason}</span>}
      {g.state === "fail" && <span class="dim">{plural(g.failures.length, "failure line")}</span>}
      {g.running && <span class="tag c-q" role="status">checking…</span>}
      {g.checked_at && <span class="dim">checked {ago(g.checked_at)}</span>}
    </span>
  );
  if (!g.failures.length) return <div class="gate" aria-label="Docs gate">{line}</div>;
  return (
    <details class="gate" open aria-label="Docs gate">
      <summary>{line}</summary>
      <pre class="gate-out">{g.failures.join("\n")}</pre>
    </details>
  );
}

function DocRow({ d, repo }: { d: BusinessDoc; repo: string }) {
  const c = d.counts;
  return (
    <a class="drow" href={docHref(d.product || repo, d.path)}>
      <span class="t"><b>{d.title || d.feature}</b>{d.updated && <span class="dim"> · Updated {d.updated}</span>}</span>
      {d.error ? <span class="tag c-b">{d.error}</span> : (
        <span class="dcounts">
          <span class="dim">{plural(d.rules, "rule")}</span>
          {COUNTS.filter(([k]) => c[k] > 0).map(([k, w, tone]) => <span key={k} class={`tag ${tone}`}>{k === "open_questions" ? plural(c[k], w) : `${c[k]} ${w}`}</span>)}
        </span>
      )}
    </a>
  );
}

function EpicBlock({ e }: { e: ValidationEpic }) {
  return (
    <div class="vepic">
      <div class="fs-head">
        <a class="fs-title" href={e.url} target="_blank" rel="noreferrer">{e.title}</a>
        <span class="dim mono">#{e.n}</span>
        <span class="grow" />
        <div class="acts">{e.actions.map((a) => <Btn key={a.label} small primary={a.primary} onClick={() => exec(a)}>{a.label}</Btn>)}</div>
      </div>
      {e.issues.map((i) => <IssueRow key={i.key} i={i} f={{ issues: e.issues, done: [] }} picked={false} />)}
      {!e.issues.length && <span class="dim">No open child issues.</span>}
    </div>
  );
}

function DocList() {
  const p = product.value;
  useEffect(() => { void load("business"); }, [p]);
  const err = loadErrors.value.business;
  const data = business.value && business.value.product === p ? business.value : null;
  const mods = data ? moduleOrder([...data.docs.map((d) => d.module), ...data.epics.map((e) => e.module)]) : [];
  return (
    <>
      <Header title="Docs" products sub={data ? <>{plural(data.docs.length, "business doc")}{data.epics.length ? `, ${plural(data.epics.length, "validation epic")}` : ""}</> : undefined} />
      {err && <div class="banner bad" role="alert">{err}</div>}
      {!p && products.value && <Empty>No product with a docs repo yet. Add one in <a href="#/settings?pane=products">Settings → products and repos</a>.</Empty>}
      {p && !data && !err && <Empty>Loading business docs…</Empty>}
      {data && <GateStatus g={data.gate} />}
      {data && !data.docs.length && <Empty>No business docs in this product yet: they live in <span class="mono">docs/business/</span>. <CollectDocs repo={p} /></Empty>}
      {data && mods.map((m) => {
        const docs = data.docs.filter((d) => d.module === m).sort((a, b) => a.feature.localeCompare(b.feature));
        const epics = data.epics.filter((e) => e.module === m);
        return (
          <section key={m} class="bay" aria-label={`Module ${moduleName(m)}`}>
            <h2 class="bay-h">{moduleName(m)}{docs.length > 0 && <> <span class="dim">{docs.length}</span></>}</h2>
            {docs.map((d) => <DocRow key={d.path} d={d} repo={data.product} />)}
            {epics.map((e) => <EpicBlock key={`${e.repo}#${e.n}`} e={e} />)}
          </section>
        );
      })}
    </>
  );
}

function DocPage() {
  const r = route.value;
  const path = r.id!;
  const repo = r.query.product || product.value || "";
  const doc = business.value?.docs.find((d) => d.path === path);
  const title = doc?.title || path.split("/").pop()!.replace(/\.md$/, "");
  return (
    <>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/docs">Docs</a> › <span>{title}</span></nav>
      <Header title={title} sub={doc?.updated ? `Updated ${doc.updated}` : undefined} />
      {repo ? <DocReader repo={repo} path={path} /> : <Empty>No product for this doc. <a href="#/docs">All docs</a></Empty>}
    </>
  );
}
