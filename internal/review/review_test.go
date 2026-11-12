package review

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/sessions"
)

// ---- fakes ----

type fakeSessions struct {
	mu        sync.Mutex
	recs      map[string]*sessions.Record
	final     map[string]string
	specs     []sessions.Spec
	resumes   []resumeCall
	stops     []string
	n         int
	failIn    int // the Nth next Launch fails (after creating its record); 0 = none
	resumeErr error
}

type resumeCall struct{ ID, Text string }

func newFake() *fakeSessions {
	return &fakeSessions{recs: map[string]*sessions.Record{}, final: map[string]string{}}
}

func (f *fakeSessions) add(status sessions.Status) string {
	f.n++
	id := fmt.Sprintf("s%d", f.n)
	f.recs[id] = &sessions.Record{ID: id, Status: status, ClaudeCmd: "claude"}
	return id
}

func (f *fakeSessions) Launch(_ context.Context, s sessions.Spec) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	id := f.add(sessions.StRunning)
	r := f.recs[id]
	r.Panel, _ = s.Fields["panel"].(string)
	r.PanelRole, _ = s.Fields["panel_role"].(string)
	r.PanelLens, _ = s.Fields["panel_lens"].(string)
	r.ClaudeCmd = s.Cmd
	f.specs = append(f.specs, s)
	if f.failIn > 0 {
		f.failIn--
		if f.failIn > 0 {
			return *r, nil
		}
		r.Status = sessions.StFailed
		return *r, errs.Upstream("spawn failed")
	}
	return *r, nil
}
func (f *fakeSessions) Get(id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if r, ok := f.recs[id]; ok {
		return *r, nil
	}
	return sessions.Record{}, errs.NotFound("session not found")
}
func (f *fakeSessions) Update(id string, fn func(*sessions.Record) error) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("session not found")
	}
	return *r, fn(r)
}
func (f *fakeSessions) Resume(_ context.Context, id, text string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.resumeErr != nil {
		return f.resumeErr
	}
	f.resumes = append(f.resumes, resumeCall{id, text})
	f.recs[id].Status = sessions.StRunning
	return nil
}
func (f *fakeSessions) Stop(_ context.Context, id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stops = append(f.stops, id)
	f.recs[id].Status = sessions.StStopped
	return *f.recs[id], nil
}
func (f *fakeSessions) FinalText(id string) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.final[id]
}
func (f *fakeSessions) set(id string, st sessions.Status) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.recs[id].Status = st
}
func (f *fakeSessions) finish(id, text string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.final[id] = text
	f.recs[id].Status = sessions.StDone
}

type fakePrompts struct{}

func (fakePrompts) Build(step, args string) (prompts.Prompt, error) {
	return prompts.Prompt{Step: step, Display: "/" + step + " " + args, Text: "BODY\n\nARGUMENTS: " + args}, nil
}
func (fakePrompts) Agent(name string) (string, []string, error) {
	return "AGENT BODY", []string{"Read", "Grep"}, nil
}

type fakeNotify struct {
	mu    sync.Mutex
	calls []string
}

func (n *fakeNotify) Notify(ev string, note notify.Note) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.calls = append(n.calls, ev+"|"+note.ID+"|"+note.Text)
}

type env struct {
	t        *testing.T
	h        *home.Home
	s        *Service
	f        *fakeSessions
	n        *fakeNotify
	artifact string
}

