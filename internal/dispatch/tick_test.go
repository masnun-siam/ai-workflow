package dispatch

import (
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/sessions"
)

func prOpen(ci string) poller.PR {
	return poller.PR{N: 9, URL: "https://github.com/o/r/pull/9", State: "OPEN", CI: ci, SHA: "abc123"}
}

func openPRs() []poller.OpenPR {
	return []poller.OpenPR{{N: 9, Approved: true}}
}

func TestLaneLifecycleEndToEnd(t *testing.T) {
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 5, Title: "five", Stage: store.StQueued})

	// no snapshot yet: never launch on a guess
	e.tick()
	if len(e.sess.Launched) != 0 || e.lane(5).Stage != store.StQueued {
		t.Fatal("launched without facts")
	}

	// first fresh poll: the lane starts
	e.snaps.set("o/r", data([]poller.Issue{issue(5, []string{"refined"})}, nil))
	evs := e.tick()
	if len(e.sess.Launched) != 1 {
		t.Fatal("not launched", evKinds(evs))
	}
	sp := e.sess.Launched[0]
	if sp.Prompt.Text != "/blubird:implement-issue 5" || sp.Prompt.Step != "implement-issue" || sp.Cwd != "o/r" || !sp.Gate || sp.Kind != "lane" ||
		sp.Link == nil || sp.Link.Owner != "o" || sp.Link.Repo != "r" || sp.Link.Issue != 5 ||
		sp.Fields["dispatch"] != "aaaaaaaaaaaa" || sp.Fields["lane"] != "o/r#5" || sp.Cmd != "" {
		t.Fatalf("%+v", sp)
	}
	l := e.lane(5)
	if l.Stage != store.StImplementing || l.Handle == nil || l.Handle.Session != "S1" || len(l.Handles) != 1 || l.StartedAt == 0 {
		t.Fatalf("%+v", l)
	}
	if evKinds(evs) != "stage:queued -> implementing" {
		t.Fatal(evKinds(evs))
	}

	// the session opens a PR; CI pending: still implementing, PR tracked
	e.snaps.set("o/r", data([]poller.Issue{issue(5, []string{"refined"}, prOpen("pending"))}, openPRs()))
	e.tick()
	if l := e.lane(5); l.Stage != store.StImplementing || l.PR != 9 {
		t.Fatalf("%+v", l)
	}

	// CI green, grinding on: the grind prompt goes into the lane's session
	e.snaps.set("o/r", data([]poller.Issue{issue(5, []string{"refined"}, prOpen("success"))}, openPRs()))
	e.tick()
	if e.lane(5).Stage != store.StGrinding || len(e.sess.Sent) != 1 || e.sess.Sent[0].ID != "S1" ||
		!strings.HasPrefix(e.sess.Sent[0].Text, "/pr-grind https://github.com/o/r/pull/9 --channel C1 -- dispatch lane:") {
		t.Fatalf("%v %+v", e.lane(5).Stage, e.sess.Sent)
	}

	// the grind finishes approved: merge gate, then awaiting the human
	e.writeGrind(9, "owner: o\nrepo: r\nnumber: 9\nthread: github\ndone: 2026-01-01T00:00:00Z - approved by bob\n\n## Round 1\n- fixed: x\n")
	e.tick()
	if l := e.lane(5); l.Stage != store.StAwaitingMerge && l.Stage != store.StMergeGate {
		t.Fatal(l.Stage)
	}
	e.tick()
	if e.lane(5).Stage != store.StAwaitingMerge || len(e.note.Notes) == 0 || !strings.Contains(e.note.Notes[len(e.note.Notes)-1].Text, "PR #9 is ready to merge") {
		t.Fatalf("%v %v", e.lane(5).Stage, e.note.Notes)
	}
	if n := e.note.Notes[0]; n.Link == nil || n.Link.Issue != 5 || n.Repo != "o/r" || !strings.HasPrefix(n.Text, "o/r#5 ") {
		t.Fatalf("notify shape: %+v", n)
	}

	// the user presses merge: the merge runs once with the pinned head
	if _, err := e.svc.LaneAction("aaaaaaaaaaaa", "o/r#5", "merge", ""); err != nil {
		t.Fatal(err)
	}
	evs = e.tick()
	if len(e.merges) != 1 || e.merges[0] != (mergeCall{"o/r", 9, "abc123"}) || !strings.Contains(evKinds(evs), "merged:merged PR #9") {
		t.Fatalf("%v %v", e.merges, evKinds(evs))
	}
	if e.lane(5).ForceMerge {
		t.Fatal("force_merge must reset")
	}

	// merged on GitHub: followups with the after-merge prompt
	merged := poller.PR{N: 9, URL: "https://github.com/o/r/pull/9", State: "MERGED", CI: "success", SHA: "abc123"}
	e.snaps.set("o/r", data([]poller.Issue{issue(5, []string{"refined"}, merged)}, nil))
	e.tick()
	last := e.sess.Sent[len(e.sess.Sent)-1].Text
	if e.lane(5).Stage != store.StFollowups || !strings.HasPrefix(last, "/blubird:implement-issue") && !strings.HasPrefix(last, "/blubird:after-merge 5 (PR #9 for issue #5 is merged") {
		t.Fatalf("%v %q", e.lane(5).Stage, last)
	}

	// the issue closes and the session is idle: lane closed, session stopped, dispatch done
	e.sess.set("S1", func(r *sessions.Record) { r.Status = sessions.StDone })
	e.snaps.set("o/r", data(nil, nil, poller.Merged{N: 9, URL: "u", Closes: []int{5}, SHA: "abc123", MergedAt: e.clk.Now().Add(time.Minute).UTC().Format(time.RFC3339)}))
	evs = e.tick()
	d := e.load()
	if d.Lanes["o/r#5"].Stage != store.StClosed || d.State != store.Done || d.EndedAt == 0 || len(e.sess.Stopped) != 1 ||
		!strings.Contains(evKinds(evs), "finished:every lane is closed or skipped") {
		t.Fatalf("%v %v %v", d.Lanes["o/r#5"].Stage, d.State, evKinds(evs))
	}
	if n := e.note.Notes[len(e.note.Notes)-1]; !strings.Contains(n.Text, "every lane is closed or skipped") || n.Link == nil {
		t.Fatalf("%+v", n)
	}
	// a done dispatch with nothing queued is no longer ticked
	if evs := e.tick(); len(evs) != 0 {
		t.Fatal(evKinds(evs))
	}
}

