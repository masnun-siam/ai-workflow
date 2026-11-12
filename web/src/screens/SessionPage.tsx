import { sessionOne, sessionList, loadErrors } from "../state/data";
import { route, goBack } from "../state/route";
import { Header } from "../components/Header";
import { SessionView } from "../components/SessionView";
import { Btn, Empty, Pane } from "../components/ui";

export function SessionPage() {
  const id = route.value.id!;
  const s = sessionOne.value?.id === id ? sessionOne.value : sessionList.value?.sessions.find((x) => x.id === id);
  return (
    <>
      <Header title="session"><Btn small onClick={() => goBack(s?.status === "waiting" ? "inbox" : "runs")}>← Back</Btn></Header>
      {loadErrors.value.session && <div class="banner bad" role="alert">{loadErrors.value.session}</div>}
      <Pane label={id}>{s ? <SessionView s={s} /> : <Empty>Loading…</Empty>}</Pane>
    </>
  );
}