func setup(t *testing.T) *env {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	h := &home.Home{Root: t.TempDir()}
	f, n := newFake(), &fakeNotify{}
	art := filepath.Join(t.TempDir(), "prd.md")
	if err := os.WriteFile(art, []byte("# PRD\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	s := New(Deps{Home: h, Sessions: f, Prompts: fakePrompts{}, Notify: n})
	return &env{t, h, s, f, n, art}
}

func (e *env) create(c CreatePanel) Panel {
	e.t.Helper()
	if c.Repo == "" {
		c.Repo = "acme/app"
	}
	if c.Artifact == "" {
		c.Artifact = e.artifact
	}
	p, err := e.s.Create(context.Background(), c)
	if err != nil {
		e.t.Fatalf("create: %v", err)
	}
	return p
}

func (e *env) tick() { e.s.Tick(context.Background()) }

func (e *env) get(id string) Panel {
	e.t.Helper()
	p, err := e.s.Get(id)
	if err != nil {
		e.t.Fatal(err)
	}
	return p
}

// ---- verdicts ----

func TestParseVerdict(t *testing.T) {
	for _, tc := range []struct{ name, in, want string }{
		{"plain approve", "Looks fine.\nVerdict: approve", "approve"},
		{"plain changes", "Verdict: changes", "changes"},
		{"case", "VERDICT: APPROVE", "approve"},
		{"bold colon outside needs no space-less form (W§5.2 regex)", "**Verdict:** approve", "changes"},
		{"bold colon outside, tight", "**Verdict:**approve", "approve"},
		{"bold inside", "**Verdict: approve**", "approve"},
		{"heading", "## Verdict: changes", "changes"},
		{"quote", "> Verdict: approve", "approve"},
		{"bullet dash", "- Verdict: approve", "approve"},
		{"backticks", "`Verdict: approve`", "approve"},
		{"underscores", "_Verdict: changes_", "changes"},
		{"last wins", "Verdict: approve\nmore\nVerdict: changes", "changes"},
		{"last wins 2", "Verdict: changes\nafter edits\nVerdict: approve", "approve"},
		{"none", "I think it is fine.", "changes"},
		{"empty", "", "changes"},
		{"approved is not approve", "Verdict: approved", "changes"},
		{"changes-requested", "Verdict: changes-requested", "changes"},
		{"approve-with-nits skipped", "Verdict: approve\nVerdict: approve-with-nits", "approve"},
		{"approve then dot", "Verdict: approve.", "approve"},
		{"mid-line is no verdict", "my Verdict: approve", "changes"},
		{"indented", "   Verdict: approve", "approve"},
		{"crlf", "text\r\nVerdict: approve\r\n", "approve"},
		{"no space", "Verdict:approve", "approve"},
		{"underscore continues word", "Verdict: approve_all", "changes"},
		{"unicode letter continues", "Verdict: approveé", "changes"},
	} {
		if got := ParseVerdict(tc.in); got != tc.want {
			t.Errorf("%s: ParseVerdict(%q) = %q, want %q", tc.name, tc.in, got, tc.want)
		}
	}
}

// ---- config ----

func TestShippedConfig(t *testing.T) {
	c := Shipped()
	if c.MaxRounds != 5 || len(c.DefaultLenses) != 1 || c.DefaultLenses[0] != "critical" {
		t.Fatalf("%+v", c)
	}
	for _, l := range []string{"critical", "ceo", "cto", "security", "qa", "ux", "performance"} {
		if c.Lenses[l].Prompt == "" || c.Lenses[l].Focus == "" {
			t.Errorf("lens %s empty", l)
		}
	}
	for kind, n := range map[string]int{"create-prd": 7, "intake": 5, "dump": 3, "gh-issue": 6, "custom": 7} {
		if len(c.Kinds[kind]) != n {
			t.Errorf("kind %s offers %v", kind, c.Kinds[kind])
		}
	}
}

func TestCheckLenses(t *testing.T) {
	c := Shipped()
	got, err := c.CheckLenses("dump", []string{"qa", "critical", "qa"})
	if err != nil || strings.Join(got, ",") != "qa,critical" {
		t.Fatalf("%v %v", got, err)
	}
	for _, tc := range []struct {
		kind   string
		picked []string
		msg    string
	}{
		{"dump", nil, "dump offers the lenses critical, ceo, qa; got none"},
		{"dump", []string{"ux", "cto"}, "dump offers the lenses critical, ceo, qa; got ux, cto"},
		{"dump", []string{"critical", "ux"}, "got ux"},
		{"nope", []string{"critical"}, "nope has no peer review; one of "},
	} {
		_, err := c.CheckLenses(tc.kind, tc.picked)
		if errs.KindOf(err) != errs.KInvalid || !strings.Contains(err.Error(), tc.msg) {
			t.Errorf("%v: %v", tc, err)
		}
	}
}

func TestConfigOverlayAndSave(t *testing.T) {
	h := &home.Home{Root: t.TempDir()}
	cfg, over := LoadConfig(h)
	if over || cfg.MaxRounds != 5 {
		t.Fatalf("%v %+v", over, cfg)
	}
	// a hand-written overlay: one lens prompt changed, a new lens, max rounds
	os.WriteFile(h.Path("config.json"), []byte(`{"other":1,"peer_review":{"max_rounds":3,"lenses":{"qa":{"prompt":"my qa"},"legal":{"prompt":"check the law","focus":"law"}}}}`), 0o644)
	cfg, over = LoadConfig(h)
	if !over || cfg.MaxRounds != 3 || cfg.Lenses["qa"].Prompt != "my qa" || cfg.Lenses["qa"].Focus != Shipped().Lenses["qa"].Focus {
		t.Fatalf("%v %+v", over, cfg.Lenses["qa"])
	}
	if cfg.Lenses["legal"].Focus != "law" || !contains(cfg.Kinds["custom"], "legal") || contains(cfg.Kinds["dump"], "legal") {
		t.Fatalf("legal not offered under custom only: %+v", cfg.Kinds)
	}
	v := View(h)
	if !v.Overridden || v.Lenses["qa"] != "my qa" || v.Shipped.Lenses["qa"] == "my qa" || v.Shipped.MaxRounds != 5 {
		t.Fatalf("%+v", v)
	}

	// save
	body := func(s string) SaveConfigInput {
		var in SaveConfigInput
		if err := json.Unmarshal([]byte(s), &in); err != nil {
			t.Fatal(err)
		}
		return in
	}
	v, err := SaveConfig(h, body(`{"max_rounds":4,"default_lenses":["critical","qa","qa"],"lenses":{"qa":"qa v2"}}`))
	if err != nil || v.MaxRounds != 4 || strings.Join(v.DefaultLenses, ",") != "critical,qa" || v.Lenses["qa"] != "qa v2" || !v.Overridden {
		t.Fatalf("%+v %v", v, err)
	}
	var top map[string]any
	b, _ := os.ReadFile(h.Path("config.json"))
	json.Unmarshal(b, &top)
	if top["other"] != float64(1) {
		t.Fatalf("other top-level key lost: %s", b)
	}
	for _, bad := range []string{
		`{"max_rounds":0,"default_lenses":["critical"],"lenses":{}}`,
		`{"max_rounds":21,"default_lenses":["critical"],"lenses":{}}`,
		`{"max_rounds":true,"default_lenses":["critical"],"lenses":{}}`,
		`{"max_rounds":2.5,"default_lenses":["critical"],"lenses":{}}`,
		`{"max_rounds":"3","default_lenses":["critical"],"lenses":{}}`,
		`{"default_lenses":["critical"],"lenses":{}}`,
		`{"max_rounds":3,"default_lenses":[],"lenses":{}}`,
		`{"max_rounds":3,"default_lenses":["bogus"],"lenses":{}}`,
		`{"max_rounds":3,"default_lenses":["critical"],"lenses":{"bad name":"x"}}`,
		`{"max_rounds":3,"default_lenses":["critical"],"lenses":{"x":"  "}}`,
	} {
		if _, err := SaveConfig(h, body(bad)); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%s: %v", bad, err)
		}
	}
	v, err = SaveConfig(h, body(`{"reset":true}`))
	if err != nil || v.Overridden || v.MaxRounds != 5 {
		t.Fatalf("%+v %v", v, err)
	}
	b, _ = os.ReadFile(h.Path("config.json"))
	if strings.Contains(string(b), "peer_review") || !strings.Contains(string(b), `"other"`) {
		t.Fatalf("reset: %s", b)
	}
}

func TestCorruptConfigIgnored(t *testing.T) {
	h := &home.Home{Root: t.TempDir()}
	os.WriteFile(h.Path("config.json"), []byte(`{{{`), 0o644)
	if cfg, over := LoadConfig(h); over || cfg.MaxRounds != 5 {
		t.Fatalf("%v %+v", over, cfg)
	}
	os.WriteFile(h.Path("config.json"), []byte(`{"peer_review":{"max_rounds":"x","default_lenses":["qa"]}}`), 0o644)
	cfg, _ := LoadConfig(h)
	if cfg.MaxRounds != 5 || cfg.DefaultLenses[0] != "qa" {
		t.Fatalf("%+v", cfg)
	}
}

// ---- panel lifecycle ----

func TestCreateFreshRoot(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa"}})
	if !ValidID(p.ID) || p.Round != 1 || p.State != StRunning || p.Phase != PhLenses || p.MaxRounds != 5 {
		t.Fatalf("%+v", p)
	}
	if p.RootSession == nil || len(e.f.specs) != 3 {
		t.Fatalf("root + 2 lenses expected: %d specs", len(e.f.specs))
	}
	root := e.f.specs[0]
	if !root.Gate || root.Kind != "panel-root" || root.Prompt.Display != "/peer-review --root "+p.ID+" "+e.artifact ||
		root.Fields["panel_role"] != "root" || root.Cwd != "acme/app" {
		t.Fatalf("root spec: %+v", root)
	}
	lens := e.f.specs[1]
	if lens.Agent != "peer-reviewer" || lens.Model != "opus" || lens.Kind != "lens" || strings.Join(lens.AllowedTools, ",") != "Read,Grep" ||
		lens.Fields["panel"] != p.ID || lens.Fields["panel_lens"] != "critical" {
		t.Fatalf("lens spec: %+v", lens)
	}
	for _, want := range []string{"Review the artifact at " + e.artifact + " through the critical lens", "round 1 of panel " + p.ID,
		"You are read-only: edit nothing", "Report at most 8 findings", "`Verdict: approve` or `Verdict: changes`", Shipped().Lenses["critical"].Focus} {
		if !strings.Contains(lens.Prompt.Text, want) {
			t.Errorf("lens prompt lacks %q", want)
		}
	}
	if strings.Contains(lens.Prompt.Text, "revised since") {
		t.Error("round 1 must not say revised")
	}
	if len(p.LensSession) != 2 || p.Status.Total != 2 || p.Status.Lenses["qa"] != "waiting" {
		t.Fatalf("%+v", p)
	}
	if strings.HasPrefix(lens.Prompt.Text, "-") {
		t.Fatal("prompt starts with a dash")
	}
	// persisted in the Python layout
	var raw map[string]any
	b, _ := os.ReadFile(e.h.Path("peer-review", p.ID, "panel.json"))
	json.Unmarshal(b, &raw)
	for _, k := range []string{"id", "repo", "artifact", "lenses", "root_session", "round", "dropped", "failed", "state", "reason", "phase", "lens_sessions"} {
		if _, ok := raw[k]; !ok {
			t.Errorf("panel.json lacks %q", k)
		}
	}
	if _, ok := raw["max_rounds"]; ok {
		t.Error("max_rounds is only written after a raise")
	}
}

func TestCreateValidation(t *testing.T) {
	e := setup(t)
	dir := t.TempDir()
	for name, c := range map[string]CreatePanel{
		"no repo":      {Repo: "bad", Artifact: e.artifact, Lenses: []string{"critical"}},
		"relative":     {Repo: "a/b", Artifact: "rel.md", Lenses: []string{"critical"}},
		"missing file": {Repo: "a/b", Artifact: filepath.Join(dir, "none.md"), Lenses: []string{"critical"}},
		"directory":    {Repo: "a/b", Artifact: dir, Lenses: []string{"critical"}},
		"no lenses":    {Repo: "a/b", Artifact: e.artifact},
		"unknown lens": {Repo: "a/b", Artifact: e.artifact, Lenses: []string{"bogus"}},
		"missing root": {Repo: "a/b", Artifact: e.artifact, Lenses: []string{"critical"}, RootSession: "s99"},
	} {
		if _, err := e.s.Create(context.Background(), c); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%s: %v", name, err)
		}
	}
	if len(e.f.specs) != 0 || len(e.s.List()) != 0 {
		t.Fatalf("nothing may be created: %d specs, %d panels", len(e.f.specs), len(e.s.List()))
	}
}