func TestSettingsReachTheSession(t *testing.T) {
	e := newEnv(t)
	e.seed(func(s *store.Settings) {
		s.Model, s.Effort, s.Account, s.CI, s.BaseBranch = store.Ptr("opus"), store.Ptr("high"), store.Ptr("work"), "defer", store.Ptr("develop")
	}, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e.tick()
	sp := e.sess.Launched[0]
	if sp.Model != "opus" || sp.Effort != "high" || sp.Cmd != "cc-work" ||
		sp.Prompt.Text != "/blubird:implement-issue 5 (base branch develop: branch from it, open the PR into it; CI mode defer: mark the PR ready after local checks and review pass; do not wait for CI)" {
		t.Fatalf("%+v", sp)
	}
	// an unknown account label falls back to the default (empty cmd)
	e2 := newEnv(t)
	e2.seed(func(s *store.Settings) { s.Account = store.Ptr("gone") }, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e2.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e2.tick()
	if e2.sess.Launched[0].Cmd != "" {
		t.Fatal("default account expected")
	}
}

func TestStartFailureSkipsTheLane(t *testing.T) {
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e.sess.LaunchErr = errors.New("no local checkout")
	evs := e.tick()
	l := e.lane(5)
	if l.Stage != store.StSkipped || l.SkipReason != "start failed: no local checkout" || !strings.Contains(evKinds(evs), "needs_you:start failed: no local checkout") {
		t.Fatalf("%+v %s", l, evKinds(evs))
	}
	// retry-failed brings it back
	if _, keys, err := e.svc.RetryFailed("aaaaaaaaaaaa"); err != nil || len(keys) != 1 || e.lane(5).Stage != store.StQueued {
		t.Fatal(keys, err)
	}
}

func inGate(n int, extra func(*store.Lane)) *store.Lane {
	l := &store.Lane{Repo: "o/r", N: n, Stage: store.StMergeGate, PR: 9, Handle: &store.Handle{Session: "S1"}, Handles: []store.Handle{{Session: "S1"}}}
	if extra != nil {
		extra(l)
	}
	return l
}

func gateEnv(t *testing.T, st func(*store.Settings), extra func(*store.Lane)) *env {
	e := newEnv(t)
	e.seed(st, inGate(5, extra))
	e.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
	e.grind = GrindPlan{} // no grinding path: the gate is CI and review only
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil, prOpen("success"))}, openPRs()))
	return e
}

