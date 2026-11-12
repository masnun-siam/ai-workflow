package grind

import (
	"strings"
	"testing"
)

func TestEvaluate(t *testing.T) {
	base := func() RoundInput {
		return RoundInput{Last: "2026-11-12T09:00:00Z", Head: "h1", Author: "alice", Set: []string{"bob"}, Known: []string{"helper-bot"}}
	}
	r := func(id int64, login, typ, state, at, commit, body string) Review {
		return Review{ID: id, User: &GHUser{login, typ}, State: state, SubmittedAt: at, CommitID: commit, Body: body}
	}
	c := func(id, rid int64, path string, line int, body string) Comment {
		return Comment{ID: id, User: &GHUser{"bob", "User"}, Path: path, Line: &line, Body: body, ReviewID: &rid, CreatedAt: "2026-11-12T10:00:00Z"}
	}
	t.Run("changes requested with findings, fingerprints and seen", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "bob", "User", "CHANGES_REQUESTED", "2026-11-12T10:00:00Z", "h1", "")}
		in.Comments = []Comment{c(11, 1, "a.go", 3, "  Fix  THIS\nnow ")}
		in.Seen = []string{"a.go:3 fix this now "}
		res := Evaluate(in)
		if !res.Landed || res.Approved || res.Clean || len(res.Findings) != 1 {
			t.Fatalf("%+v", res)
		}
		f := res.Findings[0]
		if f.FP != "a.go:3 fix this now " || f.Seen != 1 || f.New || f.ID != 11 || f.ReviewID != 1 {
			t.Fatalf("%+v", f)
		}
	})
	t.Run("stale commit is ignored", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "bob", "User", "APPROVED", "2026-11-12T10:00:00Z", "old", "")}
		if Evaluate(in).Landed {
			t.Fatal("stale")
		}
	})
	t.Run("a review with comments beats a comment-less one on the same head", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "bob", "User", "CHANGES_REQUESTED", "2026-11-12T10:00:00Z", "h1", ""), r(2, "bob", "User", "APPROVED", "2026-11-12T10:00:05Z", "h1", "")}
		in.Comments = []Comment{c(11, 1, "a.go", 3, "x")}
		res := Evaluate(in)
		if res.Approved || len(res.Reviews) != 1 || res.Reviews[0].ID != 1 {
			t.Fatalf("%+v", res)
		}
	})
	t.Run("clean bot review needs a zero verdict and no comments", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "helper-bot", "User", "COMMENTED", "2026-11-12T10:00:00Z", "h1", "**Verdict: ok** - 0 blocker, 0 should-fix")}
		if res := Evaluate(in); !res.Landed || !res.Clean || res.Approved {
			t.Fatalf("%+v", res)
		}
		in.Reviews[0].Body = "**Verdict: no** - 1 blocker, 2 should-fix"
		if res := Evaluate(in); res.Clean || res.Blocker != 1 || res.ShouldFix != 2 {
			t.Fatalf("%+v", res)
		}
	})
	t.Run("human comment-only review is not a round", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "bob", "User", "COMMENTED", "2026-11-12T10:00:00Z", "h1", "looks ok")}
		if res := Evaluate(in); res.Landed || len(res.ThirdParty) != 0 {
			t.Fatalf("%+v", res)
		}
	})
	t.Run("third party humans from reviews, inline and issue comments; bots and the author do not count", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{r(1, "zed", "User", "COMMENTED", "2026-11-12T10:00:00Z", "h1", "hi"), r(2, "x[bot]", "Bot", "COMMENTED", "2026-11-12T10:00:00Z", "h1", ""), r(3, "alice", "User", "COMMENTED", "2026-11-12T10:00:00Z", "h1", "")}
		in.Issue = []Comment{{ID: 5, User: &GHUser{"yan", "User"}, CreatedAt: "2026-11-12T10:00:00Z"}, {ID: 6, User: &GHUser{"helper-bot", "User"}, CreatedAt: "2026-11-12T10:00:00Z"}, {ID: 7, User: &GHUser{"old", "User"}, CreatedAt: "2026-11-12T08:00:00Z"}}
		got := Evaluate(in).ThirdParty
		if strings.Join(got, ",") != "yan,zed" {
			t.Fatalf("%v", got)
		}
	})
	t.Run("copilot in the set matches its bot login", func(t *testing.T) {
		in := base()
		in.Set = []string{"copilot"}
		in.Reviews = []Review{r(1, "copilot-pull-request-reviewer[bot]", "Bot", "COMMENTED", "2026-11-12T10:00:00Z", "h1", "")}
		if res := Evaluate(in); !res.Landed || !res.Clean || len(res.ThirdParty) != 0 {
			t.Fatalf("%+v", res)
		}
	})
	t.Run("learning: the first human reviewer is paired with the first unresolved slack id, once each", func(t *testing.T) {
		in := base()
		in.Set = nil
		in.Unlogged = []string{"UAAA", "UBBB"}
		in.Reviews = []Review{r(1, "carol", "User", "CHANGES_REQUESTED", "2026-11-12T10:00:00Z", "h1", ""), r(2, "dave", "User", "APPROVED", "2026-11-12T10:05:00Z", "h1", "")}
		res := Evaluate(in)
		if len(res.Learned) != 2 || res.Learned[0] != (Pairing{"UAAA", "carol"}) || res.Learned[1] != (Pairing{"UBBB", "dave"}) || len(res.ThirdParty) != 0 {
			t.Fatalf("%+v", res)
		}
		in.Learned = []string{"UAAA=carol", "UBBB=dave"}
		in.Set = []string{"carol", "dave"}
		in.Reviews = append(in.Reviews, r(3, "erin", "User", "COMMENTED", "2026-11-12T10:06:00Z", "h1", "hm"))
		if res := Evaluate(in); len(res.Learned) != 0 || strings.Join(res.ThirdParty, ",") != "erin" {
			t.Fatalf("learning stops once every id is paired: %+v", res)
		}
	})
	t.Run("no reviewer known at all: the first human review is adopted", func(t *testing.T) {
		in := base()
		in.Set = nil
		in.Reviews = []Review{r(1, "carol", "User", "APPROVED", "2026-11-12T10:00:00Z", "h1", "")}
		res := Evaluate(in)
		if len(res.LearnedAny) != 1 || !res.Approved {
			t.Fatalf("%+v", res)
		}
	})
	t.Run("null user is tolerated", func(t *testing.T) {
		in := base()
		in.Reviews = []Review{{ID: 1, State: "COMMENTED", SubmittedAt: "2026-11-12T10:00:00Z", CommitID: "h1"}}
		Evaluate(in)
	})
}