func TestCreateWithRootAndAccount(t *testing.T) {
	e := setup(t)
	root := e.f.add(sessions.StRunning)
	e.f.recs[root].ClaudeCmd = "cc-work"
	p := e.create(CreatePanel{Lenses: []string{"critical"}, RootSession: root})
	if len(e.f.specs) != 1 || e.f.specs[0].Cmd != "cc-work" {
		t.Fatalf("lens must use the root's account: %+v", e.f.specs)
	}
	r, _ := e.f.Get(root)
	if r.Panel != p.ID || r.PanelRole != "root" {
		t.Fatalf("root not tagged: %+v", r)
	}
	if *p.RootSession != root {
		t.Fatal("root_session")
	}
}

func TestCreateAfterRoot(t *testing.T) {
	e := setup(t)
	root := e.f.add(sessions.StRunning)
	p := e.create(CreatePanel{Lenses: []string{"critical", "ceo"}, RootSession: root, AfterRoot: true})
	if p.Phase != PhWaitRoot || len(e.f.specs) != 0 {
		t.Fatalf("%+v specs=%d", p, len(e.f.specs))
	}
	e.tick()
	if e.get(p.ID).Phase != PhWaitRoot || len(e.f.specs) != 0 {
		t.Fatal("must wait while the root runs")
	}
	e.f.set(root, sessions.StDone)
	e.tick()
	if e.get(p.ID).Phase != PhLenses || len(e.f.specs) != 2 {
		t.Fatalf("lenses must start when the root is done: %+v specs=%d", e.get(p.ID), len(e.f.specs))
	}
	// a root that fails before it is done
	root2 := e.f.add(sessions.StRunning)
	p2 := e.create(CreatePanel{Lenses: []string{"critical"}, RootSession: root2, AfterRoot: true})
	e.f.set(root2, sessions.StFailed)
	e.tick()
	if q := e.get(p2.ID); q.State != StFailed || *q.Reason != "root session failed" || q.Phase != PhDone {
		t.Fatalf("%+v", q)
	}
}

