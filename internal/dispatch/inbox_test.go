package dispatch

import (
	"testing"

	"github.com/masnun-siam/setu/internal/dispatch/store"
)

func TestInboxRowsAndDropOwned(t *testing.T) {
	epic := "o/r#1"
	live := &store.Dispatch{ID: "aaaaaaaaaaaa", Epic: &epic, State: store.Running, Settings: store.Defaults(), Lanes: map[string]*store.Lane{}}
	add := func(l store.Lane) { live.Lanes[l.Key()] = &l }
	add(store.Lane{Repo: "o/r", N: 1, Stage: store.StImplementing, NeedsYou: "waiting on you", Held: "x"})
	add(store.Lane{Repo: "o/r", N: 2, Stage: store.StGrinding, Held: "grind paused: stuck", PR: 12})
	add(store.Lane{Repo: "o/r", N: 3, Stage: store.StAwaitingMerge, PR: 13})
	add(store.Lane{Repo: "o/r", N: 4, Stage: store.StImplementing, LimitedUntil: 2000})
	add(store.Lane{Repo: "o/r", N: 5, Stage: store.StImplementing, LimitedUntil: 500}) // expired
	add(store.Lane{Repo: "o/r", N: 6, Stage: store.StClosed})
	done := store.Dispatch{ID: "bbbbbbbbbbbb", Epic: &epic, State: store.Done, Title: "Done one", Settings: store.Defaults(), Lanes: map[string]*store.Lane{},
		FinalPRs: map[string]string{"o/r": "u"}}
	done.Settings.FeatureBranch = store.Ptr("feat")
	seen := store.Dispatch{ID: "cccccccccccc", State: store.Done, SeenDone: true, Settings: store.Defaults(), Lanes: map[string]*store.Lane{}}
	cancelled := store.Dispatch{ID: "dddddddddddd", State: store.Cancelled, Settings: store.Defaults(), Lanes: map[string]*store.Lane{"o/r#9": {Repo: "o/r", N: 9, NeedsYou: "x"}}}

	rows := InboxRows([]store.Dispatch{*live, done, seen, cancelled}, 1000)
	want := []struct{ key, group, typ, reason string }{
		{"dispatch:aaaaaaaaaaaa:o/r#1:needs", "answer", "dispatch_lane", "waiting on you"},
		{"dispatch:aaaaaaaaaaaa:o/r#2:held", "fix", "dispatch_lane", "grind paused: stuck"},
		{"dispatch:aaaaaaaaaaaa:o/r#3:merge", "decide", "dispatch_lane", "PR #13 is ready to merge"},
		{"dispatch:aaaaaaaaaaaa:o/r#4:limited", "wait", "dispatch_lane", "Claude usage limit"},
		{"dispatch:bbbbbbbbbbbb:done", "decide", "dispatch_done", ""},
	}
	if len(rows) != len(want) {
		t.Fatalf("%d rows: %+v", len(rows), rows)
	}
	for i, w := range want {
		r := rows[i]
		if r.Key != w.key || r.Group != w.group || r.Type != w.typ || r.Reason != w.reason {
			t.Errorf("row %d: %+v", i, r)
		}
	}
	if rows[3].ResetsAt != 2000 || rows[0].Dispatch != "aaaaaaaaaaaa" || rows[0].Issue != 1 || rows[0].Repo != "o/r" {
		t.Fatalf("%+v", rows[3])
	}
	if r := rows[4]; r.FeatureBranch != "feat" || r.FinalPRs["o/r"] != "u" || *r.Epic != "o/r#1" || r.Repo != "o/r" {
		t.Fatalf("%+v", r)
	}

	owned := OwnedBy([]store.Dispatch{*live, done, cancelled})
	cases := []struct {
		typ, repo string
		issue, pr int
		drop      bool
	}{
		{"pr_ready", "o/r", 0, 12, true},
		{"pr_conflict", "O/R", 2, 0, true},
		{"grind_paused", "o/r", 0, 12, true},
		{"session_failed", "o/r", 1, 0, true},
		{"pr_ready", "o/r", 0, 99, false},
		{"waiting", "o/r", 1, 0, false},  // other types stay
		{"pr_ready", "o/r", 6, 0, false}, // closed lane owns nothing
		{"pr_ready", "o/r", 9, 0, false}, // cancelled dispatch owns nothing
		{"pr_ready", "x/y", 1, 0, false},
	}
	for _, c := range cases {
		if got := owned.Drops(c.typ, c.repo, c.issue, c.pr); got != c.drop {
			t.Errorf("%+v: %v", c, got)
		}
	}
}