func TestWaitExitCodes(t *testing.T) {
	t.Run("no state", func(t *testing.T) {
		e := newEnv(t)
		if code, _, _ := e.run("grind", "wait", testPR, "--once"); code != 64 {
			t.Fatal(code)
		}
	})
	t.Run("approved: exit 10, round recorded, last.json written", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.Reviews = arr(review(1, "bob", "APPROVED", "2026-11-12T10:00:00Z", testHead, ""))
		code, out, _ := e.run("grind", "wait", testPR)
		m := jsonOf(t, out)
		if code != 10 || m["approved"] != true || m["round"].(float64) != 1 || m["stop"] != "approved" {
			t.Fatalf("%d %s", code, out)
		}
		s := e.stateFile()
		if !strings.Contains(s, "## Round 1 - ") || !strings.Contains(s, "- review: 1 bob APPROVED") || !strings.Contains(s, "last-seen: 2026-11-12T10:00:00Z") {
			t.Fatalf("state:\n%s", s)
		}
		if _, out, _ := e.run("grind", "wait", testPR, "--last"); !strings.Contains(out, `"round": 1`) {
			t.Fatalf("--last: %s", out)
		}
	})
	t.Run("changes requested: exit 0 with findings carrying the comment id", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.Reviews = arr(review(1, "bob", "CHANGES_REQUESTED", "2026-11-12T10:00:00Z", testHead, ""))
		e.w.Comments = arr(inline(11, 1, "a.go", 3, "Rename this"))
		code, out, _ := e.run("grind", "wait", testPR)
		m := jsonOf(t, out)
		f := m["findings"].([]any)[0].(map[string]any)
		if code != 0 || m["approved"] != false || f["id"].(float64) != 11 || f["fp"] != "a.go:3 rename this" || f["new"] != true || f["author"] != "bob" || f["line"].(float64) != 3 {
			t.Fatalf("%d %s", code, out)
		}
		if !strings.Contains(e.stateFile(), "- finding: a.go:3 rename this") {
			t.Fatal(e.stateFile())
		}
	})
	t.Run("clean bot: 10 in deep mode, 0 in simple mode", func(t *testing.T) {
		for mode, want := range map[string]int{"deep": 10, "simple": 0} {
			e := newEnv(t)
			e.seedState()
			e.writeJSON("ui_settings.json", map[string]any{"grind_mode": mode, "reviewers": []any{}})
			e.w.Reviews = arr(botReview(1, "bot-x[bot]", "COMMENTED", "2026-11-12T10:00:00Z", testHead, "0 blocker, 0 should-fix"))
			if code, out, _ := e.run("grind", "wait", testPR); code != want || jsonOf(t, out)["clean"] != true {
				t.Fatalf("%s: %d %s", mode, code, out)
			}
		}
	})
	t.Run("stuck finding: 21, paused, thread notified", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("", "## Round 1 - x", "- finding: a.go:3 rename this", "## Round 2 - y", "- finding: a.go:3 rename this")
		e.w.Reviews = arr(review(1, "bob", "CHANGES_REQUESTED", "2026-11-12T10:00:00Z", testHead, ""))
		e.w.Comments = arr(inline(11, 1, "a.go", 3, "Rename this"))
		code, out, _ := e.run("grind", "wait", testPR)
		f := jsonOf(t, out)["findings"].([]any)[0].(map[string]any)
		if code != 21 || f["new"] != false {
			t.Fatalf("%d %s", code, out)
		}
		if !strings.Contains(e.stateFile(), "paused: 2026-11-12T10:00:00Z - stuck: finding seen 2 times") {
			t.Fatal(e.stateFile())
		}
		if len(e.slack.Sent) != 1 || !strings.HasPrefix(e.slack.Sent[0].Text, "<@UOWN000001> grind paused: stuck") || strings.Contains(e.slack.Sent[0].Text, "UBOT") || e.slack.Sent[0].ThreadTS != "1789128876.624469" {
			t.Fatalf("%+v", e.slack.Sent)
		}
		if code, _, _ := e.run("grind", "wait", testPR); code != 41 {
			t.Fatal("a paused grind exits 41")
		}
	})
	t.Run("round cap: 20", func(t *testing.T) {
		e := newEnv(t)
		var lines []string
		for i := 1; i <= 10; i++ {
			lines = append(lines, "## Round "+itoa(i)+" - x")
		}
		e.seedState(append([]string{""}, lines...)...)
		if code, _, _ := e.run("grind", "wait", testPR, "--once"); code != 20 {
			t.Fatal(code)
		}
		if !strings.Contains(e.stateFile(), "paused:") {
			t.Fatal("rail pauses")
		}
	})
	t.Run("third party human comment: 22", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.Issue = arr(`{"id":1,"user":{"login":"zed","type":"User"},"body":"hey","created_at":"2026-11-12T10:00:00Z"}`)
		code, _, errOut := e.run("grind", "wait", testPR, "--once")
		if code != 22 || !strings.Contains(errOut, "zed") {
			t.Fatalf("%d %s", code, errOut)
		}
	})
	t.Run("PR not open: 24", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.State = "MERGED"
		if code, _, _ := e.run("grind", "wait", testPR, "--once"); code != 24 {
			t.Fatal(code)
		}
	})
	t.Run("done: 40", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("done: 2026-11-12T09:30:00Z - approved")
		if code, _, _ := e.run("grind", "wait", testPR); code != 40 {
			t.Fatal(code)
		}
	})
	t.Run("--once with nothing yet: 12 and next-poll written", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		code, out, _ := e.run("grind", "wait", testPR, "--once")
		if code != 12 || jsonOf(t, out)["reason"] != "nothing yet" {
			t.Fatalf("%d %s", code, out)
		}
		if !strings.Contains(e.stateFile(), "next-poll: 2026-11-12T10:25:00Z") {
			t.Fatal(e.stateFile())
		}
	})
	t.Run("blocking wait times out: 12, then the silent reviewer rail: 23", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.writeJSON("ui_settings.json", map[string]any{"reviewers": []any{}, "grind_limits": map[string]any{"max_wait": 120, "poll_interval": 60, "max_idle_waits": 2}})
		code, out, _ := e.run("grind", "wait", testPR)
		if code != 12 || jsonOf(t, out)["reason"] != "timeout" || !strings.Contains(e.stateFile(), "idle-waits: 1") {
			t.Fatalf("%d %s\n%s", code, out, e.stateFile())
		}
		if e.w.ReviewCalls < 2 {
			t.Fatalf("polled %d times", e.w.ReviewCalls)
		}
		if code, _, _ := e.run("grind", "wait", testPR); code != 23 {
			t.Fatal(code)
		}
	})
	t.Run("a review landing during the wait ends it", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.Reviews = arr(review(1, "bob", "APPROVED", "2026-11-12T10:00:00Z", testHead, ""))
		if code, _, _ := e.run("grind", "wait", testPR, "--timeout", "5"); code != 10 {
			t.Fatal(code)
		}
	})
}