func TestCreateFailureFailsPanel(t *testing.T) {
	e := setup(t)
	root := e.f.add(sessions.StRunning)
	e.f.failIn = 2 // the second lens fails to start
	_, err := e.s.Create(context.Background(), CreatePanel{Repo: "a/b", Artifact: e.artifact, Lenses: []string{"critical", "qa"}, RootSession: root})
	if err == nil {
		t.Fatal("want error")
	}
	ps := e.s.List()
	if len(ps) != 1 || ps[0].State != StFailed || ps[0].Phase != PhDone || !strings.HasPrefix(*ps[0].Reason, "could not start: ") {
		t.Fatalf("%+v", ps)
	}
	if len(e.f.stops) != 1 {
		t.Fatalf("the busy lens session must be stopped: %v", e.f.stops)
	}
}

func lensIDs(p Panel) map[string]string { return p.LensSession }

func TestFullApproveRound1(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa"}})
	ids := lensIDs(p)
	e.f.set(*p.RootSession, sessions.StDone) // the fresh root stays idle
	e.tick()
	if e.get(p.ID).State != StRunning {
		t.Fatal("lenses still running")
	}
	e.f.finish(ids["critical"], "ok\nVerdict: approve")
	e.tick()
	got := e.get(p.ID)
	if got.State != StRunning || got.Status.Approved != 1 || got.Status.Lenses["critical"] != "approve" || got.Status.Lenses["qa"] != "waiting" {
		t.Fatalf("%+v", got)
	}
	// the raw final message is on disk
	b, _ := os.ReadFile(e.h.Path("peer-review", p.ID, "round-1", "critical.md"))
	if string(b) != "ok\nVerdict: approve" {
		t.Fatalf("verdict file: %q", b)
	}
	e.f.finish(ids["qa"], "fine\n**Verdict: approve**")
	e.tick()
	got = e.get(p.ID)
	if got.State != StApproved || got.Phase != PhDone || got.Reason != nil || got.Status.Approved != 2 {
		t.Fatalf("%+v", got)
	}
	if len(e.n.calls) != 0 {
		t.Fatalf("approval does not notify: %v", e.n.calls)
	}
	n := len(e.f.resumes)
	e.tick()
	if len(e.f.resumes) != n {
		t.Fatal("a finished panel is not touched again")
	}
}

