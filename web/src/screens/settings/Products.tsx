import { useState } from "preact/hooks";
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
  return (
    <Pane label="products and repos" wide>
      <div class="det">
        {(products.value ?? []).map((p) => (
          <div key={p.docs_repo}>
            <div class="dh"><b>{p.name}</b><span class="dim mono">{p.docs_repo}</span>
              <Btn small bad onClick={async () => { if (await askConfirm(`Remove product ${p.name}? The repos stay on disk.`)) void mutate(() => http.send("DELETE", `/api/products/${p.docs_repo}`), "Removed", [...keys]); }}>Remove</Btn></div>
            {p.error && <div class="banner bad">{p.error}</div>}
            <KV rows={p.repos.map((r) => [r.name, <span>{r.repo} <span class="dim">{r.role}</span> {r.cloned ? "" : <span class="c-w">not cloned</span>}{r.conflict && <span class="c-b"> conflicts with {r.conflict}</span>}</span>])} />
          </div>
        ))}
        <form class="acts" onSubmit={(e) => { e.preventDefault(); void mutate(() => http.send("POST", "/api/products", { path }), "Product added", [...keys]).then(() => setPath("")); }}>
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
                <td class="mono">{r.slug}{problems[r.slug] && <div class="c-b">{problems[r.slug]}</div>}</td><td class="mono">{r.path}</td>
                <td><input type="checkbox" aria-label={`Auto grind ${r.slug}`} checked={rs.auto_grind} onChange={(e) => set({ auto_grind: (e.target as HTMLInputElement).checked })} /></td>
                <td><input aria-label={`Slack channel ${r.slug}`} defaultValue={rs.slack_channel} onChange={(e) => set({ slack_channel: (e.target as HTMLInputElement).value.trim() })} style={{ width: "9em" }} /></td>
                <td><input aria-label={`Release head ${r.slug}`} defaultValue={rs.release_head ?? ""} placeholder="staging" onChange={(e) => set({ release_head: (e.target as HTMLInputElement).value.trim() })} style={{ width: "6em" }} /> → <input aria-label={`Release base ${r.slug}`} defaultValue={rs.release_base ?? ""} placeholder="master" onChange={(e) => set({ release_base: (e.target as HTMLInputElement).value.trim() })} style={{ width: "6em" }} /></td>
                <td><Btn small bad onClick={async () => { if (await askConfirm(`Unregister ${r.slug}?`)) void mutate(() => http.send("DELETE", `/api/repos/${r.slug}`), "Removed", [...keys]); }}>Remove</Btn></td>
              </tr>
            );
          })}</tbody></table></div>
        <form class="fields" onSubmit={(e) => { e.preventDefault(); void mutate(() => http.send("POST", "/api/repos", { slug, path: rpath }), "Repo added", [...keys]); }}>
          <Field label="Slug (owner/name)"><input value={slug} onInput={(e) => setSlug((e.target as HTMLInputElement).value)} /></Field>
          <Field label="Checkout path"><input value={rpath} onInput={(e) => setRpath((e.target as HTMLInputElement).value)} /></Field>
        </form>
        <div class="acts">
          <Btn type="button" disabled={!slug || !rpath} onClick={() => void mutate(() => http.send("POST", "/api/repos", { slug, path: rpath }), "Repo added", [...keys])}>Add repo</Btn>
          <Btn onClick={() => void mutate(() => http.send("POST", "/api/repos/scan", {}), "Scan done", [...keys])}>Scan {repos.value?.scan_roots.join(", ")}</Btn>
          <Btn onClick={async () => { const r = await mutate(() => http.send<{ problems: Record<string, string | null> }>("POST", "/api/repos/check", {}), "Checked"); if (r) setProblems(r.problems); void loadMany([]); }}>Check repos</Btn>
        </div>
      </div>
    </Pane>
  );
}
