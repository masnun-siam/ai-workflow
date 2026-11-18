package products

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

type gateFx struct {
	r       *Registry
	docs    string
	bin     string
	install string
	script  string
	mu      sync.Mutex
	evs     []map[string]any
}

// newGateFx registers a product with one business doc, installs the fakes (python3 among them) and
// a fake blubird install holding the checker file.
func newGateFx(t *testing.T) *gateFx {
	t.Helper()
	r, ws, bus := setup(t)
	docs, _ := product(t, ws)
	if _, err := r.Register(context.Background(), docs); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(docs, "docs/business/auth/login.md"), bizDoc)
	f := &gateFx{r: r, docs: docs, bin: filepath.Join(ws, "bin"), install: filepath.Join(ws, "blubird")}
	f.script = filepath.Join(f.install, "skills/collect-docs/scripts/check-business-docs.py")
	write(t, f.script, "# fake\n")
	fakebin.Install(t, f.bin)
	r.SetBusinessChecker(func() string { return f.install })
	ch, cancel := bus.Subscribe(64)
	t.Cleanup(cancel)
	go func() {
		for ev := range ch {
			if ev.Topic != events.TProducts {
				continue
			}
			if m, ok := ev.Data.(map[string]any); ok && m["kind"] == "business" {
				f.mu.Lock()
				f.evs = append(f.evs, m)
				f.mu.Unlock()
			}
		}
	}()
	return f
}

func (f *gateFx) rules(t *testing.T, rs ...fakebin.Rule) { fakebin.WriteRules(t, f.bin, rs) }

func (f *gateFx) tick() {
	f.r.CheckBusiness(context.Background())
	f.r.WaitBusiness()
}

func (f *gateFx) gate() BusinessGate { return f.r.BusinessGate("acme/shop-wiki") }

func (f *gateFx) calls(t *testing.T) []fakebin.Call {
	var out []fakebin.Call
	for _, c := range fakebin.Calls(t, f.bin) {
		if c.Bin == "python3" {
			out = append(out, c)
		}
	}
	return out
}

// events waits briefly for the bus and returns the business events seen so far.
func (f *gateFx) events() int {
	time.Sleep(50 * time.Millisecond)
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.evs)
}

// touch rewrites the doc with a newer mtime so the stamp changes.
func (f *gateFx) touch(t *testing.T, body string) {
	t.Helper()
	p := filepath.Join(f.docs, "docs/business/auth/login.md")
	write(t, p, body)
	later := time.Now().Add(time.Duration(len(f.calls(t))+1) * time.Second)
	os.Chtimes(p, later, later)
}

func checkerRule(exit int, stdout, stderr string, sleep int) fakebin.Rule {
	return fakebin.Rule{Bin: "python3", ArgsContains: "check-business-docs.py", Exit: exit, Stdout: stdout, Stderr: stderr, SleepMs: sleep}
}