func TestMergeErrors(t *testing.T) {
	auto := func(s *store.Settings) { s.AutoMerge = true }

	t.Run("conflict goes to conflict_fix", func(t *testing.T) {
		e := gateEnv(t, auto, nil)
		e.mergeOK, e.mergeErr = false, "Pull request is not mergeable: merge CONFLICT in a.go"
		evs := e.tick()
		l := e.lane(5)
		if l.Stage != store.StConflictFix || l.MergeAt != 0 || len(e.sess.Sent) != 1 || !strings.HasPrefix(e.sess.Sent[0].Text, "PR #9 conflicts with its base") ||
			!strings.Contains(evKinds(evs), "stage:merge_gate -> conflict_fix (GitHub refused the merge: conflicts)") {
			t.Fatalf("%+v %v", l, evKinds(evs))
		}
	})
	t.Run("not up to date updates the branch", func(t *testing.T) {
		e := gateEnv(t, auto, nil)
		e.mergeOK, e.mergeErr = false, "Head branch is not up to date with the base branch"
		e.gh.Add(ghtest.Rule{Prefix: []string{"pr", "update-branch"}, Stdout: "ok"})
		evs := e.tick()
		if c := e.gh.CallsMatching("pr", "update-branch", "9", "-R", "o/r"); len(c) != 1 {
			t.Fatal(e.gh.Calls)
		}
		if e.lane(5).Stage != store.StMergeGate || !strings.Contains(evKinds(evs), "lane:PR #9 was behind its base: merged the base into it") {
			t.Fatal(evKinds(evs))
		}
	})
	t.Run("not up to date and the update fails", func(t *testing.T) {
		e := gateEnv(t, auto, nil)
		e.mergeOK, e.mergeErr = false, "branch is not up to date"
		e.gh.Add(ghtest.Rule{Prefix: []string{"pr", "update-branch"}, Code: 1, Stderr: "conflict"})
		evs := e.tick()
		if e.lane(5).Stage != store.StConflictFix || !strings.Contains(evKinds(evs), "could not update the branch from its base") {
			t.Fatal(e.lane(5).Stage, evKinds(evs))
		}
	})
	t.Run("other errors: held, then needs_you at three, same text not news", func(t *testing.T) {
		e := gateEnv(t, auto, nil)
		e.mergeOK, e.mergeErr = false, "HTTP 500 boom"
		step := func() string {
			e.clk.add(6 * time.Minute) // past the merge retry window
			// the snapshot is "fresh" independent of the clock
			return evKinds(e.tick())
		}
		first := step()
		if !strings.Contains(first, "held:merge failed: HTTP 500 boom") || e.lane(5).Held != "merge failed: HTTP 500 boom" || e.lane(5).MergeFails != 1 {
			t.Fatalf("%s %+v", first, e.lane(5))
		}
		if second := step(); strings.Contains(second, "held:") || e.lane(5).MergeFails != 2 || e.lane(5).NeedsYou != "" {
			t.Fatalf("%s", second)
		}
		third := step()
		if e.lane(5).MergeFails != 3 || e.lane(5).NeedsYou != "merge failed 3 times: HTTP 500 boom" || !strings.Contains(third, "needs_you:merge failed 3 times") {
			t.Fatalf("%s %+v", third, e.lane(5))
		}
		// a later success clears the error flags
		e.mergeOK = true
		step()
		l := e.lane(5)
		if l.MergeError != "" || l.MergeFails != 0 || l.Held != "" || l.NeedsYou != "" {
			t.Fatalf("%+v", l)
		}
	})
	t.Run("ci=ignore warns when merging with red CI", func(t *testing.T) {
		e := newEnv(t)
		e.seed(func(s *store.Settings) { s.AutoMerge, s.CI = true, "ignore" }, inGate(5, nil))
		e.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
		e.grind = GrindPlan{}
		e.snaps.set("o/r", data([]poller.Issue{issue(5, nil, prOpen("failure"))}, openPRs()))
		evs := e.tick()
		if !strings.Contains(evKinds(evs), "warning:merged with red CI") {
			t.Fatal(evKinds(evs))
		}
	})
}

