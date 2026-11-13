package sessions

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

// TestMain lets the test binary stand in for `setu` (fake claude rules exec it to run `setu ask`).
func TestMain(m *testing.M) {
	if os.Getenv("SESSIONS_TEST_AS_SETU") == "1" {
		os.Exit(cli.Main(Commands(), os.Args[1:]))
	}
	os.Exit(m.Run())
}

type fakeSettings struct {
	accounts map[string]string // label -> cmd
	vault    string
}

func (f *fakeSettings) AccountCmd(label string) (string, bool) {
	if label == "claude" {
		return "claude", true
	}
	c, ok := f.accounts[label]
	return c, ok
}
func (f *fakeSettings) DefaultCmd() string { return "claude" }
func (f *fakeSettings) LabelFor(cmd string) string {
	if cmd == "claude" {
		return "claude"
	}
	for l, c := range f.accounts {
		if c == cmd {
			return l
		}
	}
	return ""
}
func (f *fakeSettings) CheckRun(model, effort string) error {
	if model != "" && model != "opus" && model != "sonnet" && model != "haiku" {
		return errs.Invalid("model must be one of opus, sonnet, haiku")
	}
	return nil
}
func (f *fakeSettings) RunDefaults() (string, string) { return "", "" }
func (f *fakeSettings) VaultDir() string              { return f.vault }

type fakeClaude struct {
	mu           sync.Mutex
	preflights   []string
	transcripts  [][4]string
	preflightErr error
}

func (c *fakeClaude) Argv(cmd string) ([]string, error) {
	fields := strings.Fields(cmd)
	p, err := exec.LookPath(fields[0])
	if err != nil {
		return nil, err
	}
	return append([]string{p}, fields[1:]...), nil
}
func (c *fakeClaude) Preflight(ctx context.Context, cmd string, isDefault bool) error {
	c.mu.Lock()
	c.preflights = append(c.preflights, cmd)
	err := c.preflightErr
	c.mu.Unlock()
	if err != nil {
		return err
	}
	argv, err := c.Argv(cmd)
	if err != nil {
		return err
	}
	r := execx.Run(ctx, append(argv, "auth", "status", "--json"), execx.Opts{Timeout: 10 * time.Second})
	var out struct {
		LoggedIn bool `json:"loggedIn"`
	}
	if json.Unmarshal(r.Stdout, &out) != nil || !out.LoggedIn {
		return errors.New("claude CLI is not logged in, run `claude auth login`")
	}
	return nil
}
func (c *fakeClaude) CopyTranscript(from, to, cwd, sid string) error {
	c.mu.Lock()
	c.transcripts = append(c.transcripts, [4]string{from, to, cwd, sid})
	c.mu.Unlock()
	return nil
}

type fakePrompts struct{}

var fakeSteps = map[string]Step{
	"implement-issue":     {ID: "implement-issue", Source: "blubird", Skill: "implement-issue", RunsIn: "issue"},
	"refine-issues":       {ID: "refine-issues", Source: "blubird", Skill: "refine-issues", RunsIn: "issue"},
	"create-prd":          {ID: "create-prd", Source: "blubird", Skill: "create-prd", RunsIn: "docs"},
	"pr-grind":            {ID: "pr-grind", Source: "setu", Skill: "pr-grind", RunsIn: "issue"},
	"release-note":        {ID: "release-note", Source: "setu", Skill: "release-note", RunsIn: "none"},
	"small-change":        {ID: "small-change", Source: "blubird", Skill: "create-tasks", RunsIn: "repo"},
	"report-bug":          {ID: "report-bug", Source: "blubird", Skill: "reproduce-bug", RunsIn: "repo"},
	"after-merge":         {ID: "after-merge", Source: "blubird", Skill: "implement-issue", RunsIn: "issue"},
	"project-coordinator": {ID: "project-coordinator", Source: "blubird", Skill: "project-coordinator", RunsIn: "docs"},
}

