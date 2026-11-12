package dispatch

import (
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/dispatch/store"
)

const now = 1_000_000.0

func ln(stage string) store.Lane {
	return store.Lane{Repo: "o/r", N: 5, Title: "t", Deps: []string{}, Stage: stage}
}

func openPR(ci string) *PRFact {
	return &PRFact{N: 9, URL: "https://github.com/o/r/pull/9", State: "OPEN", CI: ci, SHA: "abc", Approved: true}
}

func cfg(f func(*store.Settings)) store.Settings {
	s := store.Defaults()
	if f != nil {
		f(&s)
	}
	return s
}

func hasNotify(acts []Action, kind string) bool {
	for _, a := range acts {
		if a.Kind == ANotify && a.NKind == kind {
			return true
		}
	}
	return false
}

func sends(acts []Action) []Msg {
	var out []Msg
	for _, a := range acts {
		if a.Kind == ASend {
			out = append(out, a.Msg)
		}
	}
	return out
}

func TestStepRules(t *testing.T) {
	grindDone := &GrindFact{State: "done", Reason: "approved by x"}
	cases := []struct {
		name  string
		lane  func() store.Lane
		facts Facts
		set   store.Settings
		check func(t *testing.T, l store.Lane, a []Action)
	}{
		{"not active yields nothing", func() store.Lane { return ln(store.StQueued) }, Facts{PR: openPR("success")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StQueued || len(a) != 0 {
					t.Fatal(l.Stage, a)
				}
			}},
		{"paused yields nothing", func() store.Lane { l := ln(store.StImplementing); l.Paused = true; return l }, Facts{PR: openPR("success")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StImplementing || len(a) != 0 {
					t.Fatal(l.Stage, a)
				}
			}},
		{"1 limit in force records limited_until", func() store.Lane { return ln(store.StImplementing) }, Facts{LimitedUntil: now + 100}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.LimitedUntil != now+100 || len(a) != 0 {
					t.Fatal(l.LimitedUntil, a)
				}
			}},
		{"1 limit over before buffer clears quietly", func() store.Lane { l := ln(store.StImplementing); l.LimitedUntil = now - 10; return l }, Facts{}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.LimitedUntil != 0 || len(a) != 0 {
					t.Fatal(l.LimitedUntil, a)
				}
			}},
		{"1 limit over after buffer continues", func() store.Lane { l := ln(store.StImplementing); l.LimitedUntil = now - 61; return l }, Facts{}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.LimitedUntil != 0 || len(a) != 1 || a[0].Kind != AContinue {
					t.Fatal(l.LimitedUntil, a)
				}
			}},
		{"2 merged anywhere goes to followups", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: &PRFact{N: 9, State: "MERGED"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				m := sends(a)
				if l.Stage != store.StFollowups || l.PR != 9 || len(m) != 1 || m[0].Step != "after-merge" || !strings.HasPrefix(m[0].Args, "5 (PR #9 for issue #5 is merged") {
					t.Fatal(l, a)
				}
			}},
		{"3 session gone", func() store.Lane { return ln(store.StImplementing) }, Facts{Agent: "gone"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "the lane session is gone" || !hasNotify(a, "needs_you") {
					t.Fatal(l.NeedsYou, a)
				}
			}},
		{"3 gone once only", func() store.Lane { l := ln(store.StImplementing); l.NeedsYou = "the lane session is gone"; return l }, Facts{Agent: "gone"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if len(a) != 0 {
					t.Fatal(a)
				}
			}},
		{"3 gone in followups with the issue closed is fine", func() store.Lane { return ln(store.StFollowups) }, Facts{Agent: "gone", IssueOpen: false}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StClosed || l.EndedAt != now {
					t.Fatal(l)
				}
			}},
		{"4 implementing waits for green then merge_gate without grind", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: openPR("success"), Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate || l.PR != 9 {
					t.Fatal(l)
				}
			}},
		{"4 implementing with grind sends the grind prompt", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: openPR("success"), Slack: true, Channel: "C123"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				m := sends(a)
				if l.Stage != store.StGrinding || len(m) != 1 || m[0].Step != "pr-grind" ||
					m[0].Args != "https://github.com/o/r/pull/9 --channel C123" || !strings.Contains(m[0].Suffix, "dispatch lane") {
					t.Fatal(l.Stage, m)
				}
			}},
		{"4 implementing: ci pending keeps waiting", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: openPR("pending"), Agent: "working"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StImplementing || l.PR != 9 || l.NeedsYou != "" {
					t.Fatal(l)
				}
			}},
		{"4 implementing: red CI with idle agent is held once", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: openPR("failure"), Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Held != "CI is red" || !hasNotify(a, "held") {
					t.Fatal(l.Held, a)
				}
			}},
		{"4 implementing: red CI held does not renotify", func() store.Lane { l := ln(store.StImplementing); l.Held = "CI is red"; return l }, Facts{PR: openPR("failure"), Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if len(a) != 0 {
					t.Fatal(a)
				}
			}},
		{"4 implementing: defer mode ignores red CI", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: openPR("failure"), Agent: "idle"}, cfg(func(s *store.Settings) { s.CI = "defer" }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate {
					t.Fatal(l.Stage)
				}
			}},
		{"4 implementing: a draft PR is not ready", func() store.Lane { return ln(store.StImplementing) }, Facts{PR: &PRFact{N: 9, State: "OPEN", Draft: true, CI: "success"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StImplementing {
					t.Fatal(l.Stage)
				}
			}},
		{"4 implementing: idle past grace says stopped without a ready PR", func() store.Lane { l := ln(store.StImplementing); l.IdleSince = now - 181; return l }, Facts{Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "stopped without a ready PR" || !hasNotify(a, "needs_you") {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"4 implementing: idle inside grace only starts the clock", func() store.Lane { return ln(store.StImplementing) }, Facts{Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.IdleSince != now || l.NeedsYou != "" {
					t.Fatal(l)
				}
			}},
		{"4 implementing: blocked agent needs you at once", func() store.Lane { return ln(store.StImplementing) }, Facts{Agent: "blocked"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "waiting on you" {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"5 grinding done approved goes to merge_gate", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true, Grind: grindDone}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate {
					t.Fatal(l.Stage)
				}
			}},
		{"5 grinding done not approved holds once", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true, Grind: &GrindFact{State: "done", Reason: "stuck"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Held != "grind ended: stuck" || !hasNotify(a, "held") {
					t.Fatal(l.Held)
				}
			}},
		{"5 grinding paused holds", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true, Grind: &GrindFact{State: "paused"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Held != "grind paused: ?" {
					t.Fatal(l.Held)
				}
			}},
		{"5 grinding switched off mid-run", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true}, cfg(func(s *store.Settings) { s.Grind = "off" }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate {
					t.Fatal(l.Stage)
				}
			}},
		{"5 grinding due token nudges an idle agent once", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true, Agent: "idle", Grind: &GrindFact{State: "idle", Due: "T1"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Nudged != "T1" || len(sends(a)) != 1 {
					t.Fatal(l.Nudged, a)
				}
			}},
		{"5 grinding same token does not renudge", func() store.Lane { l := ln(store.StGrinding); l.Nudged = "T1"; return l }, Facts{PR: openPR("success"), Slack: true, Agent: "idle", Grind: &GrindFact{State: "idle", Due: "T1"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if len(a) != 0 {
					t.Fatal(a)
				}
			}},
		{"5 grinding blocked agent: the grind waits on you", func() store.Lane { return ln(store.StGrinding) }, Facts{PR: openPR("success"), Slack: true, Agent: "blocked", Grind: &GrindFact{State: "idle"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "the grind waits on you" {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"5 grinding unblocked clears needs_you", func() store.Lane { l := ln(store.StGrinding); l.NeedsYou = "the grind waits on you"; return l }, Facts{PR: openPR("success"), Slack: true, Agent: "working", Grind: &GrindFact{State: "idle"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "" {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"6 gate: conflict goes to conflict_fix", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "success", Conflict: true}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				m := sends(a)
				if l.Stage != store.StConflictFix || len(m) != 1 || !strings.Contains(m[0].Plain, "PR #9 conflicts with its base") {
					t.Fatal(l.Stage, m)
				}
			}},
		{"6 gate: red CI in wait mode is held", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("failure")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Held != "CI is red" {
					t.Fatal(l.Held)
				}
			}},
		{"6 gate: defer fixes a red head once per sha", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("failure")}, cfg(func(s *store.Settings) { s.CI = "defer" }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.CIFixed != "abc" || len(sends(a)) != 1 || l.Gate != "waiting for green CI (defer)" {
					t.Fatal(l.CIFixed, l.Gate, a)
				}
			}},
		{"6 gate: CI none inside the grace", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("none")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "CI not registered yet" || l.NoneSince != now || l.NoneSHA != "abc" {
					t.Fatal(l)
				}
			}},
		{"6 gate: CI none after the grace merges a CI-less repo", func() store.Lane {
			l := ln(store.StMergeGate)
			l.NoneSHA, l.NoneSince = "abc", now-301
			return l
		}, Facts{PR: openPR("none")}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "" || len(a) != 1 || a[0].Kind != AMerge || a[0].SHA != "abc" {
					t.Fatal(l.Gate, a)
				}
			}},
		{"6 gate: a new sha restarts the none grace", func() store.Lane {
			l := ln(store.StMergeGate)
			l.NoneSHA, l.NoneSince = "old", now-1000
			return l
		}, Facts{PR: openPR("none")}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "CI not registered yet" || l.NoneSHA != "abc" || l.NoneSince != now {
					t.Fatal(l)
				}
			}},
		{"6 gate: wait mode needs green", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("pending")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "CI is not green" {
					t.Fatal(l.Gate)
				}
			}},
		{"6 gate: blockers in order", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "success", ThreadsOpen: 2, ChangesRequested: true}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "changes requested" {
					t.Fatal(l.Gate)
				}
			}},
		{"6 gate: no approval unless solo", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "success", SHA: "x"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "no approving review" {
					t.Fatal(l.Gate)
				}
			}},
		{"6 gate: solo repo needs no approval", func() store.Lane { return ln(store.StMergeGate) }, Facts{Solo: true, PR: &PRFact{N: 9, State: "OPEN", CI: "success", SHA: "x"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "" || l.Stage != store.StAwaitingMerge {
					t.Fatal(l.Gate, l.Stage)
				}
			}},
		{"6 gate: skip_approval drops only approval", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "success", SHA: "x"}}, cfg(func(s *store.Settings) { s.SkipApproval = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "" {
					t.Fatal(l.Gate)
				}
			}},
		{"6 gate: grind must be done and approved", func() store.Lane { return ln(store.StMergeGate) }, Facts{Slack: true, PR: openPR("success"), Grind: &GrindFact{State: "idle"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "grind is not done" {
					t.Fatal(l.Gate)
				}
			}},
		{"6 gate: awaiting_merge falls back to merge_gate on a gate", func() store.Lane { return ln(store.StAwaitingMerge) }, Facts{PR: openPR("pending")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate || l.Gate != "CI is not green" {
					t.Fatal(l.Stage, l.Gate)
				}
			}},
		{"6 clear gate without auto-merge awaits the human", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("success")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StAwaitingMerge || !hasNotify(a, "awaiting_merge") {
					t.Fatal(l.Stage, a)
				}
			}},
		{"6 auto-merge pins the head", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "success", Approved: true}}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Gate != "head commit unknown" || len(a) != 0 {
					t.Fatal(l.Gate, a)
				}
			}},
		{"6 auto-merge merges and records merge_at", func() store.Lane { return ln(store.StMergeGate) }, Facts{PR: openPR("success")}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.MergeAt != now || len(a) != 1 || a[0].Kind != AMerge || a[0].PR != 9 {
					t.Fatal(l.MergeAt, a)
				}
			}},
		{"6 auto-merge does not retry inside 300 s", func() store.Lane { l := ln(store.StMergeGate); l.MergeAt = now - 100; return l }, Facts{PR: openPR("success")}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if len(a) != 0 {
					t.Fatal(a)
				}
			}},
		{"6 hold_merge stops auto-merge", func() store.Lane { l := ln(store.StMergeGate); l.HoldMerge = true; return l }, Facts{PR: openPR("success")}, cfg(func(s *store.Settings) { s.AutoMerge = true }),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StAwaitingMerge {
					t.Fatal(l.Stage)
				}
			}},
		{"6 force_merge skips the gate", func() store.Lane { l := ln(store.StMergeGate); l.ForceMerge = true; return l }, Facts{PR: &PRFact{N: 9, State: "OPEN", CI: "pending", SHA: "z"}}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if len(a) != 1 || a[0].Kind != AMerge {
					t.Fatal(a)
				}
			}},
		{"6 a stale merge error drops when the gate holds", func() store.Lane {
			l := ln(store.StMergeGate)
			l.MergeError, l.MergeFails, l.Held, l.NeedsYou = "boom", 3, "merge failed: boom", "merge failed 3 times: boom"
			return l
		}, Facts{PR: openPR("pending")}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.MergeError != "" || l.MergeFails != 0 || l.Held != "" || l.NeedsYou != "" || l.Gate != "CI is not green" {
					t.Fatal(l)
				}
			}},
		{"7 conflict_fix back to merge_gate when resolved and agent idle", func() store.Lane { return ln(store.StConflictFix) }, Facts{PR: openPR("success"), Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StMergeGate {
					t.Fatal(l.Stage)
				}
			}},
		{"7 conflict_fix still conflicting and blocked", func() store.Lane { return ln(store.StConflictFix) }, Facts{PR: &PRFact{N: 9, State: "OPEN", Conflict: true}, Agent: "blocked"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "waiting on you" {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"7 conflict_fix resolved but agent working just waits", func() store.Lane { return ln(store.StConflictFix) }, Facts{PR: openPR("success"), Agent: "working"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StConflictFix {
					t.Fatal(l.Stage)
				}
			}},
		{"8 followups closes when the issue closed and agent idle", func() store.Lane { return ln(store.StFollowups) }, Facts{IssueOpen: false, Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.Stage != store.StClosed || len(a) != 1 || a[0].Kind != AClose {
					t.Fatal(l.Stage, a)
				}
			}},
		{"8 followups with the issue still open and idle past grace", func() store.Lane { l := ln(store.StFollowups); l.IdleSince = now - 200; return l }, Facts{IssueOpen: true, Agent: "idle"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.NeedsYou != "followups stopped with the issue still open" {
					t.Fatal(l.NeedsYou)
				}
			}},
		{"8 idle_since clears when the agent is working", func() store.Lane { l := ln(store.StFollowups); l.IdleSince = now - 5; return l }, Facts{IssueOpen: true, Agent: "working"}, cfg(nil),
			func(t *testing.T, l store.Lane, a []Action) {
				if l.IdleSince != 0 {
					t.Fatal(l.IdleSince)
				}
			}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			before := c.lane()
			l, a := Step(before, c.facts, c.set, now)
			c.check(t, l, a)
		})
	}
}