func TestMergeNeverUnpinnedAndHeld(t *testing.T) {
	e := gateEnv(t, func(s *store.Settings) { s.AutoMerge = true }, func(l *store.Lane) { l.HoldMerge = true })
	e.tick()
	if len(e.merges) != 0 || e.lane(5).Stage != store.StAwaitingMerge {
		t.Fatal("hold_merge")
	}
	if _, err := e.svc.LaneAction("aaaaaaaaaaaa", "5", "unhold", ""); err != nil { // by number
		t.Fatal(err)
	}
	e.tick()
	if len(e.merges) != 1 {
		t.Fatal("merges", e.merges)
	}
}

func TestStrandAndFinish(t *testing.T) {
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 1, Stage: store.StSkipped, SkipReason: "needs refine"},
		&store.Lane{Repo: "o/r", N: 2, Stage: store.StQueued, Deps: []string{"o/r#1"}})
	e.snaps.set("o/r", data([]poller.Issue{issue(2, []string{"refined"})}, nil))
	evs := e.tick()
	if e.lane(2).NeedsYou != "blocked by skipped #1" || !strings.Contains(evKinds(evs), "needs_you:blocked by skipped #1") {
		t.Fatal(evKinds(evs))
	}
	if evs := e.tick(); strings.Contains(evKinds(evs), "needs_you") {
		t.Fatal("strand notice only once")
	}
	// the blocker is retried: queued again, strand notice cleared
	_, _ = e.svc.LaneAction("aaaaaaaaaaaa", "o/r#1", "retry", "")
	e.snaps.set("o/r", data([]poller.Issue{issue(1, nil), issue(2, []string{"refined"})}, nil))
	e.tick()
	if e.lane(2).NeedsYou != "" {
		t.Fatal("cleared:", e.lane(2).NeedsYou)
	}
	// every lane closed or skipped: finished
	e2 := newEnv(t)
	e2.seed(nil, &store.Lane{Repo: "o/r", N: 1, Stage: store.StClosed}, &store.Lane{Repo: "o/r", N: 2, Stage: store.StSkipped})
	e2.tick()
	if e2.load().State != store.Done {
		t.Fatal("not finished")
	}
}

func TestOutboxAndRestart(t *testing.T) {
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}, Handles: []store.Handle{{Session: "S1"}},
		Outbox: []store.OutboxItem{{Kind: "send", Text: "hello there"}, {Kind: "close"}}})
	e.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StRunning}
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e.tick()
	l := e.lane(5)
	if len(e.sess.Sent) != 1 || e.sess.Sent[0].Text != "hello there" || len(e.sess.Stopped) != 1 || l.Handle != nil || len(l.Outbox) != 0 {
		t.Fatalf("%+v %+v %+v", e.sess.Sent, e.sess.Stopped, l)
	}

	// a held session stores the text for its Resume
	e2 := newEnv(t)
	e2.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}, Outbox: []store.OutboxItem{{Kind: "send", Text: "later"}}})
	e2.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StRunning, Hold: true}
	e2.tick()
	if len(e2.sess.Sent) != 0 || e2.sess.recs["S1"].QueuedPrompt != "later" {
		t.Fatal("held send")
	}

	// a failing send becomes needs_you
	e3 := newEnv(t)
	e3.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}, Outbox: []store.OutboxItem{{Kind: "send", Text: "x"}}})
	e3.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StWaiting}
	e3.sess.SendErr = errs.Conflict("answer the pending question first", nil)
	evs := e3.tick()
	if e3.lane(5).NeedsYou != "send failed: answer the pending question first" || !strings.Contains(evKinds(evs), "needs_you:send failed") {
		t.Fatalf("%q", e3.lane(5).NeedsYou)
	}

	// a send with no handle starts a fresh session with that text
	e4 := newEnv(t)
	e4.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Outbox: []store.OutboxItem{{Kind: "send", Text: "CI is red on PR #3. fix"}}})
	e4.tick()
	if len(e4.sess.Launched) != 1 || e4.sess.Launched[0].Prompt.Text != "CI is red on PR #3. fix" || e4.sess.Launched[0].Prompt.Step != "" || e4.lane(5).Handle == nil {
		t.Fatalf("%+v", e4.sess.Launched)
	}

	// restart: the old session is closed and a fresh one starts with the stage's prompt
	e5 := newEnv(t)
	e5.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StGrinding, PR: 9, Restart: true, Handle: &store.Handle{Session: "S1"}})
	e5.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
	e5.snaps.set("o/r", data([]poller.Issue{issue(5, nil, prOpen("success"))}, openPRs()))
	evs = e5.tick()
	if len(e5.sess.Stopped) != 1 || len(e5.sess.Launched) != 1 || !strings.HasPrefix(e5.sess.Launched[0].Prompt.Text, "/pr-grind https://github.com/o/r/pull/9 --channel C1") ||
		e5.lane(5).Restart || !strings.Contains(evKinds(evs), "lane:restarted in grinding") {
		t.Fatalf("%+v %s", e5.sess.Launched, evKinds(evs))
	}
	// a restart in a stage without a prompt just drops the handle
	e6 := newEnv(t)
	e6.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StAwaitingMerge, Restart: true, Handle: &store.Handle{Session: "S1"}})
	e6.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
	e6.tick()
	if e6.lane(5).Handle != nil || len(e6.sess.Launched) != 0 {
		t.Fatal("no session for awaiting_merge")
	}
	// a cancelled dispatch runs the outbox (close) but moves no lane
	e7 := newEnv(t)
	d := e7.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}, Outbox: []store.OutboxItem{{Kind: "close"}}})
	d.State = store.Cancelled
	_ = store.Save(e7.h, d)
	e7.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StRunning}
	e7.tick()
	if len(e7.sess.Stopped) != 1 || e7.lane(5).Handle != nil {
		t.Fatal("cancel outbox")
	}
}