func (fakePrompts) Step(id string) (Step, bool) { s, ok := fakeSteps[id]; return s, ok }
func (fakePrompts) Build(id, args string) (Prompt, error) {
	s, ok := fakeSteps[id]
	if !ok {
		return Prompt{}, errs.Invalid("unknown step %q", id)
	}
	if strings.ContainsRune(args, 0) {
		return Prompt{}, errs.Invalid("bad args")
	}
	if s.Source == "blubird" {
		t := strings.TrimSpace("/blubird:" + s.Skill + " " + args)
		return Prompt{Step: id, Display: t, Text: t}, nil
	}
	return Prompt{Step: id, Display: strings.TrimSpace("/" + s.Skill + " " + args), Text: "SETU " + s.Skill + "\n\nARGUMENTS: " + args}, nil
}
func (fakePrompts) Available(id string) error { return nil }
func (fakePrompts) Agent(name string) (string, []string, error) {
	switch name {
	case "away-answerer":
		return "AWAYBODY", []string{"Read", "Bash(git status:*)"}, nil
	}
	return "", nil, errors.New("no agent " + name)
}

type fakeRepos struct{ slugs map[string]string } // slug -> dir

func (f *fakeRepos) Resolve(ctx context.Context, repo string) (string, string, error) {
	if p, ok := f.slugs[repo]; ok {
		return p, repo, nil
	}
	for s, p := range f.slugs {
		if p == repo {
			return p, s, nil
		}
	}
	if filepath.IsAbs(repo) && isDir(repo) {
		return repo, "", nil
	}
	return "", "", errs.Invalid("%s is not a registered repository", repo)
}
func (f *fakeRepos) DocsRepo(ctx context.Context, cwd string) (string, string, error) {
	if s := f.SlugOf(cwd); s != "" {
		return cwd, s, nil
	}
	return "", "", errs.Invalid("no docs repo")
}
func (f *fakeRepos) SlugOf(path string) string {
	for s, p := range f.slugs {
		if p == path {
			return s
		}
	}
	return ""
}

type noteLog struct {
	mu    sync.Mutex
	items []struct {
		Event string
		Note  Note
	}
}

func (n *noteLog) Notify(event string, note Note) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.items = append(n.items, struct {
		Event string
		Note  Note
	}{event, note})
}
func (n *noteLog) count(event string) int {
	n.mu.Lock()
	defer n.mu.Unlock()
	c := 0
	for _, i := range n.items {
		if i.Event == event {
			c++
		}
	}
	return c
}

type tenv struct {
	t        *testing.T
	h        *home.Home
	m        *Manager
	fb       string
	repo     string // /tmp/.../repo (slug acme/app)
	docs     string
	bus      *events.Bus
	notes    *noteLog
	claude   *fakeClaude
	settings *fakeSettings
	rules    []fakebin.Rule
}

func newEnv(t *testing.T) *tenv {
	t.Helper()
	root := t.TempDir()
	t.Setenv("HOME", filepath.Join(root, "home"))
	os.MkdirAll(filepath.Join(root, "home"), 0o755)
	t.Setenv("SETU_HOME", filepath.Join(root, "setuhome"))
	t.Setenv("CLAUDE_PLUGIN_DATA", "/should/not/leak")
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	fb := filepath.Join(root, "fb")
	fakebin.Install(t, fb)
	repo := filepath.Join(root, "repo")
	docs := filepath.Join(root, "docs")
	os.MkdirAll(repo, 0o755)
	os.MkdirAll(docs, 0o755)
	e := &tenv{t: t, h: h, fb: fb, repo: repo, docs: docs, bus: events.New(), notes: &noteLog{}, claude: &fakeClaude{},
		settings: &fakeSettings{accounts: map[string]string{"work": "claude work"}, vault: filepath.Join(root, "vault")}}
	os.MkdirAll(e.settings.vault, 0o755)
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "auth status --json", Stdout: `{"loggedIn":true}`})
	e.m = New(Deps{Home: h, Bus: e.bus, Settings: e.settings, Claude: e.claude, Prompts: fakePrompts{},
		Repos: &fakeRepos{slugs: map[string]string{"acme/app": repo, "acme/docs": docs}}, Notify: e.notes, BinDir: fb})
	e.m.poll = 20 * time.Millisecond
	// runs before the TempDir removal: no follower or child may still write into the home
	t.Cleanup(func() {
		deadline := time.Now().Add(15 * time.Second)
		for _, r := range e.m.List(Filter{Answerers: true}) {
			for e.m.Alive(r.ID) && time.Now().Before(deadline) {
				time.Sleep(10 * time.Millisecond)
			}
		}
	})
	return e
}

