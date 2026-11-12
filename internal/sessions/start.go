package sessions

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
)

const (
	maxPromptChars = 32000
	batchMaxUI     = 3
	recentSeconds  = 30
)

var (
	batchRe     = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)
	slugRe      = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	issueURLRe  = regexp.MustCompile(`github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/(\d+)`)
	argIssueRe  = regexp.MustCompile(`^(?:#?(\d+)|https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(?:issues|pull)/(\d+)\S*)$`)
	vaultDirRe  = regexp.MustCompile(`^05-Work/[^/\x00]+(?:/[^/\x00]+)?$`)
	needsRemote = map[string]bool{"create-tasks": true, "refine-issues": true, "implement-issue": true, "pr-grind": true, "pr-review": true, "release-pr": true}
)

func noNUL(s string) bool { return !strings.ContainsRune(s, 0) }

func expandHome(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if h, err := os.UserHomeDir(); err == nil {
			return filepath.Join(h, strings.TrimPrefix(p, "~"))
		}
	}
	return p
}

func isDir(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.IsDir()
}

// StartSession is the HTTP start path: S§5.2-5.4 with a step in place of a command, plus the
// D1 guards.
func (m *Manager) StartSession(ctx context.Context, req StartRequest) (Record, error) {
	ctx = context.WithoutCancel(ctx)
	if (req.Step == "") == (strings.TrimSpace(req.Text) == "") {
		return Record{}, errs.Invalid("exactly one of step or text is required")
	}
	if req.Issue < 0 {
		return Record{}, errs.Invalid("issue must be a positive integer")
	}
	if !noNUL(req.Repo) || !noNUL(req.Args) || !noNUL(req.Text) || !noNUL(req.Product) {
		return Record{}, errs.Invalid("fields must not contain NUL")
	}
	if req.Batch != "" && !batchRe.MatchString(req.Batch) {
		return Record{}, errs.Invalid("batch must match [A-Za-z0-9_-]{1,64}")
	}
	if req.NoRepo && req.Step != "" {
		return Record{}, errs.Invalid("no_repo is only for custom text")
	}

	var step Step
	var prompt Prompt
	if req.Step != "" {
		if m.d.Prompts == nil {
			return Record{}, errs.Invalid("unknown step %q", req.Step)
		}
		st, ok := m.d.Prompts.Step(req.Step)
		if !ok {
			return Record{}, errs.Invalid("unknown step %q", req.Step)
		}
		step = st
		if err := m.d.Prompts.Available(req.Step); err != nil {
			return Record{}, err
		}
		p, err := m.d.Prompts.Build(req.Step, req.Args)
		if err != nil {
			return Record{}, err
		}
		prompt = p
		if len([]rune(prompt.Display)) > maxPromptChars {
			return Record{}, errs.Invalid("prompt is longer than %d characters", maxPromptChars)
		}
	} else {
		if strings.HasPrefix(strings.TrimLeft(req.Text, " \t\r\n"), "-") {
			return Record{}, errs.Invalid("text must not start with '-' (claude would parse it as a flag)")
		}
		if len([]rune(req.Text)) > maxPromptChars {
			return Record{}, errs.Invalid("prompt is longer than %d characters", maxPromptChars)
		}
		prompt = Prompt{Display: req.Text, Text: req.Text}
	}

	// account and run settings
	cmd := ""
	if req.Account != "" {
		c, ok := "", false
		if m.d.Settings != nil {
			c, ok = m.d.Settings.AccountCmd(req.Account)
		}
		if !ok {
			return Record{}, errs.Invalid("account must be a label saved in Settings")
		}
		cmd = c
	}
	model, effort := req.Model, req.Effort
	if m.d.Settings != nil {
		if err := m.d.Settings.CheckRun(model, effort); err != nil {
			return Record{}, err
		}
		dm, de := m.d.Settings.RunDefaults()
		if model == "" {
			model = dm
		}
		if effort == "" {
			effort = de
		}
	}

	// where it runs
	var cwd, slug string
	vaultFolder := ""
	switch {
	case req.NoRepo:
		if req.VaultFolder != "" {
			if !vaultDirRe.MatchString(req.VaultFolder) {
				return Record{}, errs.Invalid("vault_folder must look like 05-Work/<Project>[/<Feature>]")
			}
			vaultFolder = req.VaultFolder
		}
		dir := m.vaultDir()
		if dir == "" {
			return Record{}, errs.Invalid("the vault directory does not exist: set vault_dir in Settings")
		}
		cwd = dir
		if vaultFolder != "" {
			hint := "\n\nSave notes under " + filepath.Join(dir, vaultFolder) + "."
			prompt.Display += hint
			prompt.Text += hint
		}
	case req.Step != "" && step.RunsIn == "none":
		cwd = m.vaultDir()
		if cwd == "" {
			cwd, _ = os.UserHomeDir()
		}
	default:
		base := req.Repo
		if base == "" && step.RunsIn == "docs" {
			base = req.Product
		}
		if base == "" {
			return Record{}, errs.Invalid("repo is required")
		}
		if m.d.Repos == nil {
			return Record{}, errs.Invalid("no repository registry")
		}
		// an issue URL in the prompt overrides the picked repo when that repo is registered
		if step.RunsIn != "docs" {
			if mm := issueURLRe.FindStringSubmatch(prompt.Display); mm != nil {
				if p, s, err := m.d.Repos.Resolve(ctx, mm[1]+"/"+mm[2]); err == nil && p != "" {
					cwd, slug = p, s
				}
			}
		}
		if cwd == "" {
			p, s, err := m.d.Repos.Resolve(ctx, base)
			if err != nil {
				return Record{}, err
			}
			cwd, slug = p, s
			if step.RunsIn == "docs" {
				dp, ds, err := m.d.Repos.DocsRepo(ctx, p)
				if err != nil {
					return Record{}, err
				}
				if dp2, ds2, err := m.d.Repos.Resolve(ctx, dp); err == nil && dp2 != "" {
					dp, ds = dp2, ds2
				}
				cwd, slug = dp, ds
			}
		}
		if slug == "" {
			slug = m.d.Repos.SlugOf(cwd)
		}
		if strings.HasPrefix(slug, "local/") && needsRemote[req.Step] {
			return Record{}, errs.Invalid("%s has no GitHub remote yet: add one (git remote add origin …), then run %s", slug, req.Step)
		}
	}

	// the issue this run is about
	issue := req.Issue
	var linkOwner, linkRepo string
	if issue == 0 && (req.Step == "implement-issue" || req.Step == "pr-grind") {
		first := strings.Fields(req.Args)
		if len(first) > 0 {
			if mm := argIssueRe.FindStringSubmatch(first[0]); mm != nil {
				if mm[1] != "" {
					issue, _ = strconv.Atoi(mm[1])
				} else {
					issue, _ = strconv.Atoi(mm[4])
					linkOwner, linkRepo = mm[2], mm[3]
				}
			}
		}
	}
	var link *Link
	if issue > 0 {
		if linkOwner != "" && strings.EqualFold(linkOwner+"/"+linkRepo, slug) {
			link = &Link{Owner: linkOwner, Repo: linkRepo, Issue: issue}
		} else if o, r, ok := strings.Cut(slug, "/"); ok {
			link = &Link{Owner: o, Repo: r, Issue: issue}
		}
	}

	// guards and launch, serialized so two identical starts cannot both pass
	m.startMu.Lock()
	defer m.startMu.Unlock()
	always := req.Step == "implement-issue" || req.Step == "pr-grind"
	if (req.Guard || always) && link != nil {
		if id, ok := m.liveSameRun(req.Step, slug, issue); ok {
			return Record{}, errs.Conflict(fmt.Sprintf("%s already running for %s#%d (session %s)", req.Step, slug, issue, id),
				map[string]any{"id": id, "link": link, "href": "/api/sessions/" + id})
		}
	}
	key := strings.Join([]string{req.Step, req.Args, strings.ToLower(slug), req.Text}, "\x00")
	if req.Guard {
		for _, g := range m.d.Guards {
			if err := g(ctx, req, step, slug, issue); err != nil {
				return Record{}, err
			}
		}
		if r, ok := m.recent[key]; ok && m.d.now().Sub(r.at) < recentSeconds*time.Second {
			return Record{}, errs.Conflict(fmt.Sprintf("just started (session %s)", r.id), map[string]any{"id": r.id, "href": "/api/sessions/" + r.id})
		}
	}

	fields := map[string]any{}
	if req.NoRepo {
		fields["no_repo"] = true
		if vaultFolder != "" {
			fields["vault_folder"] = vaultFolder
		}
	}
	if req.PinAccount {
		fields["pin_account"] = true
	}
	spec := Spec{
		Prompt: prompt, Args: req.Args, Cwd: cwd, Link: link, Cmd: cmd, Gate: true,
		RunModel: model, RunEffort: effort, Batch: req.Batch, BatchMax: batchMaxUI,
		Fields: fields, Request: req,
	}
	if req.Batch == "" {
		spec.BatchMax = 0
	}
	rec, err := m.Launch(ctx, spec)
	if err != nil {
		return rec, err
	}
	m.recent[key] = recentStart{at: m.d.now(), id: rec.ID}
	for k, v := range m.recent {
		if m.d.now().Sub(v.at) > 5*time.Minute {
			delete(m.recent, k)
		}
	}
	if len(req.Lenses) > 0 && m.d.AfterStart != nil {
		if err := m.d.AfterStart(ctx, rec, req); err != nil {
			_, _ = m.Stop(ctx, rec.ID)
			return rec, err
		}
	}
	return rec, nil
}

