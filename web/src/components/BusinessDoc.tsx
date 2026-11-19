/** Business doc reader (blubird 1.2 FR-7) and the feature page's Business tab (FR-9). Read-only: business docs
 *  change only through the docs skills, which these buttons start. No import from screens/ (FeaturePage imports this). */
import { useEffect, useMemo, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Feature, PRDFile, Session } from "../api/types";
import { describeError } from "../state/actions";
import { businessRev, mutate, registry } from "../state/data";
import { nav } from "../state/route";
import { startReq } from "../state/ui";
import { Markdown, headings } from "./Markdown";
import { Btn, Empty } from "./ui";

export type DocStep = "refine-docs" | "business-code-validator";

/** The `POST /api/sessions` body that runs a docs step on one business doc. */
export function docStepBody(step: DocStep, repo: string, path: string) {
  return { step, repo, product: repo, args: path, guard: true };
}

/** Why a step cannot start: the registry's reason when it lists the step as unavailable, else "".
 *  A step the registry does not list stays enabled: the server answers with its own error. */
export function stepBlocked(id: string): string {
  const s = registry.value.find((x) => x.id === id);
  return s && !s.available ? s.reason || `${id} is not available yet` : "";
}

export const docHref = (repo: string, path: string) => `#/docs/${encodeURIComponent(path)}?product=${repo}`;

async function startDocStep(step: DocStep, repo: string, path: string): Promise<void> {
  const s = await mutate(() => http.send<Session>("POST", "/api/sessions", docStepBody(step, repo, path)), `Started ${step}`, ["features", "sessions"]);
  if (s) nav(`#/sessions/${s.id}`);
}

function StepBtn({ step, label, repo, path }: { step: DocStep; label: string; repo: string; path: string }) {
  const why = stepBlocked(step);
  return (
    <>
      <Btn small disabled={!!why} title={why || undefined} onClick={() => startDocStep(step, repo, path)}>{label}</Btn>
      {why && <span class="dim">{why}</span>}
    </>
  );
}

/** The Collect docs action: opens the Start dialog on `collect-docs`, disabled with a reason when the registry lacks it. */
export function CollectDocs({ repo }: { repo?: string | null }) {
  const s = registry.value.find((x) => x.id === "collect-docs");
  const why = !s ? "collect-docs is not available yet" : s.available ? "" : s.reason || "collect-docs is not available yet";
  return (
    <span class="acts">
      <Btn small primary disabled={!!why} title={why || undefined} onClick={() => { if (s) startReq.value = { step: s, repo: repo ?? undefined }; }}>Collect docs</Btn>
      {why && <span class="dim">{why}</span>}
    </span>
  );
}

/** One doc, rendered: path and branch, the read-only note, the two step buttons, then the TOC and the text. */
export function DocView({ file, err, repo, path }: { file: PRDFile | null; err: string; repo: string; path: string }) {
  const toc = useMemo(() => (file ? headings(file.text) : []), [file?.text]);
  return (
    <>
      {err && <div class="banner bad" role="alert">{err}</div>}
      <div class="acts">
        <StepBtn step="refine-docs" label="Refine this doc" repo={repo} path={path} />
        <StepBtn step="business-code-validator" label="Validate this doc" repo={repo} path={path} />
        <span class="dim doc-where"><span class="mono">{file?.path ?? path}</span>{file?.branch ? ` on ${file.branch}` : ""} · read-only: docs change through the docs skills</span>
      </div>
      {!file && !err && <Empty>Loading…</Empty>}
      {file && toc.length > 1 && (
        <div class="prd-wrap">
          <nav class="toc" aria-label="Table of contents"><ul>{toc.map((h) => <li key={h.id} class={`l${h.level}`}><a href={`#${h.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(h.id)?.scrollIntoView({ block: "start" }); }}>{h.text}</a></li>)}</ul></nav>
          <div class="prd-read"><Markdown text={file.text} /></div>
        </div>
      )}
      {file && toc.length <= 1 && <div class="prd-read"><Markdown text={file.text} /></div>}
    </>
  );
}

/** Fetches a doc and re-fetches it after each business reload (SSE `products{kind:"business"}`). */
export function DocReader({ repo, path }: { repo: string; path: string }) {
  const [file, setFile] = useState<PRDFile | null>(null);
  const [err, setErr] = useState("");
  const rev = businessRev.value;
  useEffect(() => {
    let live = true;
    setErr("");
    setFile((f) => (f && f.repo === repo && f.path === path ? f : null));
    http.get<PRDFile>(`/api/business?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`)
      .then((f) => { if (live) setFile(f); }, (e) => { if (live) { setFile(null); setErr(describeError(e)); } });
    return () => { live = false; };
  }, [repo, path, rev]);
  return <DocView file={file} err={err} repo={repo} path={path} />;
}

/** The feature page's Business tab: the docs that cover the feature, in the server's order, each read inline. */
export function BusinessTab({ f }: { f: Pick<Feature, "product" | "business"> }) {
  const paths = f.business ?? [];
  const [open, setOpen] = useState("");
  const cur = paths.includes(open) ? open : paths[0] ?? "";
  if (!paths.length) return <Empty>No business doc covers this feature yet. <CollectDocs repo={f.product} /></Empty>;
  return (
    <>
      <div class="chips doc-pick" role="group" aria-label="Business docs">
        {paths.map((p) => <button key={p} type="button" class={`chip${p === cur ? " on" : ""}`} aria-pressed={p === cur} onClick={() => setOpen(p)}>{p.replace(/^docs\/business\//, "")}</button>)}
        <a class="dim" href={docHref(f.product, cur)}>Open full page</a>
      </div>
      <DocReader repo={f.product} path={cur} />
    </>
  );
}