// stream writes a fixture file into the fakebin dir and returns its name.
func (e *tenv) file(name, body string) string {
	e.t.Helper()
	if err := os.WriteFile(filepath.Join(e.fb, name), []byte(body), 0o644); err != nil {
		e.t.Fatal(err)
	}
	return name
}

func (e *tenv) addRule(r fakebin.Rule) {
	e.rules = append(e.rules, r)
	fakebin.WriteRules(e.t, e.fb, e.rules)
}

// claudeRule makes `claude --print …` (not resume) print a stream file.
func (e *tenv) claudeRule(contains string, file string, exit int) {
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: contains, StdoutFile: file, Exit: exit})
}

func (e *tenv) calls() []fakebin.Call { return fakebin.Calls(e.t, e.fb) }

func (e *tenv) lastClaude() fakebin.Call {
	cs := e.claudeCalls()
	if len(cs) == 0 {
		return fakebin.Call{}
	}
	return cs[len(cs)-1]
}

// claudeCalls are the runs (not auth checks); Args start at --print, after any account prefix.
func (e *tenv) claudeCalls() []fakebin.Call {
	var out []fakebin.Call
	for _, c := range e.calls() {
		if c.Bin != "claude" {
			continue
		}
		for i, a := range c.Args {
			if a == "--print" {
				c.Args = c.Args[i:]
				out = append(out, c)
				break
			}
		}
	}
	return out
}

func (e *tenv) wait(id string, pred func(Record) bool) Record {
	e.t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	var rec Record
	for time.Now().Before(deadline) {
		rec, _ = e.m.Get(id)
		if pred(rec) {
			return rec
		}
		time.Sleep(10 * time.Millisecond)
	}
	e.t.Fatalf("timeout waiting on %s: status=%s error=%q note=%q", id, rec.Status, rec.Error, rec.Note)
	return rec
}

func (e *tenv) status(id string, s Status) Record {
	e.t.Helper()
	return e.wait(id, func(r Record) bool { return r.Status == s })
}

// settled waits until the follower has finished with the session (no tracked process).
func (e *tenv) settled(id string) {
	e.t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if !e.m.Alive(id) {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	e.t.Fatalf("follower of %s did not finish", id)
}

func jl(objs ...any) string {
	var b strings.Builder
	for _, o := range objs {
		x, _ := json.Marshal(o)
		b.Write(x)
		b.WriteByte('\n')
	}
	return b.String()
}

type obj = map[string]any

func initEv(sid string) obj {
	return obj{"type": "system", "subtype": "init", "session_id": sid, "model": "claude-opus-5-5"}
}
func textEv(t string) obj {
	return obj{"type": "assistant", "message": obj{"content": []any{obj{"type": "text", "text": t}}}}
}
func toolEv(name string, in obj) obj {
	return obj{"type": "assistant", "message": obj{"content": []any{obj{"type": "tool_use", "name": name, "input": in}}}}
}
func resultEv(cost float64, in, out int, extra obj) obj {
	r := obj{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": cost, "result": "all done",
		"usage": obj{"input_tokens": in, "output_tokens": out}}
	for k, v := range extra {
		r[k] = v
	}
	return r
}

func okStream(sid string, cost float64, in, out int) string {
	return jl(initEv(sid), textEv("hello"), resultEv(cost, in, out, nil))
}

func (e *tenv) req(step, args string) StartRequest {
	return StartRequest{Step: step, Args: args, Repo: "acme/app"}
}

func mustNoErr(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func kind(err error) string {
	switch errs.KindOf(err) {
	case errs.KInvalid:
		return "invalid"
	case errs.KNotFound:
		return "notfound"
	case errs.KConflict:
		return "conflict"
	case errs.KUpstream:
		return "upstream"
	}
	if err == nil {
		return "nil"
	}
	return fmt.Sprintf("other(%v)", err)
}

func exec_ps(pid string) bool {
	r := execx.Run(context.Background(), []string{"ps", "-p", pid, "-o", "stat="}, execx.Opts{})
	s := strings.TrimSpace(string(r.Stdout))
	return r.Code == 0 && s != "" && !strings.HasPrefix(s, "Z")
}

func fmtInt(n int) string { return fmt.Sprint(n) }