func TestStepIsPure(t *testing.T) {
	l := ln(store.StMergeGate)
	l.Outbox = []store.OutboxItem{{Kind: "close"}}
	orig := l
	next, _ := Step(l, Facts{PR: openPR("success")}, cfg(nil), now)
	if l.Stage != orig.Stage || next.Stage != store.StAwaitingMerge {
		t.Fatal("Step changed its input", l.Stage, next.Stage)
	}
}

func TestPrompts(t *testing.T) {
	m := implementMsg(7, "feat", 12, "defer")
	if m.Step != "implement-issue" || m.Args != "7 (PR #12 is already open for it: continue that PR on its branch, don't start over; base branch feat: branch from it, open the PR into it; CI mode defer: mark the PR ready after local checks and review pass; do not wait for CI)" {
		t.Fatal(m.Args)
	}
	if got := implementMsg(7, "", 0, "wait").Args; got != "7" {
		t.Fatal(got)
	}
	g := grindMsg("U", "", true, "ignore", "alice")
	if g.Args != "U --reviewer alice" || g.Suffix != laneGrind+" "+skipCIReply {
		t.Fatal(g)
	}
	if grindMsg("U", "C1", false, "wait", "alice").Args != "U --channel C1" {
		t.Fatal("channel wins")
	}
	if grindMsg("U", "bad id", false, "wait", "alice").Args != "U" {
		t.Fatal("bad channel gives no flag, and no reviewer when a channel was given")
	}
	if c := conflictMsg(3, "main").Plain; c != "PR #3 conflicts with main. Merge origin/main into the branch, resolve the conflicts, re-run the checks, push and wait for CI to be green. Don't mark anything else or merge." {
		t.Fatal(c)
	}
	if q := qaMsg("o/r#1", "feat").Plain; !strings.HasPrefix(q, "Final QA for epic o/r#1 on branch feat: run /blubird:verifier-locally") || !strings.Contains(q, "/blubird:create-tasks") {
		t.Fatal(q)
	}
	l := ln(store.StGrinding)
	if m, ok := stageMsg(&l, cfg(nil), "https://x/pull/1"); !ok || m.Step != "pr-grind" {
		t.Fatal(m)
	}
	l.Stage = store.StAwaitingMerge
	if _, ok := stageMsg(&l, cfg(nil), ""); ok {
		t.Fatal("awaiting_merge needs no session")
	}
	if LaneBase(&store.Lane{Base: "b"}, cfg(func(s *store.Settings) { s.BaseBranch = store.Ptr("bb") })) != "bb" ||
		LaneBase(&store.Lane{Base: "b"}, cfg(func(s *store.Settings) { s.BaseBranch = store.Ptr("bb"); s.FeatureBranch = store.Ptr("fb") })) != "fb" ||
		LaneBase(&store.Lane{Base: "b"}, cfg(nil)) != "b" {
		t.Fatal("lane base")
	}
}