func TestRoundsAndCap(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa"}})
	root, ids := *p.RootSession, lensIDs(p)
	e.f.set(root, sessions.StDone)

	// round 1: qa wants changes
	e.f.finish(ids["critical"], "Verdict: approve")
	e.f.finish(ids["qa"], "1. blocker: missing check\nVerdict: changes")
	e.tick()
	got := e.get(p.ID)
	if got.Round != 2 || got.Phase != PhRoot || got.State != StRunning {
		t.Fatalf("%+v", got)
	}
	if len(e.f.resumes) != 1 || e.f.resumes[0].ID != root {
		t.Fatalf("root must be resumed once: %+v", e.f.resumes)
	}
	msg := e.f.resumes[0].Text
	for _, want := range []string{"Peer-review panel " + p.ID + ", round 1 verdicts on " + e.artifact + ":", "\n--- critical ---\nVerdict: approve",
		"\n--- qa ---\n1. blocker: missing check", "Now revise the artifact in place", "re-review as round 2."} {
		if !strings.Contains(msg, want) {
			t.Errorf("root message lacks %q:\n%s", want, msg)
		}
	}
	// while the root works nothing happens
	e.f.set(root, sessions.StRunning)
	e.tick()
	if len(e.f.resumes) != 1 || e.get(p.ID).Phase != PhRoot {
		t.Fatal("must wait for the root")
	}
	// root done -> every active lens resumed with the round prompt
	e.f.set(root, sessions.StDone)
	e.tick()
	got = e.get(p.ID)
	if got.Phase != PhLenses || len(e.f.resumes) != 3 {
		t.Fatalf("%+v resumes=%d", got, len(e.f.resumes))
	}
	for _, rc := range e.f.resumes[1:] {
		if !strings.Contains(rc.Text, "round 2 of panel "+p.ID) || !strings.Contains(rc.Text, "revised since your last round") {
			t.Errorf("round prompt: %s", rc.Text)
		}
	}
	if got.Status.Lenses["critical"] != "waiting" {
		t.Fatalf("round 2 starts with no verdicts: %+v", got.Status)
	}
	// rounds 2..5 keep asking for changes -> cap
	for round := 2; round <= 5; round++ {
		e.f.finish(ids["critical"], "Verdict: approve")
		e.f.finish(ids["qa"], "Verdict: changes")
		e.tick()
		got = e.get(p.ID)
		if round < 5 {
			if got.Round != round+1 || got.Phase != PhRoot {
				t.Fatalf("round %d: %+v", round, got)
			}
			e.f.set(root, sessions.StDone)
			e.tick()
		}
	}
	got = e.get(p.ID)
	if got.State != StCap || got.Phase != PhDone || got.Round != 5 || *got.Reason != "round cap reached" {
		t.Fatalf("%+v", got)
	}
	if len(e.n.calls) != 1 || e.n.calls[0] != "panel-cap|"+p.ID+"|prd.md: round cap reached" {
		t.Fatalf("notify: %v", e.n.calls)
	}
	e.tick()
	if len(e.n.calls) != 1 {
		t.Fatal("cap notifies once")
	}

	// add rounds
	if _, err := e.s.AddRounds(p.ID, 0); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("add 0: %v", err)
	}
	if _, err := e.s.AddRounds(p.ID, 6); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("add 6: %v", err)
	}
	e.f.set(root, sessions.StRunning)
	if _, err := e.s.AddRounds(p.ID, 2); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("busy root: %v", err)
	}
	e.f.set(root, sessions.StDone)
	nres := len(e.f.resumes)
	got, err := e.s.AddRounds(p.ID, 2)
	if err != nil || got.MaxRounds != 7 || got.Round != 6 || got.State != StRunning || got.Phase != PhRoot || got.Reason != nil {
		t.Fatalf("%+v %v", got, err)
	}
	if len(e.f.resumes) != nres+1 || !strings.Contains(e.f.resumes[nres].Text, "round 5 verdicts") || !strings.Contains(e.f.resumes[nres].Text, "as round 6.") {
		t.Fatalf("%+v", e.f.resumes[nres:])
	}
	// not at the cap any more
	if _, err := e.s.AddRounds(p.ID, 1); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("running: %v", err)
	}
}

