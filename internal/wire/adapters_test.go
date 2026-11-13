package wire

import (
	"path/filepath"
	"testing"

	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/home"
)

func TestLanesStuckAndContinue(t *testing.T) {
	h := &home.Home{Root: filepath.Join(t.TempDir(), ".setu")}
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", Title: "T", Runner: "headless", State: store.Running, Settings: store.Defaults(), Lanes: map[string]*store.Lane{}}
	for _, x := range []*store.Lane{
		{Repo: "o/r", N: 1, Stage: store.StImplementing, Stalled: dispatch.Stalled, Handle: &store.Handle{Session: "S1"}},
		{Repo: "o/r", N: 2, Stage: store.StMergeGate, Held: "CI is red"},
		{Repo: "o/r", N: 3, Stage: store.StImplementing, NeedsYou: "waiting on you"},
		{Repo: "o/r", N: 4, Stage: store.StImplementing},
	} {
		x.Deps = []string{}
		d.Lanes[x.Key()] = x
	}
	if err := store.Save(h, d); err != nil {
		t.Fatal(err)
	}
	l := lanes{dispatch.New(dispatch.Deps{Home: h})}
	got := map[int]bool{}
	for _, s := range l.Stuck() {
		got[s.Issue] = s.Stalled
		if s.Issue == 1 && s.Why != "Stalled: "+dispatch.Stalled {
			t.Errorf("why %q", s.Why)
		}
	}
	if len(got) != 2 || !got[1] || got[2] {
		t.Fatalf("stuck %v", got)
	}
	if err := l.Continue(d.ID, "o/r#1"); err != nil {
		t.Fatal(err)
	}
	if err := l.Continue(d.ID, "o/r#1"); err == nil {
		t.Fatal("a continued lane is no longer stalled")
	}
	for _, s := range l.Stuck() {
		if s.Issue == 1 {
			t.Fatalf("continued lane still stuck: %+v", s)
		}
	}
}