func dsp(lanes ...*store.Lane) *store.Dispatch {
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", State: store.Running, Settings: store.Defaults(), Lanes: map[string]*store.Lane{}}
	for _, l := range lanes {
		d.Lanes[l.Key()] = l
	}
	return d
}

func lane(n int, stage string, deps ...string) *store.Lane {
	return &store.Lane{Repo: "o/r", N: n, Stage: stage, Deps: append([]string{}, deps...)}
}

func TestStartable(t *testing.T) {
	facts := func(keys ...string) map[string]Facts {
		m := map[string]Facts{}
		for _, k := range keys {
			m[k] = Facts{}
		}
		return m
	}
	d := dsp(lane(1, store.StClosed), lane(2, store.StQueued, "o/r#1"), lane(3, store.StQueued, "o/r#2"), lane(4, store.StQueued), lane(5, store.StQueued))
	if got := Startable(d, facts("o/r#2", "o/r#3", "o/r#4", "o/r#5"), now); strings.Join(got, ",") != "o/r#2,o/r#4" {
		t.Fatal("cap 2, dep order, by number:", got)
	}
	d.Lanes["o/r#4"].Stage = store.StImplementing
	if got := Startable(d, facts("o/r#2", "o/r#5"), now); strings.Join(got, ",") != "o/r#2" {
		t.Fatal("one slot used:", got)
	}
	if got := Startable(d, facts("o/r#5"), now); strings.Join(got, ",") != "o/r#5" {
		t.Fatal("no facts, no launch:", got)
	}
	d.State = store.Paused
	if len(Startable(d, facts("o/r#2"), now)) != 0 {
		t.Fatal("paused dispatch starts nothing")
	}
	d.State = store.Running
	d.Lanes["o/r#4"].LimitedUntil = now + 5
	if len(Startable(d, facts("o/r#2"), now)) != 0 {
		t.Fatal("a limited lane blocks all starts")
	}
	d.Lanes["o/r#4"].LimitedUntil = 0
	d.Lanes["o/r#2"].Paused = true
	if len(Startable(d, facts("o/r#2"), now)) != 0 {
		t.Fatal("paused lane never starts")
	}
	d.Lanes["o/r#2"].Paused = false
	if len(Startable(d, map[string]Facts{"o/r#2": {BlockersOpen: []string{"o/r#99"}}}, now)) != 0 {
		t.Fatal("an open blocker outside the dispatch holds the lane")
	}
	if got := Startable(d, map[string]Facts{"o/r#2": {BlockersOpen: []string{"o/r#4"}}}, now); len(got) != 1 {
		t.Fatal("an open blocker inside the dispatch is the dep graph's business:", got)
	}
	// a dep outside the dispatch counts as closed
	d2 := dsp(lane(2, store.StQueued, "x/y#1"))
	if len(Startable(d2, facts("o/r#2"), now)) != 1 {
		t.Fatal("outside dep counts as closed")
	}
}