func TestCI(t *testing.T) {
	checks := func(rows ...string) string { return arr(rows...) }
	row := func(name, bucket string) string {
		return `{"name":"` + name + `","state":"X","bucket":"` + bucket + `","link":"https://github.com/acme/app/actions/runs/99/job/5"}`
	}
	cases := []struct {
		name  string
		setup func(e *env)
		code  int
		state string
	}{
		{"green", func(e *env) { e.w.Checks = checks(row("a", "pass")) }, 0, "green"},
		{"no checks is green", func(e *env) { e.w.Checks = ""; e.w.ChecksCode = 1; e.w.ChecksErr = "no checks reported" }, 0, "green"},
		{"red", func(e *env) { e.w.Checks = checks(row("a", "pass"), row("b", "fail")); e.w.ChecksCode = 1 }, 1, "red"},
		{"pending beats fail", func(e *env) { e.w.Checks = checks(row("a", "pending"), row("b", "fail")); e.w.ChecksCode = 8 }, 2, "pending"},
		{"conflict", func(e *env) { e.w.Mergeable = "CONFLICTING" }, 3, "conflict"},
		{"error", func(e *env) { e.w.Checks = ""; e.w.ChecksCode = 1; e.w.ChecksErr = "boom" }, 4, "error"},
	}
	for _, c := range cases {
		e := newEnv(t)
		c.setup(e)
		code, out, _ := e.run("grind", "ci", testPR)
		m := jsonOf(t, out)
		if code != c.code || m["state"] != c.state || m["head_sha"] != testHead || m["ci_attempted"] != false {
			t.Errorf("%s: %d %s", c.name, code, out)
		}
	}
	t.Run("failing logs and ci_attempted", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("ci-attempt: " + testHead + " - started")
		e.w.Checks = checks(row("build", "fail"))
		e.w.ChecksCode = 1
		code, out, _ := e.run("grind", "ci", testPR)
		m := jsonOf(t, out)
		f := m["failing"].([]any)[0].(map[string]any)
		if code != 1 || m["ci_attempted"] != true || f["run_id"] != "99" || !strings.Contains(f["log_excerpt"].(string), "FAILED") {
			t.Fatalf("%d %s", code, out)
		}
	})
	t.Run("--watch polls pending until it settles", func(t *testing.T) {
		e := newEnv(t)
		calls := 0
		e.w.OnChecks = func() {
			calls++
			if calls >= 3 {
				e.w.Checks, e.w.ChecksCode = checks(row("a", "pass")), 0
			}
		}
		e.w.Checks = checks(row("a", "pending"))
		e.w.ChecksCode = 8
		code, out, _ := e.run("grind", "ci", testPR, "--watch", "--timeout", "600")
		if code != 0 || jsonOf(t, out)["state"] != "green" {
			t.Fatalf("%d %s", code, out)
		}
	})
	t.Run("--watch gives up with a note", func(t *testing.T) {
		e := newEnv(t)
		e.w.Checks = checks(row("a", "pending"))
		e.w.ChecksCode = 8
		code, out, _ := e.run("grind", "ci", testPR, "--watch", "--timeout", "90")
		if code != 2 || !strings.Contains(jsonOf(t, out)["note"].(string), "wall-clock cap of 90s") {
			t.Fatalf("%d %s", code, out)
		}
	})
}

