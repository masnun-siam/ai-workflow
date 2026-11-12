import { useEffect, useState } from "preact/hooks";
import { route, setParam } from "../../state/route";
import { createRepo, publishRepo } from "../../components/Repos";
import { http } from "../../api/http";
import { loadMany, mutate, products, repos, settings } from "../../state/data";
import { askConfirm } from "../../state/ui";
import { Btn, Field, KV, Pane } from "../../components/ui";
import { csv, saveSettings } from "./common";
import type { RepoSettings } from "../../api/types";

export function ProductsPane() {
  const [path, setPath] = useState("");
  const [slug, setSlug] = useState("");
  const [rpath, setRpath] = useState("");
  const [problems, setProblems] = useState<Record<string, string | null>>({});
  const keys = ["products", "repos", "river"] as const;
  const pub = route.value.query.publish;
  useEffect(() => { if (pub) { publishRepo.value = pub; setParam("publish", "", true); } }, [pub]);
  return (
    <Pane label="products and repos" wide id="set-products">
      <div class="det">
        {(products.value ?? []).map((p) => (
          <div key={p.docs_repo}>
            <div class="dh"><b>{p.name}</b><span class="dim mono">{p.docs_repo}</span>
              <Btn small bad onClick={async () => { if (await askConfirm(`Remove product ${p.name}? The repos stay on disk.`)) void mutate(() => http.send("DELETE", `/api/products/${p.docs_repo}`), "Removed", [...keys]); }}>Remove</Btn></div>
            {p.error && <div class="banner bad">{p.error}</div>}
            <KV rows={p.repos.map((r) => [r.name, <span>{r.repo} <span class="dim">{r.role}</span> {r.cloned ? "" : <span class="c-w">not cloned</span>}{r.conflict && <span class="c-b"> conflicts with {r.conflict}</span>}</span>])} />
          </div>
        ))}
        <form class="acts" onSubmit={async (e) => { e.preventDefault(); if (path.trim() && (await mutate(() => http.send("POST", "/api/products", { path: path.trim() }), "Product added", [...keys]))) setPath(""); }}>
          <input aria-label="Documentation repo path" placeholder="/path/to/docs-repo" value={path} onInput={(e) => setPath((e.target as HTMLInputElement).value)} style={{ flex: 1 }} />
          <Btn type="submit" disabled={!path.trim()}>Add product</Btn>
        </form>
        <h3 class="gh">Repositories</h3>
        <div class="tablewrap"><table class="t"><thead><tr><th>Repo</th><th>Path</th><th>Auto grind</th><th>Slack channel</th><th>Release head → base</th><th /></tr></thead><tbody>
          {(repos.value?.repos ?? []).map((r) => {
            const rs: RepoSettings = settings.value?.repos[r.slug] ?? { auto_grind: false, slack_channel: "", reviewers: null };
            const set = (patch: Partial<RepoSettings>) => void saveSettings({ repos: { [r.slug]: { ...rs, ...patch } } });
            return (
              <tr key={r.slug}>
                <td class="mono">{r.slug}{problems[r.slug] && <div class="c-b">{problems[r.slug]}</div>}</td><td class="mono brk">{r.path}</td>
                <td><input type="checkbox" aria-label={`Auto grind ${r.slug}`} checked={rs.auto_grind} onChange={(e) => set({ auto_grind: (e.target as HTMLInputElement).checked })} /></td>
                <td><input aria-label={`Slack channel ${r.slug}`} defaultValue={rs.slack_channel} onChange={(e) => set({ slack_channel: (e.target as HTMLInputElement).value.trim() })} style={{ width: "9em" }} /></td>
                <td style={{ whiteSpace: "nowrap" }}><input aria-label={`Release head ${r.slug}`} defaultValue={rs.release_head ?? ""} placeholder="staging" onChange={(e) => set({ release_head: (e.target as HTMLInputElement).value.trim() })} style={{ width: "7.5em" }} /> → <input aria-label={`Release base ${r.slug}`} defaultValue={rs.release_base ?? ""} placeholder="master" onChange={(e) => set({ release_base: (e.target as HTMLInputElement).value.trim() })} style={{ width: "7.5em" }} /></td>
                <td><div class="acts">{r.slug.startsWith("local/") && <Btn small primary onClick={() => (publishRepo.value = r.slug)}>Publish</Btn>}<Btn small bad onClick={async () => { if (await askConfirm(`Unregister ${r.slug}? The checkout stays on disk.`)) void mutate(() => http.send("DELETE", `/api/repos/${r.slug}`), "Removed", [...keys]); }}>Remove</Btn></div></td>
              </tr>
            );
          })}</tbody></table></div>
        <form class="fields add-repo" onSubmit={async (e) => { e.preventDefault(); if (slug.trim() && rpath.trim() && (await mutate(() => http.send("POST", "/api/repos", { slug: slug.trim(), path: rpath.trim() }), "Repo added", [...keys]))) { setSlug(""); setRpath(""); } }}>
          <Field label="Slug (owner/name)"><input value={slug} placeholder="acme/web" onInput={(e) => setSlug((e.target as HTMLInputElement).value)} /></Field>
          <Field label="Checkout path"><input value={rpath} placeholder="/path/to/checkout" onInput={(e) => setRpath((e.target as HTMLInputElement).value)} /></Field>
          <Btn type="submit" disabled={!slug.trim() || !rpath.trim()}>Add repo</Btn>
        </form>
        <div class="acts">
          <Btn onClick={() => (createRepo.value = {})}>Create a new repo…</Btn>
          <Btn onClick={() => mutate(() => http.send("POST", "/api/repos/scan", {}), "Scan done", [...keys])}>Scan {repos.value?.scan_roots.join(", ")}</Btn>
          <Btn onClick={async () => { const r = await mutate(() => http.send<{ problems: Record<string, string | null> }>("POST", "/api/repos/check", {}), "Checked"); if (r) setProblems(r.problems); void loadMany([]); }}>Check repos</Btn>
        </div>
      </div>
    </Pane>
  );
}
