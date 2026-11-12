package store

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

func newHome(t *testing.T) *home.Home {
	t.Helper()
	h := &home.Home{Root: t.TempDir()}
	t.Setenv("SETU_HOME", h.Root)
	return h
}

func mk(h *home.Home, id string, state string, created float64, lanes ...*Lane) *Dispatch {
	d := &Dispatch{ID: id, Title: id, Runner: "headless", State: state, Settings: Defaults(), Lanes: map[string]*Lane{}, CreatedAt: created}
	for _, l := range lanes {
		d.Lanes[l.Key()] = l
	}
	if err := Save(h, d); err != nil {
		panic(err)
	}
	return d
}

func TestRoundTripKeepsUnknownKeysAndDefaults(t *testing.T) {
	h := newHome(t)
	old := `{"id":"0123456789ab","epic":"o/r#1","title":"T","runner":"headless","workspace":null,"settings":{"max":3,"grind":"simple"},
	"state":"running","lanes":{"o/r#5":{"repo":"o/r","n":5,"title":"x","deps":null,"base":null,"stage":"queued","skip_reason":null,"handle":null,"pr":null,
	"herdr_extra":1,"outbox":[["send","hi"],["close",null]],"started_at":12.5}},"events":[{"at":1.5,"lane":null,"kind":"started","text":"1 lanes"}],"created_at":10.0,"ended_at":null,"future_key":{"a":1}}`
	if err := os.MkdirAll(filepath.Join(h.Root, "dispatches"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(h.Root, "dispatches", "0123456789ab.json"), []byte(old), 0o644); err != nil {
		t.Fatal(err)
	}
	d, err := Load(h, "0123456789ab")
	if err != nil {
		t.Fatal(err)
	}
	if d.Settings.Max != 3 || d.Settings.Grind != "simple" || d.Settings.CI != "wait" {
		t.Fatalf("defaults under stored settings: %+v", d.Settings)
	}
	l := d.Lanes["o/r#5"]
	if l.Deps == nil || l.StartedAt != 12.5 || len(l.Outbox) != 2 || l.Outbox[0].Text != "hi" || l.Outbox[1].Kind != "close" {
		t.Fatalf("%+v", l)
	}
	if err := Save(h, &d); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(h.Root, "dispatches", "0123456789ab.json"))
	var m map[string]json.RawMessage
	_ = json.Unmarshal(b, &m)
	if compact(m["future_key"]) != `{"a":1}` {
		t.Fatalf("unknown dispatch key lost: %s", b)
	}
	var lanes map[string]map[string]json.RawMessage
	_ = json.Unmarshal(m["lanes"], &lanes)
	if compact(lanes["o/r#5"]["herdr_extra"]) != "1" {
		t.Fatalf("unknown lane key lost: %s", b)
	}
	if !strings.Contains(compact(lanes["o/r#5"]["outbox"]), `["close",null]`) {
		t.Fatalf("outbox shape: %s", lanes["o/r#5"]["outbox"])
	}
	if !strings.HasPrefix(string(b), "{\n \"") {
		t.Fatalf("indent 1: %q", string(b[:10]))
	}
}

func TestIDsAndMissing(t *testing.T) {
	h := newHome(t)
	for _, bad := range []string{"", "xyz", "0123456789AB", "../etc/passwd", "0123456789abc"} { // gitleaks:allow
		if _, err := Load(h, bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%q: %v", bad, err)
		}
		if _, err := Lock(h, bad); err == nil {
			t.Errorf("%q locked", bad)
		}
	}
	if _, err := Load(h, "0123456789ab"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal(err)
	}
	if len(NewID()) != 12 || !ValidID(NewID()) {
		t.Fatal("NewID")
	}
	if List(h) != nil && len(List(h)) != 0 {
		t.Fatal("empty store")
	}
}