func TestRecordRetriggerDonePauseStatus(t *testing.T) {
	t.Run("record ci-attempt: 30 on a second started, outcome updates in place", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		if code, _, _ := e.run("grind", "record", testPR, "ci-attempt", "abc", "started"); code != 0 {
			t.Fatal(code)
		}
		if code, _, _ := e.run("grind", "record", testPR, "ci-attempt", "abc", "started"); code != 30 {
			t.Fatal(code)
		}
		if code, _, _ := e.run("grind", "record", testPR, "ci-attempt", "abc", "flake-rerun"); code != 0 {
			t.Fatal(code)
		}
		if code, _, _ := e.run("grind", "record", testPR, "ci-attempt", "def", "started"); code != 0 {
			t.Fatal("another head gets its own attempt")
		}
		s := e.stateFile()
		if strings.Count(s, "ci-attempt: abc ") != 1 || !strings.Contains(s, "ci-attempt: abc - flake-rerun") || !strings.Contains(s, "ci-attempt: def - started") {
			t.Fatal(s)
		}
	})
	t.Run("record lines", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("", "## Round 1 - x")
		for _, a := range [][]string{
			{"fixed", "11", "abc123", "renamed", "it"}, {"rebutted", "12", "handled", "elsewhere"}, {"note", "write", "blocked"},
			{"jev-ci-hint", "build real (0.9) - session: fixed"}, {"jev-finding-hint", "11 fix (0.8) - session: fix"},
		} {
			if code, _, _ := e.run(append([]string{"grind", "record", testPR}, a...)...); code != 0 {
				t.Fatalf("%v: %d", a, code)
			}
		}
		s := e.stateFile()
		for _, want := range []string{"- fixed: 11 abc123 renamed it", "- rebutted: 12 handled elsewhere", "- note: write blocked", "- jev-ci-hint: build real", "- jev-finding-hint: 11 fix"} {
			if !strings.Contains(s, want) {
				t.Errorf("missing %q in\n%s", want, s)
			}
		}
		if code, _, _ := e.run("grind", "record", testPR, "bogus"); code != 64 {
			t.Fatal("unknown kind")
		}
		if code, _, _ := e.run("grind", "record", testPR, "queued", "abc"); code != 64 {
			t.Fatal("--then required")
		}
	})
	t.Run("queued push blocks retrigger (32) and done (31); unqueue clears", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("", "## Round 1 - x")
		e.w.Checks = arr(`{"name":"a","bucket":"pass","link":""}`)
		if code, _, _ := e.run("grind", "record", testPR, "queued", "aaa", "bbb", "--then", "retrigger"); code != 0 {
			t.Fatal(code)
		}
		if !strings.Contains(e.stateFile(), "queued-push: aaa bbb - round 1 - then retrigger") {
			t.Fatal(e.stateFile())
		}
		if _, out, _ := e.run("grind", "status", testPR, "--json"); jsonOf(t, out)["queued_push"] != "aaa bbb - round 1 - then retrigger" {
			t.Fatal(out)
		}
		if code, _, _ := e.run("grind", "retrigger", testPR); code != 32 {
			t.Fatal(code)
		}
		if code, _, _ := e.run("grind", "done", testPR, "approved", "x"); code != 31 {
			t.Fatal(code)
		}
		e.run("grind", "record", testPR, "unqueue")
		if strings.Contains(e.stateFile(), "queued-push") {
			t.Fatal("unqueue")
		}
	})
	t.Run("retrigger: 33 when CI is not green, slack reply when green", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		e.w.Checks = arr(`{"name":"a","bucket":"fail","link":""}`)
		e.w.ChecksCode = 1
		if code, _, _ := e.run("grind", "retrigger", testPR); code != 33 {
			t.Fatal(code)
		}
		if len(e.slack.Sent) != 0 {
			t.Fatal("nothing may be posted on a red head")
		}
		e.w.Checks = arr(`{"name":"a","bucket":"pass","link":""}`)
		e.w.ChecksCode = 0
		code, out, _ := e.runEnv(map[string]string{"SETU_HEADLESS": "1"}, "grind", "retrigger", testPR)
		m := jsonOf(t, out)
		if code != 0 || m["posted"] != "slack" || len(e.slack.Sent) != 1 {
			t.Fatalf("%d %s", code, out)
		}
		s := e.slack.Sent[0]
		if s.Text != "<@UBOT000001> recheck" || s.ThreadTS != "1789128876.624469" || s.Channel != "C0AAAAAAAA" {
			t.Fatalf("%+v", s)
		}
		st := e.stateFile()
		if !strings.Contains(st, "- retrigger: ") || !strings.Contains(st, "next-poll: 2026-11-12T10:25:00Z") || !strings.Contains(st, "last-retrigger:") {
			t.Fatal(st)
		}
	})
	t.Run("retrigger on the GitHub path requests the reviews", func(t *testing.T) {
		e := newEnv(t)
		e.seedState()
		lines := strings.Replace(e.stateFile(), "thread: https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469", "thread: github", 1)
		writeFile(e.h.Path("pr-grind", "acme-app-7.md"), lines)
		e.w.Checks = arr(`{"name":"a","bucket":"pass","link":""}`)
		// no resolver answer (repo has reviewers only via reviewers-last)
		writeFile(e.h.Path("pr-grind", "acme-app-7.md"), strings.Replace(lines, "reviewers-last: UBOT000001", "reviewers-last: copilot,bob", 1))
		code, out, _ := e.run("grind", "retrigger", testPR)
		if code != 0 || jsonOf(t, out)["posted"] != "github" || strings.Join(e.w.Edits, ",") != "@copilot,bob" || len(e.slack.Sent) != 0 {
			t.Fatalf("%d %s %v", code, out, e.w.Edits)
		}
		if !strings.Contains(e.stateFile(), "reviewers-kept: no active reviewer") {
			t.Fatal(e.stateFile())
		}
	})
	t.Run("pause, done and status", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("", "## Round 1 - x")
		if code, out, _ := e.run("grind", "status", testPR, "--json"); code != 0 || jsonOf(t, out)["state"] != "running" || jsonOf(t, out)["rounds"].(float64) != 1 {
			t.Fatal(out)
		}
		if code, _, _ := e.run("grind", "pause", testPR, "CI", "red", "--no-post"); code != 0 || len(e.slack.Sent) != 0 {
			t.Fatal("--no-post")
		}
		_, out, _ := e.run("grind", "status", testPR, "--json")
		m := jsonOf(t, out)
		if m["state"] != "paused" || m["reason"] != "CI red" || m["repo"] != "acme/app" || m["pr"].(float64) != 7 || m["thread"] == nil {
			t.Fatal(out)
		}
		if code, _, _ := e.run("grind", "done", testPR, "approved (deep), 1 round: fixed x"); code != 0 {
			t.Fatal(code)
		}
		_, out, _ = e.run("grind", "status", testPR, "--json")
		m = jsonOf(t, out)
		if m["state"] != "approved" || strings.Contains(e.stateFile(), "paused:") || strings.Contains(e.stateFile(), "next-poll") {
			t.Fatal(out + e.stateFile())
		}
		if len(e.slack.Sent) != 1 || !strings.Contains(e.slack.Sent[0].Text, "ready for human merge") || strings.Contains(e.slack.Sent[0].Text, "UBOT") {
			t.Fatalf("%+v", e.slack.Sent)
		}
		_, text, _ := e.run("grind", "status", testPR)
		if !strings.Contains(text, "approved") {
			t.Fatal(text)
		}
		// done:  --no-post posts nothing
		e2 := newEnv(t)
		e2.seedState()
		e2.run("grind", "done", testPR, "merged", "--no-post")
		if len(e2.slack.Sent) != 0 {
			t.Fatal("no post")
		}
	})
	t.Run("status without state is none and never calls GitHub", func(t *testing.T) {
		e := newEnv(t)
		code, out, _ := e.run("grind", "status", testPR, "--json")
		m := jsonOf(t, out)
		if code != 0 || m["state"] != "none" || m["rounds"].(float64) != 0 || len(e.gh.Calls) != 0 {
			t.Fatalf("%d %s %v", code, out, e.gh.Calls)
		}
		e.seedState()
		e.run("grind", "status", testPR, "--json")
		if len(e.gh.Calls) != 0 {
			t.Fatal("status is offline")
		}
	})
}