func TestCostCap(t *testing.T) {
	e := newEnv(t)
	cost := 1.5
	e.seed(func(s *store.Settings) { c := 1.0; s.MaxCost = &c }, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing,
		Handle: &store.Handle{Session: "S1"}, Handles: []store.Handle{{Session: "S1"}}})
	e.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StRunning, Cost: &cost}
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e.tick()
	d := e.load()
	if d.State != store.Paused || d.Events[len(d.Events)-1].Text != "cost cap reached: $1.50 of $1.00" || len(e.note.Notes) != 1 {
		t.Fatalf("%v %v", d.State, d.Events)
	}
	// under the cap nothing happens
	e2 := newEnv(t)
	e2.seed(func(s *store.Settings) { c := 5.0; s.MaxCost = &c }, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}, Handles: []store.Handle{{Session: "S1"}}})
	e2.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StRunning, Cost: &cost}
	e2.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e2.tick()
	if e2.load().State != store.Running {
		t.Fatal("cap")
	}
}

func TestFactsFromTruncatedSnapshot(t *testing.T) {
	trunc := func() poller.Data { d := data(nil, nil); d.IssuesTruncated = true; return d }
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e.snaps.set("o/r", trunc())
	e.gh.Add(ghtest.Rule{Prefix: []string{"issue", "view", "5"}, Stdout: "OPEN\n"})
	e.tick()
	if len(e.sess.Launched) != 0 || e.lane(5).Stage != store.StQueued {
		t.Fatal("an open issue past the cut must wait")
	}
	// gh does not answer: also waits
	e2 := newEnv(t)
	e2.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, Handle: &store.Handle{Session: "S1"}})
	e2.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
	e2.snaps.set("o/r", trunc())
	e2.tick()
	if e2.lane(5).Stage != store.StImplementing || e2.lane(5).NeedsYou != "" {
		t.Fatal("no facts, no move")
	}
	// CLOSED is cached forever: facts exist with the issue closed, and a merged PR finishes the lane
	e3 := newEnv(t)
	e3.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StFollowups, PR: 9, Handle: &store.Handle{Session: "S1"}})
	e3.sess.recs["S1"] = &sessions.Record{ID: "S1", Status: sessions.StDone}
	d := trunc()
	d.Merged = []poller.Merged{{N: 9, Closes: []int{5}, SHA: "s", URL: "u"}}
	e3.snaps.set("o/r", d)
	e3.gh.Add(ghtest.Rule{Prefix: []string{"issue", "view", "5"}, Stdout: "CLOSED\n"})
	e3.tick()
	if e3.lane(5).Stage != store.StClosed {
		t.Fatal(e3.lane(5).Stage)
	}
	if n := len(e3.gh.CallsMatching("issue", "view")); n != 1 {
		t.Fatal("one gh call:", n)
	}
	// a stale snapshot gives no facts at all
	e4 := newEnv(t)
	e4.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e4.snaps.m = map[string]poller.Snapshot{"o/r": {Repo: "o/r", Stale: true, Data: data([]poller.Issue{issue(5, nil)}, nil)}}
	e4.tick()
	if len(e4.sess.Launched) != 0 {
		t.Fatal("stale")
	}
}

