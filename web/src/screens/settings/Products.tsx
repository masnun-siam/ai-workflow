import { useEffect, useState } from "preact/hooks";
import { route, setParam } from "../../state/route";
import { createRepo, publishRepo } from "../../components/Repos";
import { http } from "../../api/http";
import { loadMany, mutate, products, repos, settings } from "../../state/data";
import { askConfirm } from "../../state/ui";
import { Btn, Field, KV, Pane } from "../../components/ui";
import { saveSettings, val } from "./common";
import { toast } from "../../state/ui";
import type { RepoSettings } from "../../api/types";

const COLLAPSED_ROWS = 10;

/** A text input that shows what is saved, and snaps back to it when the save fails. */
function SaveInput({ label, saved, placeholder, width, onSave }: { label: string; saved: string; placeholder?: string; width: string; onSave: (v: string) => Promise<boolean> }) {
  const [v, setV] = useState<string | null>(null);
  return <input aria-label={label} placeholder={placeholder} value={v ?? saved} style={{ width }} onInput={(e) => setV(val(e))}
    onChange={async (e) => { await onSave(val(e).trim()); setV(null); }} />;
}

export function ProductsPane() {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const [path, setPath] = useState("");
  const [slug, setSlug] = useState("");
  const [rpath, setRpath] = useState("");
  const [problems, setProblems] = useState<Record<string, string | null>>({});
  const keys = ["products", "repos", "river"] as const;
  const pub = route.value.query.publish;
  useEffect(() => { if (pub) { publishRepo.value = pub; setParam("publish", "", true); } }, [pub]);
  const matching = (repos.value?.repos ?? []).filter((r) => !q.trim() || `${r.slug} ${r.path}`.toLowerCase().includes(q.trim().toLowerCase()));
  const shown = q || all ? matching : matching.slice(0, COLLAPSED_ROWS);
  const check = async () => {
    const r = await mutate(() => http.send<{ problems: Record<string, string | null> }>("POST", "/api/repos/check", {}), null);
    if (!r) return;
    setProblems(r.problems);
    const bad = Object.values(r.problems).filter(Boolean).length;
    toast(`${Object.keys(r.problems).length - bad} ok, ${bad} failing`, bad ? "warn" : "info");
    void loadMany([]);
  };
  return (
    <Pane label="products and repos" wide id="set-products">
      <div class="det">
        {(products.value ?? []).map((p) => (
          <div key={p.docs_repo}>
            <div class="dh"><b>{p.name}</b><span class="dim mono">{p.docs_repo}</span>
              <Btn small bad label={`Remove product ${p.name}`} onClick={async () => { if (await askConfirm(`Remove product ${p.name}? The repos stay on disk.`)) void mutate(() => http.send("DELETE", `/api/products/${p.docs_repo}`), "Removed", [...keys]); }}>Remove</Btn></div>
            {p.error && <div class="banner bad">{p.error}</div>}
            <KV rows={p.repos.map((r) => [r.name, <span>{r.repo} <span class="dim">{r.role}</span> {r.cloned ? "" : <span class="c-w">not cloned</span>}{r.conflict && <span class="c-b"> conflicts with {r.conflict}</span>}</span>])} />
          </div>
        ))}
        <form class="acts" onSubmit={async (e) => { e.preventDefault(); if (path.trim() && (await mutate(() => http.send("POST", "/api/products", { path: path.trim() }), "Product added", [...keys]))) setPath(""); }}>
          <input aria-label="Documentation repo path" placeholder="/path/to/docs-repo" value={path} onInput={(e) => setPath(val(e))} style={{ flex: 1 }} />
          <Btn type="submit" disabled={!path.trim()}>Add product</Btn>
        </form>
        <h3 class="gh">Repositories</h3>
        <form class="fields add-repo" onSubmit={async (e) => { e.preventDefault(); if (slug.trim() && rpath.trim() && (await mutate(() => http.send("POST", "/api/repos", { slug: slug.trim(), path: rpath.trim() }), "Repo added", [...keys]))) { setSlug(""); setRpath(""); } }}>
          <Field label="Slug (owner/name)"><input value={slug} placeholder="acme/web" onInput={(e) => setSlug(val(e))} /></Field>
          <Field label="Checkout path"><input value={rpath} placeholder="/path/to/checkout" onInput={(e) => setRpath(val(e))} /></Field>
          <Btn type="submit" disabled={!slug.trim() || !rpath.trim()}>Add repo</Btn>
        </form>
        <div class="acts">
          <Btn onClick={() => (createRepo.value = {})}>Create a new repo…</Btn>
          <Btn onClick={() => mutate(() => http.send("POST", "/api/repos/scan", {}), "Scan done", [...keys])}>Scan {repos.value?.scan_roots.join(", ")}</Btn>
          <Btn onClick={check}>Check repos</Btn>
        </div>
        <input type="search" aria-label="Filter repositories" placeholder="Filter repositories" value={q} onInput={(e) => setQ(val(e))} />
        <div class="tablewrap"><table class="t"><thead><tr><th>Repo</th><th>Path</th><th>Auto grind</th><th>Slack channel</th><th>Release head → base</th><th /></tr></thead><tbody>
          {shown.map((r) => {
            const rs: RepoSettings = settings.value?.repos[r.slug] ?? { auto_grind: false, slack_channel: "", reviewers: null };
            const set = (patch: Partial<RepoSettings>) => saveSettings({ repos: { [r.slug]: { ...rs, ...patch } } });
            return (
              <tr key={r.slug}>
                <td class="mono">{r.slug}{problems[r.slug] && <div class="c-b">{problems[r.slug]}</div>}</td><td class="mono brk">{r.path}</td>
                <td><input type="checkbox" aria-label={`Auto grind ${r.slug}`} checked={rs.auto_grind} onChange={(e) => void set({ auto_grind: (e.target as HTMLInputElement).checked })} /></td>
                <td><SaveInput label={`Slack channel ${r.slug}`} saved={rs.slack_channel} width="9em" onSave={(v) => set({ slack_channel: v })} /></td>
                <td style={{ whiteSpace: "nowrap" }}><SaveInput label={`Release head ${r.slug}`} saved={rs.release_head ?? ""} placeholder="staging" width="7.5em" onSave={(v) => set({ release_head: v })} /> → <SaveInput label={`Release base ${r.slug}`} saved={rs.release_base ?? ""} placeholder="master" width="7.5em" onSave={(v) => set({ release_base: v })} /></td>
                <td><div class="acts">{r.slug.startsWith("local/") && <Btn small primary label={`Publish repo ${r.slug}`} onClick={() => (publishRepo.value = r.slug)}>Publish</Btn>}<Btn small bad label={`Remove repo ${r.slug}`} onClick={async () => { if (await askConfirm(`Unregister ${r.slug}? The checkout stays on disk.`)) void mutate(() => http.send("DELETE", `/api/repos/${r.slug}`), "Removed", [...keys]); }}>Remove</Btn></div></td>
              </tr>
            );
          })}</tbody></table></div>
        {!q && matching.length > COLLAPSED_ROWS && <div class="acts"><Btn small onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${matching.length}`}</Btn></div>}
        {q && !matching.length && <span class="dim">No repository matches "{q}".</span>}
      </div>
    </Pane>
  );
}