func TestAddRoundsRestoresOnFailure(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical"}})
	// jump the panel to its cap by hand
	raw, _ := e.s.load(p.ID)
	raw.State, raw.Phase, raw.Round = StCap, PhDone, 5
	reason := "round cap reached"
	raw.Reason = &reason
	e.s.save(raw)
	e.f.set(*p.RootSession, sessions.StDone)
	e.f.resumeErr = errors.New("cannot resume")
	if _, err := e.s.AddRounds(p.ID, 3); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("%v", err)
	}
	got := e.get(p.ID)
	if got.State != StCap || got.Round != 5 || got.MaxRounds != 5 || got.Phase != PhDone || got.Reason == nil {
		t.Fatalf("not restored: %+v", got)
	}
	// no root at all
	raw, _ = e.s.load(p.ID)
	raw.RootSession = nil
	e.s.save(raw)
	if _, err := e.s.AddRounds(p.ID, 1); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("no root: %v", err)
	}
	if _, err := e.s.AddRounds("p-bad", 1); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("bad id: %v", err)
	}
}

func TestHeldLensDelaysRound(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa"}})
	root, ids := *p.RootSession, lensIDs(p)
	e.f.set(root, sessions.StDone)
	e.f.finish(ids["critical"], "Verdict: changes")
	e.f.finish(ids["qa"], "Verdict: changes")
	e.tick() // -> root phase
	e.f.set(root, sessions.StDone)
	e.f.recs[ids["qa"]].Hold = true // the user held the qa lens
	e.tick()
	if got := e.get(p.ID); got.Phase != PhRoot || len(e.f.resumes) != 1 {
		t.Fatalf("a held lens delays the round for everyone: %+v resumes=%d", got, len(e.f.resumes))
	}
	e.f.recs[ids["qa"]].Hold = false
	e.tick()
	if got := e.get(p.ID); got.Phase != PhLenses || len(e.f.resumes) != 3 {
		t.Fatalf("%+v resumes=%d", got, len(e.f.resumes))
	}
}

func TestBusyRootBlocksAdvance(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical"}})
	root, ids := *p.RootSession, lensIDs(p)
	e.f.set(root, sessions.StRunning)
	e.f.finish(ids["critical"], "Verdict: approve")
	e.tick()
	got := e.get(p.ID)
	if got.State != StRunning || got.Status.Approved != 1 {
		t.Fatalf("the verdict is recorded but the panel waits: %+v", got)
	}
	e.f.set(root, sessions.StDone)
	e.tick()
	if e.get(p.ID).State != StApproved {
		t.Fatal("approved once the root is idle")
	}
	// a held root also counts as busy
	p2 := e.create(CreatePanel{Lenses: []string{"critical"}})
	e.f.finish(lensIDs(p2)["critical"], "Verdict: approve")
	e.f.set(*p2.RootSession, sessions.StDone)
	e.f.recs[*p2.RootSession].Hold = true
	e.tick()
	if e.get(p2.ID).State != StRunning {
		t.Fatal("held root is busy")
	}
}

func TestLensFailureRerunDrop(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa", "ceo"}})
	root, ids := *p.RootSession, lensIDs(p)
	e.f.set(root, sessions.StDone)
	e.f.set(ids["critical"], sessions.StFailed)
	e.f.set(ids["qa"], sessions.StStopped)
	delete(e.f.recs, ids["ceo"]) // gone
	e.tick()
	got := e.get(p.ID)
	if strings.Join(got.Failed, ",") != "critical,qa,ceo" || got.Status.Lenses["qa"] != "failed" || got.State != StRunning {
		t.Fatalf("%+v", got)
	}
	// conflicts and validation
	if _, err := e.s.LensAction(p.ID, "bogus", "drop"); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("unknown lens: %v", err)
	}
	if _, err := e.s.LensAction(p.ID, "qa", "explode"); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("bad action: %v", err)
	}
	// rerun critical: a new session replaces the old one
	nspec := len(e.f.specs)
	got, err := e.s.LensAction(p.ID, "critical", "rerun")
	if err != nil || len(e.f.specs) != nspec+1 || got.LensSession["critical"] == ids["critical"] || contains(got.Failed, "critical") {
		t.Fatalf("%+v %v", got, err)
	}
	// drop qa
	got, err = e.s.LensAction(p.ID, "qa", "drop")
	if err != nil || !contains(got.Dropped, "qa") || contains(got.Failed, "qa") || got.Status.Total != 2 {
		t.Fatalf("%+v %v", got, err)
	}
	// qa is no longer failed: a second action conflicts
	if _, err := e.s.LensAction(p.ID, "qa", "rerun"); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("not failed: %v", err)
	}
	if _, err := e.s.LensAction(p.ID, "critical", "drop"); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("healthy lens: %v", err)
	}
	// rerun that cannot start
	e.f.failIn = 1
	if _, err := e.s.LensAction(p.ID, "ceo", "rerun"); errs.KindOf(err) != errs.KConflict || !strings.Contains(err.Error(), "could not restart") {
		t.Fatalf("restart failure: %v", err)
	}
	if !contains(e.get(p.ID).Failed, "ceo") {
		t.Fatal("ceo must stay failed")
	}
	// the remaining lenses approve -> approved without the dropped one
	e.f.finish(e.get(p.ID).LensSession["critical"], "Verdict: approve")
	if _, err := e.s.LensAction(p.ID, "ceo", "drop"); err != nil {
		t.Fatal(err)
	}
	e.tick()
	if got := e.get(p.ID); got.State != StApproved {
		t.Fatalf("%+v", got)
	}
	// panel not running -> conflict
	if _, err := e.s.LensAction(p.ID, "critical", "rerun"); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("done panel: %v", err)
	}
}