func TestStrandedAndDiagnose(t *testing.T) {
	d := dsp(lane(1, store.StSkipped), lane(2, store.StQueued, "o/r#1"), lane(3, store.StQueued, "o/r#2"),
		lane(4, store.StQueued, "o/r#5"), lane(5, store.StQueued, "o/r#4"), lane(6, store.StImplementing), lane(7, store.StQueued, "o/r#6"),
		&store.Lane{Repo: "x/y", N: 8, Stage: store.StQueued, Deps: []string{"x/y#1"}})
	d.Lanes["o/r#1"].N = 1
	st := Stranded(d)
	want := map[string]string{"o/r#2": "blocked by skipped #1", "o/r#3": "blocked by skipped #1", "o/r#4": "dependency cycle", "o/r#5": "dependency cycle"}
	if len(st) != len(want) {
		t.Fatal(st)
	}
	for k, v := range want {
		if st[k] != v {
			t.Fatal(k, st[k], v)
		}
	}
	d.Lanes["o/r#7"].Paused = true
	d.Lanes["o/r#6"].NeedsYou = "waiting on you"
	d.Lanes["o/r#3"].NeedsYou = "blocked by skipped #1" // already a strand reason: listed once
	probs := Diagnose(d, map[string]SnapInfo{"o/r": {Known: true, Stale: true, Error: "rate limited"}, "x/y": {Known: true, Stale: true}})
	var lines []string
	for _, p := range probs {
		lines = append(lines, p.Lane+"|"+p.Problem)
	}
	got := strings.Join(lines, "\n")
	for _, w := range []string{"o/r#2|blocked by skipped #1", "|stale poll snapshot for o/r: rate limited", "|stale poll snapshot for x/y: not fetched yet", "o/r#6|needs you: waiting on you"} {
		if !strings.Contains(got, w) {
			t.Fatalf("missing %q in\n%s", w, got)
		}
	}
	if strings.Count(got, "o/r#3|") != 1 {
		t.Fatal("a stranded lane's needs_you is listed once:", got)
	}
	d.State = store.Done
	if len(Diagnose(d, nil)) != 0 {
		t.Fatal("done has no problems")
	}
}