func TestPROfChoice(t *testing.T) {
	old := time.Unix(1_000, 0).UTC().Format(time.RFC3339)
	d := data([]poller.Issue{issue(5, nil,
		poller.PR{N: 1, State: "MERGED", MergedAt: old}, poller.PR{N: 2, State: "OPEN", CI: "success"}, poller.PR{N: 3, State: "MERGED", MergedAt: time.Unix(5_000, 0).UTC().Format(time.RFC3339)})}, nil)
	x := &store.Lane{Repo: "o/r", N: 5, StartedAt: 2_000}
	is := &d.Issues[0]
	if p := prOf(x, d, is); p == nil || p.N != 2 {
		t.Fatalf("open first: %+v", p)
	}
	is.PRs = []poller.PR{{N: 1, State: "MERGED", MergedAt: old}, {N: 3, State: "MERGED", MergedAt: time.Unix(5_000, 0).UTC().Format(time.RFC3339)}}
	if p := prOf(x, d, is); p == nil || p.N != 3 {
		t.Fatalf("merged before the lane started belongs to an earlier run: %+v", p)
	}
	x.PR = 1
	if p := prOf(x, d, is); p == nil || p.N != 1 {
		t.Fatal("the lane's recorded PR wins")
	}
	x.PR = 77
	if prOf(x, d, is) != nil {
		t.Fatal("recorded PR absent")
	}
}

func TestGrindFileParsing(t *testing.T) {
	e := newEnv(t)
	cases := []struct {
		body  string
		state string
		due   string
	}{
		{"owner: o\nrepo: r\nnumber: 9\nthread: github\ndispatch-due: 2026-01-01T00:00:00Z\n\n## Round 1\n", "idle", "2026-01-01T00:00:00Z"},
		{"owner: o\nrepo: r\nnumber: 9\npaused: waiting\n\n## Round 1\n", "paused", ""},
		{"owner: o\nrepo: r\nnumber: 9\ndone: 2026-01-01T00:00:00Z - approved\n", "done", ""},
		{"owner: o\nrepo: r\nnumber: 9\n\n## Round 1\n- fixed: a\ndone: 2026-01-01T00:00:00Z - cap\n", "done", ""},
		{"owner: o\nrepo: r\nnumber: 9\n\n## Round 1\n- note: done: soon\n", "idle", ""},
	}
	for i, c := range cases {
		e.writeGrind(9, c.body)
		g := e.svc.grindFact("O/R", 9)
		if g == nil || g.State != c.state || g.Due != c.due {
			t.Errorf("case %d: %+v", i, g)
		}
	}
	if e.svc.grindFact("o/r", 10) != nil {
		t.Fatal("no file")
	}
}