func TestStart(t *testing.T) {
	reviewerSettings := func(e *env, repos map[string]any) {
		e.writeJSON("ui_settings.json", map[string]any{
			"reviewers": []any{
				map[string]string{"id": "r-00000001", "name": "A", "slack_id": "UAAAAAAAA1", "github_login": "bob"},
				map[string]string{"id": "r-00000002", "name": "B", "slack_id": "UBBBBBBBB2", "github_login": ""},
			},
			"active_reviewers": []any{"r-00000001", "r-00000002"},
			"slack_channels":   []any{map[string]string{"id": "C0AAAAAAAA", "name": "reviews"}},
			"repos":            repos,
		})
	}
	t.Run("draft and closed: 3, nothing posted, no state", func(t *testing.T) {
		for _, s := range []struct {
			state string
			draft bool
		}{{"OPEN", true}, {"CLOSED", false}, {"MERGED", false}} {
			e := newEnv(t)
			e.w.State, e.w.Draft = s.state, s.draft
			if code, _, errOut := e.run("grind", "start", testPR); code != 3 || len(e.slack.Sent) != 0 || !strings.Contains(errOut, "PR #7") {
				t.Fatalf("%v: %d %s", s, code, errOut)
			}
			if e.files().Exists(Key{"acme", "app", 7}) {
				t.Fatal("no state")
			}
		}
	})
	t.Run("slack path: posts the trigger, builds the state", func(t *testing.T) {
		e := newEnv(t)
		reviewerSettings(e, map[string]any{"acme/app": map[string]any{"slack_channel": "C0AAAAAAAA"}})
		code, out, errOut := e.run("grind", "start", testPR, "--mode", "simple")
		m := jsonOf(t, out)
		if code != 0 || m["state"] != "running" || m["mode"] != "simple" || m["thread"] != "https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469" {
			t.Fatalf("%d %s %s", code, out, errOut)
		}
		if len(e.slack.Sent) != 1 || e.slack.Sent[0].Text != "<@UAAAAAAAA1> <@UBBBBBBBB2>, review this PR\n"+testPR+"" && !strings.HasPrefix(e.slack.Sent[0].Text, "<@UAAAAAAAA1> <@UBBBBBBBB2>, review this PR") || e.slack.Sent[0].ThreadTS != "" {
			t.Fatalf("%+v", e.slack.Sent)
		}
		s := e.stateFile()
		for _, want := range []string{"owner: acme", "number: 7", "author: alice", "base: staging", "channel: C0AAAAAAAA", "reviewers: bob", "unlogged: UBBBBBBBB2", "reviewers-last: UAAAAAAAA1,UBBBBBBBB2", "reviewer: UNRESOLVED", "mode: simple", "head-at-open: " + testHead, "last-seen: 2026-11-12T10:00:00Z"} {
			if !strings.Contains(s, want) {
				t.Errorf("missing %q\n%s", want, s)
			}
		}
	})
	t.Run("an existing state is reused: human clears paused and done, a headless re-entry does not", func(t *testing.T) {
		e := newEnv(t)
		e.seedState("paused: 2026-11-12T09:30:00Z - CI red", "next-poll: 2026-11-12T11:00:00Z")
		code, out, _ := e.runEnv(map[string]string{"SETU_HEADLESS": "1"}, "grind", "start", testPR)
		if code != 0 || jsonOf(t, out)["state"] != "paused" || len(e.slack.Sent) != 0 {
			t.Fatalf("headless: %d %s", code, out)
		}
		code, out, _ = e.run("grind", "start", testPR)
		if code != 0 || jsonOf(t, out)["state"] != "running" || len(e.slack.Sent) != 0 || strings.Contains(e.stateFile(), "next-poll") {
			t.Fatalf("human: %d %s\n%s", code, out, e.stateFile())
		}
	})
	t.Run("--thread adopts a thread and posts nothing; seeds from the resolver", func(t *testing.T) {
		e := newEnv(t)
		reviewerSettings(e, map[string]any{"acme/app": map[string]any{"slack_channel": "C0AAAAAAAA"}})
		code, out, _ := e.run("grind", "start", testPR, "--thread", "https://acme.slack.com/archives/C0BBBBBBBB/p1700000000123456?thread_ts=1")
		if code != 0 || len(e.slack.Sent) != 0 || jsonOf(t, out)["thread"] != "https://acme.slack.com/archives/C0BBBBBBBB/p1700000000123456" {
			t.Fatalf("%d %s", code, out)
		}
		if s := e.stateFile(); !strings.Contains(s, "channel: C0BBBBBBBB") || !strings.Contains(s, "reviewers: bob") {
			t.Fatal(s)
		}
	})
	t.Run("a Slack thread url as the argument finds the PR in the thread", func(t *testing.T) {
		e := newEnv(t)
		e.slack.Read = "please review " + testPR
		thread := "https://acme.slack.com/archives/C0BBBBBBBB/p1700000000123456"
		code, out, _ := e.run("grind", "start", thread)
		if code != 0 || e.slack.Reads != 1 || len(e.slack.Sent) != 0 || jsonOf(t, out)["thread"] != thread {
			t.Fatalf("%d %s", code, out)
		}
	})
	t.Run("github path: the resolver logins are requested, author dropped", func(t *testing.T) {
		e := newEnv(t)
		e.writeJSON("channels.json", map[string]any{"workspace_url": "https://acme.slack.com", "bot_uid": "UBOT000001"})
		e.writeJSON("ui_settings.json", map[string]any{
			"reviewers": []any{
				map[string]string{"id": "r-00000001", "name": "A", "slack_id": "", "github_login": "bob"},
				map[string]string{"id": "r-00000002", "name": "B", "slack_id": "", "github_login": "alice"},
				map[string]string{"id": "r-00000003", "name": "C", "slack_id": "", "github_login": "copilot"},
			},
			"active_reviewers": []any{"r-00000001", "r-00000002", "r-00000003"},
			"repos":            map[string]any{"acme/app": map[string]any{}},
		})
		code, out, errOut := e.run("grind", "start", testPR)
		if code != 0 || jsonOf(t, out)["state"] != "running" {
			t.Fatalf("%d %s %s", code, out, errOut)
		}
		if strings.Join(e.w.Edits, ",") != "bob,@copilot" || len(e.slack.Sent) != 0 {
			t.Fatalf("%v", e.w.Edits)
		}
		s := e.stateFile()
		if !strings.Contains(s, "thread: github") || !strings.Contains(s, "reviewers: bob,copilot") || !strings.Contains(s, "reviewer: bob") {
			t.Fatal(s)
		}
		if _, out, _ := e.run("grind", "status", testPR, "--json"); jsonOf(t, out)["thread"] != nil {
			t.Fatal("thread: github is not a url")
		}
	})
	t.Run("--reviewer pins the grind to GitHub and skips the resolver", func(t *testing.T) {
		e := newEnv(t)
		code, _, _ := e.run("grind", "start", testPR, "--reviewer", "carol")
		if code != 0 || strings.Join(e.w.Edits, ",") != "carol" || !strings.Contains(e.stateFile(), "pinned: carol") {
			t.Fatalf("%d %v\n%s", code, e.w.Edits, e.stateFile())
		}
		if code, _, _ := newEnv(t).run("grind", "start", testPR, "--reviewer", "alice"); code != 64 {
			t.Fatal("the author cannot review")
		}
		if code, _, _ := newEnv(t).run("grind", "start", testPR, "--reviewer", "org/team"); code != 64 {
			t.Fatal("team slugs are refused")
		}
	})
	t.Run("a resolver skip is printed and stops: 3", func(t *testing.T) {
		e := newEnv(t)
		e.writeJSON("channels.json", map[string]any{"channels": map[string]string{"acme/app": "C0AAAAAAAA"}})
		code, out, _ := e.run("grind", "start", testPR)
		if code != 3 || strings.TrimSpace(out) != NoReviewer || len(e.slack.Sent) != 0 || e.files().Exists(Key{"acme", "app", 7}) {
			t.Fatalf("%d %q", code, out)
		}
	})
	t.Run("slack failure records nothing: 70; missing workspace_url: 64", func(t *testing.T) {
		e := newEnv(t)
		e.slack.Fail = true
		if code, _, _ := e.run("grind", "start", testPR); code != 70 || e.files().Exists(Key{"acme", "app", 7}) {
			t.Fatal(code)
		}
		e = newEnv(t)
		e.writeJSON("channels.json", map[string]any{"bot_uid": "UBOT000001", "dm_fallback": "D0DM000001"})
		if code, _, errOut := e.run("grind", "start", testPR); code != 64 || !strings.Contains(errOut, "workspace_url") {
			t.Fatalf("%d %s", code, errOut)
		}
	})
	t.Run("gh failure: 70; bad flags: 64", func(t *testing.T) {
		e := newEnv(t)
		e.w.State = "" // pr view answers an empty state: not OPEN
		if code, _, _ := e.run("grind", "start", testPR); code != 3 {
			t.Fatal(code)
		}
		if code, _, _ := e.run("grind", "start", testPR, "--mode", "bogus"); code != 64 {
			t.Fatal("mode")
		}
		if code, _, _ := e.run("grind", "start"); code != 64 {
			t.Fatal("missing pr")
		}
		if code, _, _ := e.run("grind", "bogus"); code != 64 {
			t.Fatal("unknown verb")
		}
	})
}

func TestThreadsDelegates(t *testing.T) {
	e := newEnv(t)
	e.w.Graphql = `{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[{"id":"PRRT_1","isResolved":false,"isOutdated":false,"path":"a.go","line":3,"comments":{"nodes":[{"databaseId":11,"url":"u","body":"b"}]}}]}}}}}`
	code, out, _ := e.run("grind", "threads", testPR, "--for-comment", "11")
	if code != 0 || !strings.Contains(out, "PRRT_1") {
		t.Fatalf("%d %s", code, out)
	}
}
