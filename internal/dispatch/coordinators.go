package dispatch

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/sessions"
)

// blubird's project-coordinator keeps its state under ~/.claude/project-coordinator/:
//
//	<slug>.json                       {repo, destination, updated}
//	claims/<slug>/<issue>/run         the run dir an issue is claimed by
//	runs/<slug>/<stamp>/              config.json {repo, source, destination, max, started, ...},
//	                                  queue.tsv (issue \t state \t title), prs.json, poll_stats.json,
//	                                  events.log, loop.pid (present while the loop runs), control/
//
// setu only reads it (and stops a loop through coordinator.sh); the coordinator itself runs as an
// interactive blubird session started from the project-coordinator step.

const (
	coordEvents   = 20
	coordMaxRuns  = 40
	coordStopWait = 30 * time.Second
)

// CoordQueue is one line of queue.tsv.
type CoordQueue struct {
	Issue int    `json:"issue"`
	State string `json:"state"` // ok | blocked:#a,#b | not-ready:... | done ...
	Title string `json:"title"`
}

// CoordPoll is poll_stats.json.
type CoordPoll struct {
	Calls  int64  `json:"calls"`
	Last   int64  `json:"last"`
	Result string `json:"result"`
	Every  int64  `json:"every"`
}

// Coordinator is one project-coordinator run (§4 Coordinator).
type Coordinator struct {
	Run         string         `json:"run"`
	Repo        string         `json:"repo"`
	Source      string         `json:"source"`
	Destination string         `json:"destination"`
	Session     *string        `json:"session"`
	Live        bool           `json:"live"`
	Queue       []CoordQueue   `json:"queue"`
	Claims      []int          `json:"claims"`
	PRs         map[string]any `json:"prs"`
	Poll        *CoordPoll     `json:"poll"`
	Events      []string       `json:"events"`

	dir string
}

func (s *Service) coordRoot() string {
	if s.d.CoordRoot != "" {
		return s.d.CoordRoot
	}
	h, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(h, ".claude", "project-coordinator")
}

func pidAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

func readLines(path string, keep int) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	var ring []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64<<10), 1<<20)
	for sc.Scan() {
		if line := strings.TrimRight(sc.Text(), "\r"); line != "" {
			ring = append(ring, line)
			if len(ring) > keep {
				ring = ring[1:]
			}
		}
	}
	return ring
}

// parseQueue reads queue.tsv: issue, state and title separated by tabs.
func parseQueue(path string) []CoordQueue {
	out := []CoordQueue{}
	for _, line := range readLines(path, 10000) {
		f := strings.SplitN(line, "\t", 3)
		if len(f) < 2 {
			continue
		}
		n, err := strconv.Atoi(strings.TrimSpace(f[0]))
		if err != nil {
			continue
		}
		q := CoordQueue{Issue: n, State: f[1]}
		if len(f) == 3 {
			q.Title = f[2]
		}
		out = append(out, q)
	}
	return out
}

type coordConfig struct {
	Repo        string `json:"repo"`
	Source      string `json:"source"`
	Destination string `json:"destination"`
	Started     string `json:"started"`
}

func readRun(root, slug, stamp string) (Coordinator, coordConfig, bool) {
	dir := filepath.Join(root, "runs", slug, stamp)
	b, err := os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil {
		return Coordinator{}, coordConfig{}, false
	}
	var cfg coordConfig
	if json.Unmarshal(b, &cfg) != nil {
		return Coordinator{}, coordConfig{}, false
	}
	c := Coordinator{Run: stamp, Repo: cfg.Repo, Source: cfg.Source, Destination: cfg.Destination, dir: dir,
		Queue: parseQueue(filepath.Join(dir, "queue.tsv")), Claims: []int{}, PRs: map[string]any{}, Events: []string{}}
	if pb, err := os.ReadFile(filepath.Join(dir, "loop.pid")); err == nil {
		pid, _ := strconv.Atoi(strings.TrimSpace(string(pb)))
		c.Live = pidAlive(pid)
	}
	if b, err := os.ReadFile(filepath.Join(dir, "prs.json")); err == nil {
		var m map[string]any
		if json.Unmarshal(b, &m) == nil && m != nil {
			c.PRs = m
		}
	}
	if b, err := os.ReadFile(filepath.Join(dir, "poll_stats.json")); err == nil {
		var p CoordPoll
		if json.Unmarshal(b, &p) == nil {
			c.Poll = &p
		}
	}
	if ev := readLines(filepath.Join(dir, "events.log"), coordEvents); ev != nil {
		c.Events = ev
	}
	// claims/<slug>/<issue>/run holds the path of the run dir that owns the issue
	if ents, err := os.ReadDir(filepath.Join(root, "claims", slug)); err == nil {
		for _, e := range ents {
			rb, err := os.ReadFile(filepath.Join(root, "claims", slug, e.Name(), "run"))
			if err != nil {
				continue
			}
			if filepath.Clean(strings.TrimSpace(string(rb))) == dir {
				if n, err := strconv.Atoi(e.Name()); err == nil {
					c.Claims = append(c.Claims, n)
				}
			}
		}
		sort.Ints(c.Claims)
	}
	return c, cfg, true
}

