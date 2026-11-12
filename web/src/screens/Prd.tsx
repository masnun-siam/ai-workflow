import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { PRDFile } from "../api/types";
import { describeError } from "../state/actions";
import { route } from "../state/route";
import { Header } from "../components/Header";
import { Btn, Chips, Empty, Pane } from "../components/ui";
import { Markdown } from "../components/Markdown";

export function Prd() {
  const { repo, path } = route.value.query;
  const [f, setF] = useState<PRDFile | null>(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState<"preview" | "source">("preview");
  useEffect(() => {
    setF(null); setErr("");
    http.get<PRDFile>(`/api/prd?repo=${encodeURIComponent(repo ?? "")}&path=${encodeURIComponent(path ?? "")}`).then(setF, (e) => setErr(describeError(e)));
  }, [repo, path]);
  return (
    <>
      <Header title="prd"><Btn small onClick={() => history.back()}>← Back</Btn></Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      <Pane label={`${repo ?? ""} ${path ?? ""}`}>{f ? <><Chips label="PRD view" value={view} onPick={setView} options={[["preview", "Preview"], ["source", "Markdown"]]} />{view === "preview" ? <Markdown text={f.text} /> : <pre class="note">{f.text}</pre>}</> : !err && <Empty>Loading…</Empty>}</Pane>
    </>
  );
}