func TestListNewestFirstSkipsUnreadable(t *testing.T) {
	h := newHome(t)
	mk(h, "aaaaaaaaaaaa", Done, 1)
	mk(h, "bbbbbbbbbbbb", Running, 3)
	mk(h, "cccccccccccc", Paused, 2)
	if err := os.WriteFile(filepath.Join(h.Root, "dispatches", "dddddddddddd.json"), []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, d := range List(h) {
		ids = append(ids, d.ID)
	}
	if strings.Join(ids, ",") != "bbbbbbbbbbbb,cccccccccccc,aaaaaaaaaaaa" {
		t.Fatal(ids)
	}
}

func TestCreateOwnership(t *testing.T) {
	h := newHome(t)
	a := &Dispatch{ID: "aaaaaaaaaaaa", State: Running, Settings: Defaults(), Lanes: map[string]*Lane{"o/r#1": {Repo: "o/r", N: 1}}}
	if err := Create(h, a); err != nil {
		t.Fatal(err)
	}
	b := &Dispatch{ID: "bbbbbbbbbbbb", State: Running, Settings: Defaults(), Lanes: map[string]*Lane{"o/r#1": {Repo: "o/r", N: 1}, "o/r#2": {Repo: "o/r", N: 2}}}
	err := Create(h, b)
	var e *errs.Error
	if errs.KindOf(err) != errs.KConflict || !errorsAs(err, &e) || e.Extra["id"] != "aaaaaaaaaaaa" {
		t.Fatalf("%v", err)
	}
	if _, err := Load(h, "bbbbbbbbbbbb"); err == nil {
		t.Fatal("a refused dispatch must not be saved")
	}
	// a finished dispatch releases its issues
	a.State = Done
	_ = Save(h, a)
	if err := Create(h, b); err != nil {
		t.Fatal(err)
	}
	if OwnerOf(h, "o/r#2") != "bbbbbbbbbbbb" || OwnerOf(h, "o/r#9") != "" {
		t.Fatal("OwnerOf")
	}
}

func compact(b []byte) string {
	var buf bytes.Buffer
	_ = json.Compact(&buf, b)
	return buf.String()
}

func errorsAs(err error, e **errs.Error) bool {
	x, ok := errs.As(err)
	*e = x
	return ok
}

func TestActiveLaneAndGrindMode(t *testing.T) {
	h := newHome(t)
	d := mk(h, "aaaaaaaaaaaa", Running, 1, &Lane{Repo: "Owner/Repo", N: 4, Stage: StGrinding, PR: 12}, &Lane{Repo: "Owner/Repo", N: 5, Stage: StQueued, PR: 13},
		&Lane{Repo: "Owner/Repo", N: 6, Stage: StClosed, PR: 14})
	d.Settings.Grind = "simple"
	_ = Save(h, d)
	id, l, ok := ActiveLane(h, "owner/repo", 4, 0)
	if !ok || id != "aaaaaaaaaaaa" || l.PR != 12 {
		t.Fatal(id, l, ok)
	}
	if _, _, ok := ActiveLane(h, "owner/repo", 0, 12); !ok {
		t.Fatal("by PR")
	}
	for _, c := range []struct {
		repo      string
		issue, pr int
	}{{"owner/repo", 5, 0}, {"owner/repo", 0, 13}, {"owner/repo", 6, 14}, {"other/repo", 4, 0}, {"owner/repo", 0, 0}} {
		if _, _, ok := ActiveLane(h, c.repo, c.issue, c.pr); ok {
			t.Errorf("%+v owned", c)
		}
	}
	if m, ok := GrindMode(h, "https://github.com/owner/repo/pull/12"); !ok || m != "simple" {
		t.Fatal(m, ok)
	}
	if _, ok := GrindMode(h, "https://github.com/owner/repo/pull/99"); ok {
		t.Fatal("not owned")
	}
	d.Settings.Grind = "full"
	_ = Save(h, d)
	if m, _ := GrindMode(h, "https://github.com/OWNER/repo/pull/12"); m != "deep" {
		t.Fatal(m)
	}
	d.State = Done
	_ = Save(h, d)
	if _, ok := GrindMode(h, "https://github.com/owner/repo/pull/12"); ok {
		t.Fatal("a done dispatch owns nothing")
	}
	if _, _, ok := ActiveLane(h, "owner/repo", 4, 0); ok {
		t.Fatal("a done dispatch owns nothing")
	}
}

func TestArchiveOld(t *testing.T) {
	h := newHome(t)
	day := 86400.0
	now := 100 * day
	old := mk(h, "aaaaaaaaaaaa", Done, 1)
	old.EndedAt = now - 31*day
	_ = Save(h, old)
	recent := mk(h, "bbbbbbbbbbbb", Cancelled, 1)
	recent.EndedAt = now - 29*day
	_ = Save(h, recent)
	running := mk(h, "cccccccccccc", Running, 1) // ancient but running
	_ = running
	noEnd := mk(h, "dddddddddddd", Done, now-40*day) // falls back to created_at
	_ = noEnd
	if err := os.WriteFile(filepath.Join(h.Root, "dispatches", "eeeeeeeeeeee.json"), []byte("garbage"), 0o644); err != nil {
		t.Fatal(err)
	}
	moved := ArchiveOld(h, now, 30)
	if strings.Join(moved, ",") != "aaaaaaaaaaaa,dddddddddddd" {
		t.Fatal(moved)
	}
	for _, id := range moved {
		if _, err := os.Stat(filepath.Join(h.Root, "dispatches", "archive", id+".json")); err != nil {
			t.Fatal(err)
		}
		if _, err := Load(h, id); err == nil {
			t.Fatal("still in the live dir")
		}
	}
	for _, id := range []string{"bbbbbbbbbbbb", "cccccccccccc", "eeeeeeeeeeee"} {
		if _, err := os.Stat(filepath.Join(h.Root, "dispatches", id+".json")); err != nil {
			t.Fatalf("%s must stay: %v", id, err)
		}
	}
}

func TestLockSerializes(t *testing.T) {
	h := newHome(t)
	var wg sync.WaitGroup
	counter, max := 0, 0
	var mu sync.Mutex
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			unlock, err := Lock(h, "aaaaaaaaaaaa")
			if err != nil {
				t.Error(err)
				return
			}
			mu.Lock()
			counter++
			if counter > max {
				max = counter
			}
			mu.Unlock()
			mu.Lock()
			counter--
			mu.Unlock()
			unlock()
		}()
	}
	wg.Wait()
	if max != 1 {
		t.Fatalf("two holders at once: %d", max)
	}
	un, err := StoreLock(h)
	if err != nil {
		t.Fatal(err)
	}
	un()
	if _, err := os.Stat(filepath.Join(h.Root, "dispatches", ".store.lock")); err != nil {
		t.Fatal(".store.lock:", err)
	}
}