func TestSyncLanesAndPlan(t *testing.T) {
	d := dsp()
	kids := []Child{{Repo: "o/r", N: 1, Title: "a", Refined: true, Deps: []string{}}, {Repo: "o/r", N: 2, Title: "b", Refined: false, Deps: []string{"o/r#1"}}}
	if added := SyncLanes(d, kids, now); len(added) != 2 {
		t.Fatal(added)
	}
	if d.Lanes["o/r#1"].Stage != store.StQueued || d.Lanes["o/r#2"].Stage != store.StSkipped || d.Lanes["o/r#2"].SkipReason != "needs refine" {
		t.Fatal(d.Lanes["o/r#2"])
	}
	// a re-read lists fewer blockers: the union is kept; refining un-skips
	kids[1].Refined, kids[1].Deps = true, []string{}
	if added := SyncLanes(d, kids, now); len(added) != 0 || d.Lanes["o/r#2"].Stage != store.StQueued || len(d.Lanes["o/r#2"].Deps) != 1 {
		t.Fatal(added, d.Lanes["o/r#2"])
	}
	// done + new work => paused
	d.State, d.EndedAt = store.Done, now
	SyncLanes(d, []Child{{Repo: "o/r", N: 3, Refined: true}}, now)
	if d.State != store.Paused || d.EndedAt != 0 || d.Events[len(d.Events)-1].Text != "new issues joined: refine them, then resume" {
		t.Fatal(d.State, d.Events)
	}

	p := MakePlan([]Child{
		{Repo: "o/r", N: 1, Refined: true}, {Repo: "o/r", N: 2, Refined: true, Deps: []string{"o/r#1"}},
		{Repo: "o/r", N: 3, Refined: true, Deps: []string{"o/r#1"}}, {Repo: "o/r", N: 4, Refined: false},
		{Repo: "o/r", N: 5, Refined: true, Deps: []string{"o/r#6"}}, {Repo: "o/r", N: 6, Refined: true, Deps: []string{"o/r#5"}},
		{Repo: "o/r", N: 7, Refined: true, Deps: []string{"x/y#1"}},
	})
	if len(p.Waves) != 2 || strings.Join(p.Waves[0], ",") != "o/r#1,o/r#7" || strings.Join(p.Waves[1], ",") != "o/r#2,o/r#3" {
		t.Fatal(p.Waves)
	}
	if strings.Join(p.Warnings, "|") != "o/r#4: needs refine|dependency cycle or blocked by an unrefined issue: o/r#5, o/r#6" {
		t.Fatal(p.Warnings)
	}
}