func TestEndActions(t *testing.T) {
	e := newEnv(t)
	d := e.seed(func(s *store.Settings) { s.FeatureBranch = store.Ptr("feat/x") },
		&store.Lane{Repo: "o/r", N: 2, Stage: store.StClosed}, &store.Lane{Repo: "o/second", N: 3, Stage: store.StClosed})
	d.State = store.Done
	_ = store.Save(e.h, d)
	e.gh.Add(ghtest.Rule{Prefix: []string{"repo", "view", "o/r"}, Stdout: "main\n"})
	e.gh.Add(ghtest.Rule{Prefix: []string{"repo", "view", "o/second"}, Stdout: "\n"}) // unknown default branch: master
	e.gh.Add(ghtest.Rule{Prefix: []string{"pr", "create", "-R", "o/r"}, Stdout: "https://github.com/o/r/pull/20\n"})
	e.gh.Add(ghtest.Rule{Prefix: []string{"pr", "create", "-R", "o/second"}, Code: 1, Stderr: "boom", Once: true})
	e.gh.Add(ghtest.Rule{Prefix: []string{"pr", "create", "-R", "o/second"}, Stdout: "noise\nhttps://github.com/o/second/pull/21\n"})

	if _, err := e.svc.RequestEnd("aaaaaaaaaaaa", "open-pr"); err != nil {
		t.Fatal(err)
	}
	evs := e.tick() // a done dispatch with end requests is still ticked
	got := e.load()
	if got.FinalPRs["o/r"] != "https://github.com/o/r/pull/20" || len(got.FinalPRs) != 1 || !strings.Contains(evKinds(evs), "needs_you:open-pr failed: gh pr create on o/second failed: boom") {
		t.Fatalf("%v %s", got.FinalPRs, evKinds(evs))
	}
	args := e.gh.CallsMatching("pr", "create", "-R", "o/r")[0]
	if strings.Join(args, " ") != "pr create -R o/r --base main --head feat/x --title Epic #1: merge feat/x --body Every child of o/r#1 is merged into `feat/x`." {
		t.Fatal(args)
	}
	// retry: the repo already done is reused, only the missing PR is created
	_, _ = e.svc.RequestEnd("aaaaaaaaaaaa", "open-pr")
	evs = e.tick()
	got = e.load()
	if len(got.FinalPRs) != 2 || got.FinalPRs["o/second"] != "https://github.com/o/second/pull/21" || len(e.gh.CallsMatching("pr", "create", "-R", "o/r")) != 1 ||
		!strings.Contains(evKinds(evs), "end:opened https://github.com/o/r/pull/20, https://github.com/o/second/pull/21") {
		t.Fatalf("%v %s", got.FinalPRs, evKinds(evs))
	}
	if a := e.gh.CallsMatching("pr", "create", "-R", "o/second"); !strings.Contains(strings.Join(a[1], " "), "--base master") {
		t.Fatal("fallback base master:", a[1])
	}

	// qa and grind-pr start sessions on the epic's repo and each final PR
	_, _ = e.svc.RequestEnd("aaaaaaaaaaaa", "qa")
	_, _ = e.svc.RequestEnd("aaaaaaaaaaaa", "grind-pr")
	e.tick()
	got = e.load()
	if got.QA == nil || len(got.FinalGr) != 2 || len(e.sess.Launched) != 3 {
		t.Fatalf("%+v %d", got.QA, len(e.sess.Launched))
	}
	qa := e.sess.Launched[0]
	if !strings.HasPrefix(qa.Prompt.Text, "Final QA for epic o/r#1 on branch feat/x:") || qa.Fields["lane"] != "qa-1" || qa.Cwd != "o/r" || qa.Link.Issue != 1 {
		t.Fatalf("%+v", qa)
	}
	gr := e.sess.Launched[1]
	if gr.Prompt.Text != "/pr-grind https://github.com/o/r/pull/20 --reviewer" && !strings.HasPrefix(gr.Prompt.Text, "/pr-grind https://github.com/o/r/pull/20") ||
		strings.Contains(gr.Prompt.Text, "dispatch lane") || gr.Fields["lane"] != "grind-r" || gr.Link.Issue != 20 {
		t.Fatalf("%+v", gr)
	}
	if got.QA.Session == "" {
		t.Fatal("qa handle")
	}
}

func TestTickAllArchivesOncePerDayAndTicksBusyOnly(t *testing.T) {
	e := newEnv(t)
	now := epoch(e.clk.Now())
	old := &store.Dispatch{ID: "bbbbbbbbbbbb", State: store.Done, Settings: store.Defaults(), CreatedAt: now - 50*86400, EndedAt: now - 31*86400, Lanes: map[string]*store.Lane{}}
	if err := store.Save(e.h, old); err != nil {
		t.Fatal(err)
	}
	e.seed(nil, &store.Lane{Repo: "o/r", N: 5, Stage: store.StQueued})
	e.snaps.set("o/r", data([]poller.Issue{issue(5, nil)}, nil))
	e.svc.TickAll(e.ctx())
	if _, err := store.Load(e.h, "bbbbbbbbbbbb"); err == nil {
		t.Fatal("not archived")
	}
	if len(e.sess.Launched) != 1 {
		t.Fatal("the running dispatch was not ticked")
	}
	// archived again only after a day
	again := &store.Dispatch{ID: "cccccccccccc", State: store.Cancelled, Settings: store.Defaults(), CreatedAt: 1, EndedAt: 2, Lanes: map[string]*store.Lane{}}
	_ = store.Save(e.h, again)
	e.svc.TickAll(e.ctx())
	if _, err := store.Load(e.h, "cccccccccccc"); err != nil {
		t.Fatal("archived twice in one day")
	}
	e.clk.add(25 * time.Hour)
	e.svc.TickAll(e.ctx())
	if _, err := store.Load(e.h, "cccccccccccc"); err == nil {
		t.Fatal("not archived the next day")
	}
}
