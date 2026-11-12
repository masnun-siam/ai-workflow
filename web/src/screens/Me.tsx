import { me, loadErrors } from "../state/data";
import { fmtCost, pct } from "../state/format";
import { ActionBar } from "../components/ActionBar";
import { Header } from "../components/Header";
import { Empty, Meter, Pane } from "../components/ui";
import { exec } from "../state/exec";
import { Btn } from "../components/ui";

export function Me() {
  const m = me.value;
  return (
    <>
      <Header title="me" />
      {loadErrors.value.me && <div class="banner bad" role="alert">{loadErrors.value.me}</div>}
      {!m ? <Empty>Loading…</Empty> : (
        <div class="grid2">
          <Pane label="day end">
            <div class="det">
              <span class="mu">{m.day_end.reconciled ? `${m.day_end.date} is reconciled.` : `${m.day_end.date} is not reconciled.`}{m.day_end.missing_days > 0 && ` ${m.day_end.missing_days} days this month are missing.`}</span>
              <div class="acts">{m.actions.filter((a) => a.key === "r").map((a) => <Btn key={a.key} k={a.key} primary onClick={() => void exec(a)}>{a.label}</Btn>)}</div>
            </div>
          </Pane>
          <Pane label="weekly review">
            <div class="det">
              <span class="mu">Week {m.weekly.week} {m.weekly.drafted ? "is drafted." : "is not drafted."}</span>
              <div class="acts">{m.actions.filter((a) => a.key === "w").map((a) => <Btn key={a.key} k={a.key} onClick={() => void exec(a)}>{a.label}</Btn>)}</div>
            </div>
          </Pane>
          <Pane label="usage">
            <div class="det">
              {m.usage.map((u) => (
                <div key={u.label}>
                  <span>{u.label} · 5h {pct(u.five_hour)} · week {pct(u.seven_day)}</span>
                  <Meter pct={u.five_hour?.pct ?? 0} label={`${u.label} five hour usage`} />
                  {u.error && <span class="c-b">{u.error}</span>}
                </div>
              ))}
              <span class="dim">{fmtCost(m.cost.month_cost)} this month · {m.cost.month_count} sessions · {fmtCost(m.cost.today_cost)} today</span>
            </div>
          </Pane>
          <ActionBar actions={m.actions.filter((a) => a.key !== "r" && a.key !== "w")} />
        </div>
      )}
    </>
  );
}