// Coordinators lists the project-coordinator runs, newest first: every live one and the most
// recent others. A run started by a setu session is matched to it by the repo's run start time.
func (s *Service) Coordinators() []Coordinator {
	root := s.coordRoot()
	if root == "" {
		return []Coordinator{}
	}
	type item struct {
		c       Coordinator
		started time.Time
		stamp   string
	}
	var all []item
	slugs, err := os.ReadDir(filepath.Join(root, "runs"))
	if err != nil {
		return []Coordinator{}
	}
	for _, sl := range slugs {
		if !sl.IsDir() {
			continue
		}
		stamps, _ := os.ReadDir(filepath.Join(root, "runs", sl.Name()))
		for _, st := range stamps {
			if !st.IsDir() {
				continue
			}
			c, cfg, ok := readRun(root, sl.Name(), st.Name())
			if !ok {
				continue
			}
			t, _ := time.ParseInLocation("2006-01-02 15:04:05", cfg.Started, time.Local)
			all = append(all, item{c, t, st.Name()})
		}
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].stamp > all[j].stamp })
	var recs []sessions.Record
	if s.d.Sessions != nil {
		recs = s.d.Sessions.List(sessions.Filter{Limit: 200, Step: "project-coordinator"})
	}
	out := []Coordinator{}
	for _, it := range all {
		if len(out) >= coordMaxRuns && !it.c.Live {
			continue
		}
		if sid := matchSession(recs, it.started); sid != "" {
			it.c.Session = &sid
		}
		out = append(out, it.c)
	}
	return out
}

// matchSession picks the project-coordinator session that started closest before the run began.
func matchSession(recs []sessions.Record, started time.Time) string {
	if started.IsZero() {
		return ""
	}
	best, bestD := "", 30*time.Minute+1
	for _, r := range recs {
		if r.Step != "project-coordinator" && r.Kind != "coordinator" {
			continue
		}
		t, err := time.Parse(time.RFC3339, r.StartedAt)
		if err != nil {
			continue
		}
		d := started.Sub(t)
		if d >= -30*time.Second && d < bestD {
			best, bestD = r.ID, d
		}
	}
	return best
}

// StopCoordinator runs `<blubird>/skills/project-coordinator/scripts/coordinator.sh stop <run dir>`.
// The sessions of the run are left alone.
func (s *Service) StopCoordinator(ctx context.Context, run string) error {
	if run == "" || strings.ContainsAny(run, `/\`) || run == "." || run == ".." {
		return errs.NotFound("no coordinator run %q", run)
	}
	root := s.coordRoot()
	var dirs []string
	slugs, _ := os.ReadDir(filepath.Join(root, "runs"))
	for _, sl := range slugs {
		d := filepath.Join(root, "runs", sl.Name(), run)
		if fi, err := os.Stat(filepath.Join(d, "config.json")); err == nil && !fi.IsDir() {
			dirs = append(dirs, d)
		}
	}
	switch len(dirs) {
	case 0:
		return errs.NotFound("no coordinator run %q", run)
	case 1:
	default:
		return errs.Conflict("coordinator run "+run+" is ambiguous", nil)
	}
	if s.d.SkillDir == nil {
		return errs.Upstream("blubird is not installed")
	}
	dir, ok := s.d.SkillDir("project-coordinator")
	if !ok {
		return errs.Upstream("blubird is not installed")
	}
	r := execx.Run(ctx, StopArgv(dir, dirs[0]), execx.Opts{Timeout: coordStopWait})
	if r.Code != 0 {
		return errs.Upstream("coordinator stop failed: %s", r.LastLine())
	}
	if s.d.Bus != nil {
		s.d.Bus.Publish("products", map[string]any{"kind": "coordinator"})
	}
	return nil
}

// StopArgv is the command that stops a coordinator loop.
func StopArgv(skillDir, runDir string) []string {
	return []string{filepath.Join(skillDir, "scripts", "coordinator.sh"), "stop", runDir}
}

// StartCoordinator starts the project-coordinator step as a session in the product's
// Documentation Repo (docs is its slug). args is `<issues link | n> [--destination L] [--max N]`.
func (s *Service) StartCoordinator(ctx context.Context, docs, args string) (sessions.Record, error) {
	if s.d.Sessions == nil || s.d.Prompts == nil {
		return sessions.Record{}, errs.Upstream("no session manager")
	}
	if err := s.d.Prompts.Available("project-coordinator"); err != nil {
		return sessions.Record{}, err
	}
	p, err := s.d.Prompts.BuildIn("project-coordinator", args, docs)
	if err != nil {
		return sessions.Record{}, err
	}
	return s.d.Sessions.Launch(ctx, sessions.Spec{
		Prompt: sessions.Prompt{Step: p.Step, Display: p.Display, Text: p.Text}, Args: args, Cwd: docs,
		Gate: true, Kind: "coordinator",
	})
}
