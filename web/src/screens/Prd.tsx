import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { PRDFile } from "../api/types";
import { describeError } from "../state/actions";
import { goBack, route } from "../state/route";
import { Header } from "../components/Header";
import { Btn, Chips, Empty, Pane } from "../components/ui";
import { Markdown } from "../components/Markdown";

export function Prd() {
  const { repo, path } = route.value.query;
  const [f, setF] = useState<PRDFile | null>(null);
  const [err, setErr] = useState("");
  const [view, setView] = useState<"preview" | "source">("preview");
  const missing = !repo || !path;
  useEffect(() => {
    setF(null); setErr("");
    if (missing) return;
    http.get<PRDFile>(`/api/prd?repo=${encodeURIComponent(repo ?? "")}&path=${encodeURIComponent(path ?? "")}`).then(setF, (e) => setErr(describeError(e)));
  }, [repo, path]);
  return (
    <>
      <Header title="PRD"><Btn small onClick={() => goBack("features")}>← Back</Btn></Header>
      {missing && <Empty>No PRD selected. Pick one from <a href="#/features">Features</a>.</Empty>}
      {!missing && err && <div class="banner bad" role="alert">{err}</div>}
      {!missing && <Pane plain label={`${repo} ${path}`}>{f ? <><Chips label="PRD view" value={view} onPick={setView} options={[["preview", "Preview"], ["source", "Markdown"]]} />{view === "preview" ? <Markdown text={f.text} /> : <pre class="note">{f.text}</pre>}</> : !err && <Empty>Loading…</Empty>}</Pane>}
    </>
  );
}
