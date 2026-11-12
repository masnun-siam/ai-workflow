/** Old aiw repo dialogs: Create a new repo (optionally seeded with a notes-vault PRD) and Publish a
 *  local/ repo to GitHub. */
import { signal } from "@preact/signals";
import { Select } from "./Select";
import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Repo, VaultPRD } from "../api/types";
import { describeError } from "../state/actions";
import { chooseRepo, loadMany, repos } from "../state/data";
import { toast } from "../state/ui";
import { Btn, Field, useFocusTrap } from "./ui";

/** Open dialogs. `createRepo.vault` seeds the PRD from a notes folder; `onDone` gets the new repo. */
export const createRepo = signal<{ vault?: string; onDone?: (r: Repo) => void } | null>(null);
export const publishRepo = signal<string | null>(null);

function Shell({ label, onClose, children }: { label: string; onClose: () => void; children: preact.ComponentChildren }) {
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      onKeyDown={(e) => { if (e.key === "Escape") { onClose(); e.stopPropagation(); } }}>
      <div class="dlg narrow" ref={box} role="dialog" aria-modal="true" aria-label={label}>{children}</div>
    </div>
  );
}

export function CreateRepoDialog() {
  const req = createRepo.value!;
  const roots = repos.value?.scan_roots ?? [];
  const [name, setName] = useState(req.vault ? (req.vault.split("/").pop() ?? "").toLowerCase().replace(/[^a-z0-9_.-]+/g, "-") : "");
  const [parent, setParent] = useState(roots[0] ?? "");
  const [vault, setVault] = useState(req.vault ?? "");
  const [prd, setPrd] = useState<VaultPRD | null>(null);
  const [busy, setBusy] = useState(false);
  const close = () => (createRepo.value = null);
  useEffect(() => {
    setPrd(null);
    if (!vault) return;
    const t = setTimeout(() => { void http.get<VaultPRD>(`/api/vault/prd?folder=${encodeURIComponent(vault)}`).then(setPrd, () => setPrd(null)); }, 300);
    return () => clearTimeout(t);
  }, [vault]);
  const ok = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(name) && parent.startsWith("/") && (!vault || !!prd?.exists);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await http.send<{ repo: Repo }>("POST", "/api/repos/create", { name, parent, vault_folder: vault || undefined });
      toast(`Created ${r.repo.slug} at ${r.repo.path}`);
      void loadMany(["repos", "inbox"]);
      chooseRepo(r.repo.slug);
      req.onDone?.(r.repo);
      close();
    } catch (e) { toast(describeError(e), "error"); }
    setBusy(false);
  };
  return (
    <Shell label="Create a new repo" onClose={close}>
      <form class="form" onSubmit={(e) => { e.preventDefault(); if (ok && !busy) void submit(); }}>
        <h2 class="dlg-h">Create a new repo</h2>
        <span class="dim">A local git repository with a README{vault ? " and the PRD from your notes" : ""}. Publish it to GitHub when you are ready.</span>
        <Field label="Name"><input value={name} placeholder="my-app" onInput={(e) => setName((e.target as HTMLInputElement).value)} /></Field>
        <Field label="Parent folder">
          <div class="acts">
            <input class="grow mono" value={parent} placeholder="/Users/me/code" onInput={(e) => setParent((e.target as HTMLInputElement).value)} />
            {repos.value?.can_browse && <Btn small onClick={async () => { try { const r = await http.send<{ path: string | null }>("POST", "/api/repos/browse", { start: parent || undefined }); if (r.path) setParent(r.path); } catch (e) { toast(describeError(e), "error"); } }}>Choose…</Btn>}
          </div>
        </Field>
        {roots.length > 1 && <div class="chips">{roots.map((r) => <button key={r} type="button" class={`chip${parent === r ? " on" : ""}`} onClick={() => setParent(r)}>{r}</button>)}</div>}
        <Field label="PRD from the notes vault (optional)" hint="05-Work/<Project>/<Feature>, with a PRD.md">
          <input class="mono" value={vault} placeholder="05-Work/Project/Feature" onInput={(e) => setVault((e.target as HTMLInputElement).value)} />
        </Field>
        {vault && prd && (prd.exists ? <span class="c-o">PRD found: {prd.title ?? "untitled"}{prd.status ? ` · ${prd.status}` : ""}</span> : <span class="c-w">No PRD.md in that folder.</span>)}
        {name && parent && <span class="dim mono">{parent.replace(/\/$/, "")}/{name} → local/{name}</span>}
        <div class="acts"><Btn type="submit" primary disabled={!ok || busy}>{busy ? "Creating…" : "Create repo"}</Btn><Btn onClick={close}>Cancel</Btn></div>
      </form>
    </Shell>
  );
}

export function PublishDialog() {
  const slug = publishRepo.value!;
  const [owners, setOwners] = useState<string[] | null>(null);
  const [owner, setOwner] = useState("");
  const [name, setName] = useState(slug.replace(/^local\//, ""));
  const [priv, setPriv] = useState(true);
  const [busy, setBusy] = useState(false);
  const close = () => (publishRepo.value = null);
  useEffect(() => { void http.get<{ owners: string[] }>("/api/github/owners").then((r) => { setOwners(r.owners); setOwner(r.owners[0] ?? ""); }, (e) => { setOwners([]); toast(describeError(e), "error"); }); }, []);
  const submit = async () => {
    setBusy(true);
    try {
      const r = await http.send<{ repo: Repo }>("POST", "/api/repos/publish", { slug, owner, name, private: priv });
      toast(`Published ${r.repo.slug}`);
      void loadMany(["repos", "inbox", "products"]);
      chooseRepo(r.repo.slug);
      close();
    } catch (e) { toast(describeError(e), "error"); }
    setBusy(false);
  };
  return (
    <Shell label="Publish to GitHub" onClose={close}>
      <form class="form" onSubmit={(e) => { e.preventDefault(); if (owner && name && !busy) void submit(); }}>
        <h2 class="dlg-h">Publish {slug} to GitHub</h2>
        <div class="fields">
          <Field label="Owner">{owners === null ? <span class="dim">Loading…</span> : <Select label="Owner" value={owner} onChange={setOwner} options={owners.map((o) => [o, o] as [string, string])} />}</Field>
          <Field label="Name"><input value={name} onInput={(e) => setName((e.target as HTMLInputElement).value)} /></Field>
        </div>
        <label class="opt inline"><input type="checkbox" checked={priv} onChange={(e) => setPriv((e.target as HTMLInputElement).checked)} /><span>Private</span></label>
        {owner && name && <span class="dim mono">github.com/{owner}/{name}</span>}
        <div class="acts"><Btn type="submit" primary disabled={!owner || !name || busy}>{busy ? "Publishing…" : "Publish"}</Btn><Btn onClick={close}>Cancel</Btn></div>
      </form>
    </Shell>
  );
}
