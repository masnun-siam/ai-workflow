import { sessionOne, sessionList, loadErrors } from "../state/data";
import { route, goBack } from "../state/route";
import { Header } from "../components/Header";
import { SessionView } from "../components/SessionView";
import { Btn, Empty, Pane } from "../components/ui";
import { createRepo } from "../components/Repos";

export function SessionPage() {
  const id = route.value.id!;
  const s = sessionOne.value?.id === id ? sessionOne.value : sessionList.value?.sessions.find((x) => x.id === id);
  return (
    <>
      <Header title="Session"><Btn small onClick={() => goBack(s?.status === "waiting" ? "inbox" : "activity")}>← Back</Btn></Header>
      {loadErrors.value.session && <div class="banner bad" role="alert">{loadErrors.value.session}</div>}
      {s?.no_repo && s.vault_folder && !["running", "starting", "waiting"].includes(s.status) && (
        <div class="banner">This ran in your notes ({s.vault_folder}). Ready to build it? <Btn small primary onClick={() => (createRepo.value = { vault: s.vault_folder! })}>Create repo</Btn></div>
      )}
      <Pane label={s ? `session · ${s.skill ?? "free text"}` : "session"}>{s ? <SessionView s={s} /> : <Empty>Loading…</Empty>}</Pane>
    </>
  );
}