func TestLaneActions(t *testing.T) {
	d := dsp(lane(1, store.StImplementing), lane(2, store.StSkipped), lane(3, store.StMergeGate))
	d.Lanes["o/r#1"].Handle = &store.Handle{Session: "s1"}
	d.Lanes["o/r#3"].Handle = &store.Handle{Session: "s3"}
	d.Lanes["o/r#3"].PR = 9
	act := func(k, a, text string) error { return ApplyLaneAction(d, k, a, text, now) }
	if act("o/r#1", "pause", "") != nil || !d.Lanes["o/r#1"].Paused {
		t.Fatal("pause")
	}
	if act("o/r#1", "resume", "") != nil || d.Lanes["o/r#1"].Paused || d.Lanes["o/r#1"].Restart {
		t.Fatal("plain resume does not restart")
	}
	d.Lanes["o/r#1"].PausedBy = "dispatch"
	d.Lanes["o/r#1"].Paused = true
	_ = act("o/r#1", "resume", "")
	if !d.Lanes["o/r#1"].Restart || d.Lanes["o/r#1"].PausedBy != "" {
		t.Fatal("resume after pause-now restarts")
	}
	// retry: implementing without a PR -> close + queued
	_ = act("o/r#1", "retry", "")
	l1 := d.Lanes["o/r#1"]
	if l1.Stage != store.StQueued || l1.Handle != nil || len(l1.Outbox) != 1 || l1.Outbox[0].Kind != "close" {
		t.Fatal(l1)
	}
	// retry a skipped lane
	_ = act("o/r#2", "retry", "")
	if d.Lanes["o/r#2"].Stage != store.StQueued || d.Lanes["o/r#2"].SkipReason != "" {
		t.Fatal(d.Lanes["o/r#2"])
	}
	// retry red CI with a handle: send the ci-fix prompt
	d.Lanes["o/r#3"].Held = "CI is red"
	_ = act("o/r#3", "retry", "")
	if o := d.Lanes["o/r#3"].Outbox; len(o) != 1 || o[0].Kind != "send" || !strings.HasPrefix(o[0].Text, "CI is red on PR #9") || d.Lanes["o/r#3"].Held != "" {
		t.Fatal(d.Lanes["o/r#3"])
	}
	// retry an active lane otherwise restarts it
	d.Lanes["o/r#3"].Outbox = nil
	_ = act("o/r#3", "retry", "")
	if !d.Lanes["o/r#3"].Restart {
		t.Fatal("restart")
	}
	_ = act("o/r#3", "merge", "")
	_ = act("o/r#3", "hold", "")
	if !d.Lanes["o/r#3"].ForceMerge || !d.Lanes["o/r#3"].HoldMerge {
		t.Fatal("merge/hold")
	}
	_ = act("o/r#3", "unhold", "")
	if d.Lanes["o/r#3"].HoldMerge {
		t.Fatal("unhold")
	}
	// skip closes the active session
	_ = act("o/r#3", "skip", "")
	l3 := d.Lanes["o/r#3"]
	if l3.Stage != store.StSkipped || l3.SkipReason != "skipped by you" || len(l3.Outbox) != 1 {
		t.Fatal(l3)
	}
	// send needs a handle and sane text
	if act("o/r#2", "send", "hi") == nil {
		t.Fatal("send without a session")
	}
	d.Lanes["o/r#2"].Handle = &store.Handle{Session: "s"}
	if act("o/r#2", "send", "  ") == nil || act("o/r#2", "send", strings.Repeat("x", 2001)) == nil {
		t.Fatal("send text bounds")
	}
	if act("o/r#2", "send", " hi ") != nil || d.Lanes["o/r#2"].Outbox[0].Text != "hi" {
		t.Fatal("send")
	}
	if act("o/r#2", "dance", "") == nil || act("nope#1", "pause", "") == nil {
		t.Fatal("unknown action / lane")
	}
	if len(d.Events) == 0 || d.Events[0].Kind != "lane" {
		t.Fatal("every action logs an event")
	}
}

