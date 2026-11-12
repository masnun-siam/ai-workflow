import { renderToString } from "preact-render-to-string";
import { describe, expect, it } from "vitest";
import type { Session, TranscriptEvent } from "./api/types";
import { SessionView } from "./components/SessionView";
import { Transcript } from "./components/Transcript";

const base = {
  id: "s1", title: "check the comments", command: "check the comments", status: "done", session_id: "abc", skill: null, repo: "o/r",
  link: null, hooks: 0, hold: false, dismissed: false, account: "Work", tokens: null, cost: null,
} as unknown as Session;

describe("session view", () => {
  it("a finished run can be replied to", () => {
    const html = renderToString(<SessionView s={base} />);
    expect(html).toContain("Reply to continue this run");
  });
  it("a finished run without a claude session cannot", () => {
    expect(renderToString(<SessionView s={{ ...base, session_id: null } as unknown as Session} />)).not.toContain("Reply to continue");
  });
  it("shows the full prompt when the title is clipped", () => {
    const long = "x ".repeat(80).trim();
    const html = renderToString(<SessionView s={{ ...base, title: "x…", command: long }} />);
    expect(html).toContain(long);
  });
});

describe("transcript", () => {
  const ev: TranscriptEvent[] = [
    { kind: "text", text: "**done** with `x`" },
    { kind: "result", cost: 0.27, is_error: false, text: "**done** with `x`", tokens: null },
  ];
  it("does not repeat the final text in the result", () => {
    const html = renderToString(<Transcript events={ev} />);
    expect(html).toContain('class="e txt"');
    expect(html).toContain("result · $0.27</div>");
    expect(html.match(/done/g)?.length).toBe(1);
  });
  it("keeps result text that differs", () => {
    const html = renderToString(<Transcript events={[{ kind: "result", cost: null, is_error: true, text: "boom", tokens: null }]} />);
    expect(html).toContain("error · boom");
  });
});