func TestBusinessGateResults(t *testing.T) {
	f := newGateFx(t)
	if g := f.gate(); g.State != "unavailable" || *g.Reason != "not checked yet" || g.Failures == nil || g.CheckedAt != nil || g.Running {
		t.Fatalf("before first run %+v", g)
	}
	f.rules(t, checkerRule(1, "docs/business/auth/login.md: timeline bullet not dated\n\n1 rules checked in business docs, 0 links between docs; 1 failures\n", "", 0))
	f.tick()
	g := f.gate()
	want := []string{"docs/business/auth/login.md: timeline bullet not dated", "1 rules checked in business docs, 0 links between docs; 1 failures"}
	if g.State != "fail" || !reflect.DeepEqual(g.Failures, want) || g.Reason != nil || g.CheckedAt == nil {
		t.Fatalf("fail %+v", g)
	}
	cs := f.calls(t)
	if len(cs) != 1 || !reflect.DeepEqual(cs[0].Args, []string{"-I", f.script, "docs/business"}) || realpath(cs[0].Cwd) != f.docs {
		t.Fatalf("calls %+v", cs)
	}

	// no change: the next ticks run nothing
	f.tick()
	f.tick()
	if n := len(f.calls(t)); n != 1 {
		t.Fatalf("idle ticks ran the checker: %d calls", n)
	}

	// fixing the doc turns the gate to pass on the next tick
	f.rules(t, checkerRule(0, "1 rules checked in business docs, 0 links between docs; 0 failures\n", "", 0))
	f.touch(t, bizDoc+"\n")
	f.tick()
	if g := f.gate(); g.State != "pass" || len(g.Failures) != 0 || g.Failures == nil || len(f.calls(t)) != 2 {
		t.Fatalf("pass %+v", g)
	}

	cases := []struct {
		rule   fakebin.Rule
		state  string
		reason string
		fails  []string
	}{
		{checkerRule(1, "", "Traceback\nKeyError: x\n", 0), "fail", "", []string{"KeyError: x"}},
		{checkerRule(2, "", "usage: check-business-docs.py\n", 0), "unavailable", "checker exited 2: usage: check-business-docs.py", nil},
		{checkerRule(0, "", "", 1500), "unavailable", "timed out", nil},
	}
	f.r.biz.timeout = 300 * time.Millisecond
	for i, c := range cases {
		f.rules(t, c.rule)
		f.touch(t, bizDoc+string(rune('a'+i)))
		f.tick()
		g := f.gate()
		reason := ""
		if g.Reason != nil {
			reason = *g.Reason
		}
		if g.State != c.state || reason != c.reason || (c.fails != nil && !reflect.DeepEqual(g.Failures, c.fails)) || g.Failures == nil {
			t.Errorf("case %d: %+v (%s)", i, g, reason)
		}
	}
}

func TestBusinessGateUnavailable(t *testing.T) {
	f := newGateFx(t)
	reason := func() string {
		g := f.gate()
		if g.State != "unavailable" || g.Reason == nil {
			t.Fatalf("%+v", g)
		}
		return *g.Reason
	}
	// blubird not installed, then installed without the checker
	f.r.SetBusinessChecker(func() string { return "" })
	f.tick()
	if r := reason(); r != "blubird older than 1.2.0" {
		t.Fatal(r)
	}
	f.r.SetBusinessChecker(func() string { return filepath.Join(f.install, "old") })
	f.touch(t, bizDoc+"x")
	f.tick()
	if r := reason(); r != "blubird older than 1.2.0" {
		t.Fatal(r)
	}
	if n := len(f.calls(t)); n != 0 {
		t.Fatalf("ran %d", n)
	}
	// no docs/business
	os.RemoveAll(filepath.Join(f.docs, "docs/business"))
	f.tick()
	if r := reason(); r != "no docs/business" {
		t.Fatal(r)
	}
	// no python3 on PATH
	empty := t.TempDir()
	t.Setenv("PATH", empty)
	f.r.SetBusinessChecker(func() string { return f.install })
	f.touch(t, bizDoc)
	f.tick()
	if r := reason(); r != "python3 not found" {
		t.Fatal(r)
	}
}

func TestBusinessGateChangeDuringRunAndEvents(t *testing.T) {
	f := newGateFx(t)
	f.rules(t, fakebin.Rule{Bin: "python3", ArgsContains: "check-business-docs.py", Exit: 1, Stdout: "first\n", SleepMs: 400, Once: true},
		checkerRule(0, "second\n", "", 0))
	f.r.CheckBusiness(context.Background())
	// a request during the run returns the previous result at once, flagged running
	if g := f.gate(); !g.Running || g.State != "unavailable" {
		t.Fatalf("during run %+v", g)
	}
	time.Sleep(100 * time.Millisecond)
	f.touch(t, bizDoc+"\n")
	f.r.CheckBusiness(context.Background()) // sees the change, does not start a second run
	f.r.WaitBusiness()
	if n := len(f.calls(t)); n != 2 {
		t.Fatalf("calls %d", n)
	}
	if g := f.gate(); g.State != "pass" || g.Running {
		t.Fatalf("stored %+v", g)
	}
	// events: tick 1 (stamp), tick 2 (stamp), one stored result
	if n := f.events(); n != 3 {
		t.Fatalf("events %d", n)
	}
	f.tick()
	f.tick()
	if n := f.events(); n != 3 {
		t.Fatalf("idle ticks published: %d", n)
	}
	f.mu.Lock()
	repo := f.evs[0]["repo"]
	f.mu.Unlock()
	if repo != "acme/shop-wiki" {
		t.Fatalf("repo %v", repo)
	}
}
