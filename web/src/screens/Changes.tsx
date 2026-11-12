/** Small changes (old aiw): issues filed without a PRD. Interim for phase 1: the matrix, Ready to run and
 *  "Run N as a dispatch" come back in phase 4. Filing one already works through the small-change step. */
import { currentRepo, registry } from "../state/data";
import { startReq } from "../state/ui";
import { Header } from "../components/Header";
import { Btn, Empty, Pane } from "../components/ui";

export function Changes() {
  const step = registry.value.find((s) => s.id === "small-change");
  return (
    <>
      <Header title="Small changes" scope>
        {step && <Btn primary disabled={!step.available} title={step.reason} onClick={() => (startReq.value = { step, repo: currentRepo.value ?? undefined })}>File a small change</Btn>}
      </Header>
      <Pane label="small changes">
        <Empty>A small change is one issue with no PRD: setu files it, refines it, and you run it as a dispatch.
          The list of ready and unrefined small changes is being rebuilt; for now file one here and run it from <a href="#/dispatches">Dispatches</a>.</Empty>
      </Pane>
    </>
  );
}