func TestAllLensesDropped(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical"}})
	e.f.set(*p.RootSession, sessions.StDone)
	e.f.set(lensIDs(p)["critical"], sessions.StFailed)
	e.tick()
	if _, err := e.s.LensAction(p.ID, "critical", "drop"); err != nil {
		t.Fatal(err)
	}
	e.tick()
	got := e.get(p.ID)
	if got.State != StFailed || got.Phase != PhDone || *got.Reason != "every lens was dropped" {
		t.Fatalf("%+v", got)
	}
}

func TestRootGoneFailsPanelAndStopsLenses(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical", "qa"}})
	delete(e.f.recs, *p.RootSession)
	e.tick()
	got := e.get(p.ID)
	if got.State != StFailed || *got.Reason != "root session gone" {
		t.Fatalf("%+v", got)
	}
	if len(e.f.stops) != 2 {
		t.Fatalf("busy lenses must be stopped: %v", e.f.stops)
	}
}

func TestArtifactDeleted(t *testing.T) {
	e := setup(t)
	p := e.create(CreatePanel{Lenses: []string{"critical"}})
	os.Remove(e.artifact)
	e.tick()
	if got := e.get(p.ID); got.State != StFailed || *got.Reason != "artifact deleted" {
		t.Fatalf("%+v", got)
	}
}

func TestCorruptPanelJSON(t *testing.T) {
	e := setup(t)
	good := e.create(CreatePanel{Lenses: []string{"critical"}})
	bad := e.create(CreatePanel{Lenses: []string{"critical"}})
	path := e.h.Path("peer-review", bad.ID, "panel.json")
	os.WriteFile(path, []byte("{not json"), 0o644)
	if _, err := e.s.Get(bad.ID); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("corrupt Get: %v", err)
	}
	if got := e.s.List(); len(got) != 1 || got[0].ID != good.ID {
		t.Fatalf("list must skip the corrupt panel: %+v", got)
	}
	e.tick() // must not panic, backs the file up, keeps ticking the good panel
	matches, _ := filepath.Glob(path + ".corrupt-*")
	if len(matches) != 1 {
		t.Fatalf("backup: %v", matches)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("corrupt file must be moved aside")
	}
	e.tick()
	if got := e.get(good.ID); got.State != StRunning {
		t.Fatalf("%+v", got)
	}
	// non-object JSON, and an id mismatch
	os.WriteFile(e.h.Path("peer-review", good.ID, "panel.json"), []byte(`[1,2]`), 0o644)
	if _, err := e.s.Get(good.ID); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("array: %v", err)
	}
	e.tick()
	// a stray directory is ignored
	os.MkdirAll(e.h.Path("peer-review", "junk"), 0o755)
	if len(e.s.List()) != 0 {
		t.Fatal("junk dir listed")
	}
}

func TestIDsAndRows(t *testing.T) {
	e := setup(t)
	if ValidID("p-20260101T000000Z-abcdef") != true || ValidID("p-2026-abc") || ValidID("../p-20260101T000000Z-abcdef") {
		t.Fatal("ValidID")
	}
	prdDir := filepath.Join(t.TempDir(), "docs", "prds")
	os.MkdirAll(prdDir, 0o755)
	prd := filepath.Join(prdDir, "a.md")
	os.WriteFile(prd, []byte("# A\n\n**Status:** In review · 2026\n"), 0o644)
	p := e.create(CreatePanel{Artifact: prd, Lenses: []string{"critical"}})
	rows := e.s.Rows()
	if len(rows) != 1 || rows[0].ID != p.ID || rows[0].PRDStatus != "In review" || rows[0].Total != 1 || rows[0].MaxRounds != 5 {
		t.Fatalf("%+v", rows)
	}
	if e.s.State(p.ID) != StRunning || e.s.State("p-nope") != "" {
		t.Fatal("State")
	}
	base := time.Now().Add(time.Minute)
	e.s.d.Now = func() time.Time { return base } // ids carry a second-resolution time
	p2 := e.create(CreatePanel{Lenses: []string{"qa"}})
	if l := e.s.List(); len(l) != 2 || l[0].ID != p2.ID {
		t.Fatalf("newest first: %+v", l)
	}
}