func TestEventsCapAndKeys(t *testing.T) {
	d := &Dispatch{}
	for i := 0; i < MaxEvents+20; i++ {
		d.AddEvent("", "k", "t", float64(i))
	}
	if len(d.Events) != MaxEvents || d.Events[0].At != 20 {
		t.Fatal(len(d.Events), d.Events[0].At)
	}
	d.Lanes = map[string]*Lane{"o/r#10": {Repo: "o/r", N: 10}, "o/r#2": {Repo: "o/r", N: 2}, "a/b#2": {Repo: "a/b", N: 2}}
	if strings.Join(d.SortedKeys(), ",") != "a/b#2,o/r#2,o/r#10" {
		t.Fatal(d.SortedKeys())
	}
	e := Event{}
	e = d.AddEvent("o/r#2", "lane", "x", 1)
	if e.Lane == nil || *e.Lane != "o/r#2" {
		t.Fatal(e)
	}
}

func TestListSharedFollowsWritesAndIsRaceFree(t *testing.T) {
	h := newHome(t)
	mk(h, "aaaaaaaaaaaa", Running, 1, &Lane{Repo: "o/r", N: 1, Stage: StQueued, PR: 7})
	if got := ListShared(h); len(got) != 1 {
		t.Fatal(got)
	}
	if m, ok := GrindMode(h, "https://github.com/o/r/pull/7"); !ok || m != "deep" {
		t.Fatal(m, ok)
	}
	// a write by this process shows at once
	mk(h, "bbbbbbbbbbbb", Running, 2, &Lane{Repo: "o/r", N: 2, Stage: StQueued, PR: 8})
	if got := ListShared(h); len(got) != 2 || got[0].ID != "bbbbbbbbbbbb" {
		t.Fatal(got)
	}
	// a write by another process (no Save here) shows through the directory mtime
	other := `{"id":"cccccccccccc","title":"c","runner":"headless","state":"running","settings":{"grind":"simple"},"lanes":{"o/r#9":{"repo":"o/r","n":9,"stage":"queued","pr":9}},"created_at":3}`
	if err := os.WriteFile(filepath.Join(h.Root, "dispatches", "cccccccccccc.json"), []byte(other), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := ListShared(h); len(got) != 3 {
		t.Fatal(got)
	}
	if m, ok := GrindMode(h, "https://github.com/o/r/pull/9"); !ok || m != "simple" {
		t.Fatal(m, ok)
	}
	if err := os.Remove(filepath.Join(h.Root, "dispatches", "cccccccccccc.json")); err != nil {
		t.Fatal(err)
	}
	if _, ok := GrindMode(h, "https://github.com/o/r/pull/9"); ok || len(ListShared(h)) != 2 {
		t.Fatal("removed dispatch still listed")
	}
	// the returned slice is the caller's own
	l := ListShared(h)
	l[0] = Dispatch{}
	if ListShared(h)[0].ID == "" {
		t.Fatal("slice shared with the cache")
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 50; j++ {
				ListShared(h)
				GrindMode(h, "https://github.com/o/r/pull/7")
				ActiveLane(h, "o/r", 1, 0)
			}
		}()
	}
	mk(h, "dddddddddddd", Running, 4)
	wg.Wait()
}
