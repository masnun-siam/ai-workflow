/** Features (old aiw): every PRD of the products in view, by status. Interim for phase 1: the stage strips,
 *  next-step buttons and the feature page come back in phase 3. */
import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { PRD } from "../api/types";
import { inbox, only, products, repoList } from "../state/data";
import { stages } from "../state/select";
import { Header } from "../components/Header";
import { Empty, Pane, Tag } from "../components/ui";

const BAYS: [PRD["status"], string, string][] = [
  ["Draft", "Draft", "c-w"], ["In review", "In review", "c-q"], ["Approved", "Approved: ready for tasks", "c-o"], ["Done", "Shipped", ""],
];

export function Features() {
  const scoped = only.value ? repoList.value.find((r) => r.slug === only.value)?.product ?? only.value : null;
  const list = (products.value ?? []).filter((p) => !scoped || p.docs_repo === scoped || p.repos.some((r) => r.repo === only.value));
  const key = list.map((p) => p.docs_repo).join(",");
  const [prds, setPrds] = useState<PRD[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let live = true;
    setPrds(null);
    Promise.all(list.map((p) => http.get<{ prds: PRD[] }>(`/api/products/${p.docs_repo}/prds`).then((r) => r.prds).catch((e) => { setErr(String(e?.message ?? e)); return []; })))
      .then((all) => live && setPrds(all.flat()));
    return () => { live = false; };
  }, [key]);
  const waiting = inbox.value?.count ?? 0;
  const live = stages.value.flatMap((s) => s.cards).filter((c) => c.live).length;
  return (
    <>
      <Header title="Features" scope sub={<>{live} running on their own{waiting ? <> · <a href="#/inbox">{waiting} wait in Inbox</a></> : null}</>} />
      {err && <div class="banner bad" role="alert">{err}</div>}
      {products.value && !list.length && <Empty>No product with a docs repo{only.value ? " for this repository" : ""}. Add one in <a href="#/settings?pane=products">Settings → products and repos</a>; PRDs live in its docs/prds/.</Empty>}
      {!prds && list.length > 0 && <Empty>Loading PRDs…</Empty>}
      {prds && BAYS.map(([st, name, tone]) => {
        const rows = prds.filter((p) => p.status === st);
        if (!rows.length) return null;
        return (
          <Pane key={st} label={`${name} · ${rows.length}`}>
            <div class="rows">
              {rows.map((p) => (
                <a key={`${p.product}:${p.path}`} class="row" href={`#/prd?repo=${p.product}&path=${encodeURIComponent(p.path)}`}>
                  <Tag tone={tone}>{p.status}</Tag>
                  <span class="t"><b>{p.title}</b> <span class="dim mono">{p.label}</span></span>
                  <span class="w">{p.epic ? `epic ${p.epic.split("/").pop()}` : (list.find((x) => x.docs_repo === p.product)?.name ?? "")}</span>
                </a>
              ))}
            </div>
          </Pane>
        );
      })}
      {prds && list.length > 0 && prds.length === 0 && <Empty>No PRDs yet. Press n and run create-prd to write the first one.</Empty>}
    </>
  );
}