func TestRetryFailedAndStates(t *testing.T) {
	d := dsp(lane(1, store.StSkipped), lane(2, store.StSkipped), lane(3, store.StImplementing), lane(4, store.StClosed), lane(5, store.StSkipped), lane(6, store.StAwaitingMerge))
	d.Lanes["o/r#1"].SkipReason = "start failed: boom"
	d.Lanes["o/r#2"].SkipReason = "skipped by you"
	d.Lanes["o/r#3"].NeedsYou = "waiting on you"
	d.Lanes["o/r#5"].SkipReason = "needs refine"
	d.Lanes["o/r#6"].Held = "CI is red"
	got := RetryFailed(d, now)
	if strings.Join(got, ",") != "o/r#1,o/r#3,o/r#6" {
		t.Fatal(got)
	}
	if d.Lanes["o/r#2"].Stage != store.StSkipped || d.Lanes["o/r#5"].SkipReason != "needs refine" {
		t.Fatal("user-skipped and needs-refine lanes are left alone")
	}

	// set_state
	d = dsp(lane(1, store.StImplementing), lane(2, store.StImplementing), lane(3, store.StQueued))
	d.Lanes["o/r#1"].Handle = &store.Handle{Session: "a"}
	d.Lanes["o/r#2"].Handle = &store.Handle{Session: "b"}
	d.Lanes["o/r#2"].Paused = true // the user's
	d.Lanes["o/r#1"].NeedsYou, d.Lanes["o/r#1"].LimitedUntil = "x", 5
	if err := SetState(d, store.Paused, true, now); err != nil {
		t.Fatal(err)
	}
	l1, l2 := d.Lanes["o/r#1"], d.Lanes["o/r#2"]
	if d.State != store.Paused || !l1.Paused || l1.PausedBy != "dispatch" || l1.NeedsYou != "" || l1.LimitedUntil != 0 || len(l1.Outbox) != 1 {
		t.Fatal(l1)
	}
	if l2.PausedBy != "" || len(l2.Outbox) != 0 {
		t.Fatal("a user-paused lane is not touched")
	}
	if e := d.Events[len(d.Events)-1]; e.Text != "dispatch paused now: 1 issue stopped" {
		t.Fatal(e.Text)
	}
	_ = SetState(d, store.Running, false, now)
	if l1.Paused || !l1.Restart || !l2.Paused || d.Events[len(d.Events)-1].Text != "dispatch running: 1 issue restarted" {
		t.Fatal(l1, l2, d.Events[len(d.Events)-1])
	}
	_ = SetState(d, store.Cancelled, false, now)
	if d.State != store.Cancelled || d.EndedAt != now || len(l1.Outbox) != 1 || len(l2.Outbox) != 1 {
		t.Fatal("cancel closes every active session, paused ones too", l1.Outbox, l2.Outbox)
	}
	if SetState(d, "bogus", false, now) == nil {
		t.Fatal("bad state")
	}
}

