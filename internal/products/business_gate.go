package products

import (
	"context"
	"io/fs"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
)

// BusinessGate is the cached result of blubird's check-business-docs.py on a product's
// docs/business. State: pass | fail | unavailable (Reason says why). Running is true while a check
// runs; the result shown is then the previous one.
type BusinessGate struct {
	State     string   `json:"state"`
	Failures  []string `json:"failures"`
	Reason    *string  `json:"reason"`
	CheckedAt *string  `json:"checked_at"`
	Running   bool     `json:"running"`
}

const (
	gateTimeout     = 30 * time.Second
	gateMaxFailures = 200
	gateChecker     = "skills/collect-docs/scripts/check-business-docs.py"
	noStamp         = "none" // the stamp of a product with no docs/business
)

type gateEntry struct {
	gate    BusinessGate
	seen    string // the newest stamp a tick saw
	stored  bool
	running bool
}

// businessState is the gate cache; its zero value is usable.
type businessState struct {
	mu      sync.Mutex
	wg      sync.WaitGroup
	m       map[string]*gateEntry // lower(docs repo)
	checker func() string         // blubird's install path ("" when not installed)
	timeout time.Duration
}

func unavailable(reason string) BusinessGate {
	return BusinessGate{State: "unavailable", Failures: []string{}, Reason: &reason}
}

// SetBusinessChecker sets the func returning blubird's install path, where the checker lives.
func (r *Registry) SetBusinessChecker(f func() string) {
	r.biz.mu.Lock()
	r.biz.checker = f
	r.biz.mu.Unlock()
}

// WaitBusiness blocks until every running gate check has finished.
func (r *Registry) WaitBusiness() { r.biz.wg.Wait() }

func (r *Registry) gateEntry(product string) *gateEntry {
	if r.biz.m == nil {
		r.biz.m = map[string]*gateEntry{}
	}
	k := strings.ToLower(product)
	e, ok := r.biz.m[k]
	if !ok {
		e = &gateEntry{}
		r.biz.m[k] = e
	}
	return e
}

// BusinessGate returns the cached gate of a product. It never runs anything: before the first
// result it is unavailable, "not checked yet".
func (r *Registry) BusinessGate(product string) BusinessGate {
	r.biz.mu.Lock()
	defer r.biz.mu.Unlock()
	e := r.gateEntry(product)
	g := unavailable("not checked yet")
	if e.stored {
		g = e.gate
		g.Failures = append([]string{}, e.gate.Failures...)
	}
	g.Running = e.running
	return g
}

// businessStamp is the newest modification time under dir, files and folders (so a delete is
// seen), plus the entry count. Stat only.
func businessStamp(dir string) string {
	var newest int64
	n := 0
	_ = filepath.WalkDir(dir, func(_ string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if fi, err := d.Info(); err == nil {
			if t := fi.ModTime().UnixNano(); t > newest {
				newest = t
			}
			n++
		}
		return nil
	})
	return strconv.FormatInt(newest, 10) + "/" + strconv.Itoa(n)
}

// CheckBusiness runs from the poll tick: for each valid product whose docs/business changed since
// the last tick, it starts the checker in the background (one run per product at a time). It never
// waits for a run.
func (r *Registry) CheckBusiness(ctx context.Context) {
	for _, p := range r.Products() {
		if p.Error != "" || ctx.Err() != nil {
			continue
		}
		dir := filepath.Join(p.Path, "docs", "business")
		stamp := noStamp
		if isDir(dir) {
			stamp = businessStamp(dir)
		}
		r.biz.mu.Lock()
		e := r.gateEntry(p.DocsRepo)
		if stamp == e.seen {
			r.biz.mu.Unlock()
			continue
		}
		e.seen = stamp
		if stamp == noStamp {
			// nothing to run; a run in flight sees the folder gone and stores this too
			if !e.running {
				e.gate, e.stored = unavailable("no docs/business"), true
				e.gate.CheckedAt = nowStamp()
			}
			r.biz.mu.Unlock()
			r.changed("business", p.DocsRepo)
			continue
		}
		start := !e.running
		if start {
			e.running = true
			r.biz.wg.Add(1)
		}
		r.biz.mu.Unlock()
		r.changed("business", p.DocsRepo)
		if start {
			go r.runGate(p, dir)
		}
	}
}

// runGate checks until the result belongs to the stamp the docs have when it ends: a change during
// a run drops that result and runs once more.
func (r *Registry) runGate(p Product, dir string) {
	defer r.biz.wg.Done()
	for {
		before := noStamp
		if isDir(dir) {
			before = businessStamp(dir)
		}
		var g BusinessGate
		if before == noStamp {
			g = unavailable("no docs/business")
		} else {
			g = r.checkBusiness(p.Path)
		}
		after := noStamp
		if isDir(dir) {
			after = businessStamp(dir)
		}
		r.biz.mu.Lock()
		e := r.gateEntry(p.DocsRepo)
		if after != before {
			e.seen = after
			r.biz.mu.Unlock()
			continue
		}
		g.CheckedAt = nowStamp()
		e.gate, e.stored, e.running, e.seen = g, true, false, after
		r.biz.mu.Unlock()
		r.changed("business", p.DocsRepo)
		return
	}
}

func nowStamp() *string {
	t := time.Now().UTC().Format(time.RFC3339)
	return &t
}

// checkBusiness runs the checker once in the docs checkout and maps its exit code.
func (r *Registry) checkBusiness(checkout string) BusinessGate {
	if _, err := exec.LookPath("python3"); err != nil {
		return unavailable("python3 not found")
	}
	r.biz.mu.Lock()
	install, timeout := "", r.biz.timeout
	if r.biz.checker != nil {
		install = r.biz.checker()
	}
	r.biz.mu.Unlock()
	if timeout <= 0 {
		timeout = gateTimeout
	}
	script := filepath.Join(install, filepath.FromSlash(gateChecker))
	if install == "" || !exists(script) {
		return unavailable("blubird older than 1.2.0")
	}
	res := execx.Run(context.Background(), []string{"python3", "-I", script, "docs/business"}, execx.Opts{Dir: checkout, Timeout: timeout})
	switch res.Code {
	case 0:
		return BusinessGate{State: "pass", Failures: []string{}}
	case 1:
		fails := []string{}
		for _, l := range strings.Split(string(res.Stdout), "\n") {
			if l = strings.TrimRight(l, "\r"); strings.TrimSpace(l) != "" && len(fails) < gateMaxFailures {
				fails = append(fails, l)
			}
		}
		if len(fails) == 0 {
			fails = append(fails, res.LastLine())
		}
		return BusinessGate{State: "fail", Failures: fails}
	case 124:
		return unavailable("timed out")
	case 127:
		return unavailable("python3 not found")
	default:
		return unavailable("checker exited " + strconv.Itoa(res.Code) + ": " + res.LastLine())
	}
}