func (m *Manager) vaultDir() string {
	if m.d.Settings == nil {
		return ""
	}
	d := expandHome(m.d.Settings.VaultDir())
	if d != "" && isDir(d) {
		return d
	}
	return ""
}

// liveSameRun finds a live session of the same step, issue and repo whose process group is alive.
func (m *Manager) liveSameRun(step, slug string, issue int) (string, bool) {
	for _, r := range m.listAll() {
		if r.Link == nil || r.Link.Issue != issue || m.stepOf(r) != step || !strings.EqualFold(m.slugOf(r), slug) {
			continue
		}
		switch r.Status {
		case StStarting:
			return r.ID, true
		case StRunning, StWaiting:
			if m.Alive(r.ID) || (r.PID > 0 && syscall.Kill(-r.PID, 0) == nil) {
				return r.ID, true
			}
		}
	}
	return "", false
}

// legacyRequest reads a stored replay body of either generation.
type legacyRequest struct {
	StartRequest
	Command   string   `json:"command"`
	ClaudeCmd string   `json:"claude_cmd"`
	Peer      []string `json:"peer_review"`
}

// Rerun replays the stored start body through StartSession (guards apply again).
func (m *Manager) Rerun(ctx context.Context, id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	var lr legacyRequest
	if len(rec.Request) > 0 {
		_ = json.Unmarshal(rec.Request, &lr)
	}
	req := lr.StartRequest
	if len(rec.Request) > 0 && (req.Step != "" || req.Text != "") {
		// new format
	} else if lr.Command != "" && len(rec.Request) > 0 {
		if m.d.Prompts != nil {
			if _, ok := m.d.Prompts.Step(lr.Command); ok {
				req.Step = lr.Command
			}
		}
		if req.Step == "" {
			req.Text = lr.Command
		}
	} else if rec.Command != "" {
		req = StartRequest{Text: rec.Command, NoRepo: rec.NoRepo}
		if step := m.stepOf(rec); step != "" {
			_, rest, _ := parseCommand(rec.Command)
			req = StartRequest{Step: step, Args: strings.TrimSpace(rest)}
		}
		req.Repo = rec.Repo
		if rec.Link != nil {
			req.Issue = rec.Link.Issue
		}
	} else {
		return rec, errs.Invalid("nothing to rerun: the session has no stored request or command")
	}
	if len(lr.Lenses) == 0 && len(lr.Peer) > 0 {
		req.Lenses = lr.Peer
	}
	if lr.ClaudeCmd != "" && req.Account == "" && m.d.Settings != nil {
		req.Account = m.d.Settings.LabelFor(lr.ClaudeCmd)
	}
	if req.Account == "" && m.d.Settings != nil {
		req.Account = m.d.Settings.LabelFor(rec.ClaudeCmd)
	}
	req.Guard = false
	return m.StartSession(ctx, req)
}