func TestRequestEnd(t *testing.T) {
	epic := "o/r#1"
	d := dsp(lane(2, store.StClosed))
	d.Epic = &epic
	if RequestEnd(d, "open-pr", now) == nil {
		t.Fatal("open-pr needs a feature branch")
	}
	d.Settings.FeatureBranch = store.Ptr("feat")
	if err := RequestEnd(d, "open-pr", now); err != nil || len(d.EndReqs) != 1 {
		t.Fatal(err)
	}
	if RequestEnd(d, "grind-pr", now) == nil {
		t.Fatal("grind-pr needs final_prs")
	}
	d.FinalPRs = map[string]string{"o/r": "u"}
	if RequestEnd(d, "grind-pr", now) != nil || RequestEnd(d, "qa", now) != nil || RequestEnd(d, "nope", now) == nil {
		t.Fatal("end actions")
	}
	d.Issues = []string{"o/r#2"}
	if RequestEnd(d, "qa", now) == nil {
		t.Fatal("refused for a list of issues")
	}
}

func TestApplySettings(t *testing.T) {
	d := store.Defaults()
	good, err := ApplySettings(d, map[string]any{"max": 5, "grind": "simple", "ci": "defer", "auto_merge": true, "model": "opus", "effort": "high", "account": "work", "max_cost": 12.5, "feature_branch": "feat/x"})
	if err != nil || good.Max != 5 || good.Grind != "simple" || !good.AutoMerge || *good.MaxCost != 12.5 || *good.FeatureBranch != "feat/x" {
		t.Fatal(good, err)
	}
	bad := []map[string]any{
		{"max": 0}, {"max": 11}, {"max": "3"}, {"max": 2.5}, {"max": true},
		{"grind": "maybe"}, {"ci": "x"}, {"nope": 1}, {"model": "-bad"}, {"model": 3}, {"effort": "huge"}, {"account": ""},
		{"max_cost": 0}, {"max_cost": 10001}, {"max_cost": "5"}, {"feature_branch": "a b"}, {"base_branch": "x y"},
		{"feature_branch": "same", "base_branch": "same"},
	}
	for _, b := range bad {
		if _, err := ApplySettings(d, b); err == nil {
			t.Errorf("%v accepted", b)
		}
	}
	if s, err := ApplySettings(good, map[string]any{"max_cost": nil, "model": nil}); err != nil || s.MaxCost != nil || s.Model != nil {
		t.Fatal("null clears", s, err)
	}
	if s, _ := ApplySettings(d, map[string]any{"auto_merge": "yes", "skip_approval": nil}); !s.AutoMerge || s.SkipApproval {
		t.Fatal("coerced to bool")
	}
	if noFeatureBranch(good) == nil {
		t.Fatal("issue lists have no feature branch")
	}
}

func TestIssuesTitle(t *testing.T) {
	if got := IssuesTitle([]string{"o/r#9", "o/r#2", "o/r#4", "o/r#7", "o/r#3"}); got != "Small changes: #2, #3, #4 +2 more" {
		t.Fatal(got)
	}
	if got := IssuesTitle([]string{"o/r#2"}); got != "Small changes: #2" {
		t.Fatal(got)
	}
}
