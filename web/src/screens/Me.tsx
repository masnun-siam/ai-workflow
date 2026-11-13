import { me, loadErrors } from "../state/data";
import { fmtCost, pct } from "../state/format";
import { ActionBar } from "../components/ActionBar";
import { Header } from "../components/Header";
import { Empty, Meter, Pane } from "../components/ui";
import { exec } from "../state/exec";
import { Btn } from "../components/ui";
import type { Action } from "../api/types";

/** A server action is told apart by the step it starts, not by its key letter. */
const startsStep = (step: string) => (a: Action) => (a.body as { step?: string } | undefined)?.step === step;
const isDayEnd = startsStep("day-end-reconcile");
const isWeekly = startsStep("weekly-review");

export function Me() {
  const m = me.value;
  return (
    <>
      <Header title="Me" />
      {loadErrors.value.me && <div class="banner bad" role="alert">{loadErrors.value.me}</div>}
      {!m ? <Empty>Loading…</Empty> : (
        <div class="grid2">
          <Pane label="day end">
            <div class="det">
              <span class="mu">{m.day_end.reconciled ? `${m.day_end.date} is reconciled.` : `${m.day_end.date} is not reconciled.`}{m.day_end.missing_days > 0 && <span title={m.day_end.missing_dates.join(", ")}>{` ${m.day_end.missing_days} days this month are missing.`}</span>}</span>
              {m.day_end.missing_dates.length > 0 && <span class="dim mono">Missing: {m.day_end.missing_dates.join(", ")}</span>}
              <div class="acts">{m.actions.filter(isDayEnd).map((a) => <Btn key={a.key} k={a.key} primary onClick={() => exec(a)}>{a.label}</Btn>)}</div>
            </div>
          </Pane>
          <Pane label="weekly review">
            <div class="det">
              <span class="mu">Week {m.weekly.week} {m.weekly.drafted ? "is drafted." : "is not drafted."}</span>
              <div class="acts">{m.actions.filter(isWeekly).map((a) => <Btn key={a.key} k={a.key} onClick={() => exec(a)}>{a.label}</Btn>)}</div>
            </div>
          </Pane>
          <Pane label="usage">
            <div class="det">
              {m.usage.map((u) => (
                <div key={u.label}>
                  <span>{u.label} · 5h {pct(u.five_hour)} · week {pct(u.seven_day)}</span>
                  <Meter pct={u.five_hour?.pct ?? 0} label={`${u.label} five hour usage`} />
                  <Meter pct={u.seven_day?.pct ?? 0} label={`${u.label} seven day usage`} />
                  {u.error && <span class="c-b">{u.error}</span>}
                </div>
              ))}
              <span class="mu">{fmtCost(m.cost.month_cost)} this month · {m.cost.month_count} sessions · <b>{fmtCost(m.cost.today_cost)} today</b></span>
            </div>
          </Pane>
          <ActionBar actions={m.actions.filter((a) => !isDayEnd(a) && !isWeekly(a))} />
        </div>
      )}
    </>
  );
}