func TestOffers(t *testing.T) {
	e := setup(t)
	o := e.s.Offers()
	if o.MaxRounds != 5 || len(o.Default) != 1 || len(o.Kinds["custom"]) != 7 || len(o.Kinds["dump"]) != 3 {
		t.Fatalf("%+v", o)
	}
}

// ---- HTTP and CLI ----

func serve(e *env) http.Handler {
	mux := http.NewServeMux()
	for _, r := range Routes(RouteDeps{Svc: e.s}) {
		mux.Handle(r.Pattern, r.Handler)
	}
	return mux
}

func call(h http.Handler, method, path, body string) (int, map[string]any) {
	var rd *strings.Reader
	if body != "" {
		rd = strings.NewReader(body)
	} else {
		rd = strings.NewReader("")
	}
	req := httptest.NewRequest(method, path, rd)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var out map[string]any
	json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

var _ = server.Route{}

func TestRoutes(t *testing.T) {
	e := setup(t)
	h := serve(e)
	code, out := call(h, "POST", "/api/review", fmt.Sprintf(`{"repo":"acme/app","artifact":%q,"lenses":["critical"]}`, e.artifact))
	if code != 201 || out["state"] != "running" {
		t.Fatalf("%d %v", code, out)
	}
	id := out["id"].(string)
	if code, out = call(h, "GET", "/api/review/"+id, ""); code != 200 || out["id"] != id || out["max_rounds"] != float64(5) {
		t.Fatalf("%d %v", code, out)
	}
	if code, out = call(h, "GET", "/api/review", ""); code != 200 || len(out["panels"].([]any)) != 1 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out = call(h, "GET", "/api/review/offers", ""); code != 200 || out["max_rounds"] != float64(5) {
		t.Fatalf("%d %v", code, out)
	}
	if code, _ = call(h, "GET", "/api/review/p-nope", ""); code != 404 {
		t.Fatalf("404: %d", code)
	}
	if code, _ = call(h, "POST", "/api/review", `{"repo":"acme/app","artifact":"/nope","lenses":["critical"]}`); code != 400 {
		t.Fatalf("400: %d", code)
	}
	if code, _ = call(h, "POST", "/api/review/"+id+"/lens", `{"lens":"critical","action":"drop"}`); code != 409 {
		t.Fatalf("lens 409: %d", code)
	}
	if code, _ = call(h, "POST", "/api/review/"+id+"/lens", `{"lens":"zz","action":"drop"}`); code != 400 {
		t.Fatalf("lens 400: %d", code)
	}
	for body, want := range map[string]int{`{"add":2}`: 409, `{"add":0}`: 400, `{"add":true}`: 400, `{"add":1.5}`: 400, `{"add":"2"}`: 400, `{}`: 400} {
		if code, out = call(h, "POST", "/api/review/"+id+"/rounds", body); code != want {
			t.Errorf("rounds %s: %d %v", body, code, out)
		}
	}
	// settings
	if code, out = call(h, "GET", "/api/settings/review", ""); code != 200 || out["overridden"] != false {
		t.Fatalf("%d %v", code, out)
	}
	code, out = call(h, "PUT", "/api/settings/review", `{"max_rounds":3,"default_lenses":["qa"],"lenses":{}}`)
	if code != 200 || out["max_rounds"] != float64(3) || out["overridden"] != true {
		t.Fatalf("%d %v", code, out)
	}
	if e.get(id).MaxRounds != 3 {
		t.Fatal("new cap applies to existing panels")
	}
	if code, _ = call(h, "PUT", "/api/settings/review", `{"max_rounds":99,"default_lenses":["qa"],"lenses":{}}`); code != 400 {
		t.Fatalf("put 400: %d", code)
	}
	if code, out = call(h, "PUT", "/api/settings/review", `{"reset":true}`); code != 200 || out["overridden"] != false {
		t.Fatalf("%d %v", code, out)
	}
}

func TestCommandLenses(t *testing.T) {
	e := setup(t)
	var out, errb strings.Builder
	cmds := Commands()
	env := cli.Env{Stdout: &out, Stderr: &errb, Home: e.h}
	if rc := cmds[0].Run(context.Background(), env, []string{"lenses"}); rc != 0 {
		t.Fatalf("rc=%d %s", rc, errb.String())
	}
	var v struct {
		ReviewConfig
		Focus map[string]string `json:"focus"`
	}
	if err := json.Unmarshal([]byte(out.String()), &v); err != nil || v.MaxRounds != 5 || v.Lenses["critical"] == "" || v.Focus["critical"] == "" || !strings.HasSuffix(out.String(), "}\n") {
		t.Fatalf("%v %s", err, out.String())
	}
	if rc := cmds[0].Run(context.Background(), env, []string{"nope"}); rc != cli.ExitUsage {
		t.Fatalf("rc=%d", rc)
	}
}
