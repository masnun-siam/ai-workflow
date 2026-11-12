package review

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Sessions is what review needs from *sessions.Manager.
type Sessions interface {
	Launch(ctx context.Context, s sessions.Spec) (sessions.Record, error)
	Get(id string) (sessions.Record, error)
	Update(id string, fn func(*sessions.Record) error) (sessions.Record, error)
	Resume(ctx context.Context, id, text string) error
	Stop(ctx context.Context, id string) (sessions.Record, error)
	FinalText(id string) string
}

// Prompts is what review needs from *prompts.Registry.
type Prompts interface {
	Build(stepID, args string) (prompts.Prompt, error)
	Agent(name string) (body string, tools []string, err error)
}

// Notifier is satisfied by *notify.Service.
type Notifier interface {
	Notify(event string, n notify.Note)
}

// Deps wires a Service.
type Deps struct {
	Home     *home.Home
	Bus      *events.Bus
	Sessions Sessions
	Prompts  Prompts
	Notify   Notifier
	// Account returns the account command a repo's work ran under ("" = the default).
	Account func(repo string) string
	Now     func() time.Time
	// Tick is the panel tick interval (default 5 s).
	Tick time.Duration
}

// Service owns peer-review/.
type Service struct {
	d  Deps
	mu sync.Mutex // serialises every panel mutation in this process
}

// New returns a Service.
func New(d Deps) *Service { return &Service{d: d} }

// Panel is the API shape (API §4).
type Panel struct {
	ID          string            `json:"id"`
	Repo        string            `json:"repo"`
	Artifact    string            `json:"artifact"`
	Lenses      []string          `json:"lenses"`
	RootSession *string           `json:"root_session"`
	Round       int               `json:"round"`
	MaxRounds   int               `json:"max_rounds"`
	Dropped     []string          `json:"dropped"`
	Failed      []string          `json:"failed"`
	State       string            `json:"state"`
	Reason      *string           `json:"reason"`
	Phase       string            `json:"phase"`
	LensSession map[string]string `json:"lens_sessions"`
	Status      Status            `json:"status"`
}

// CreatePanel is POST /api/review.
type CreatePanel struct {
	Repo        string   `json:"repo"`
	Artifact    string   `json:"artifact"`
	Lenses      []string `json:"lenses"`
	RootSession string   `json:"root_session"`
	AfterRoot   bool     `json:"after_root"`
}

func (s *Service) config() Config { c, _ := LoadConfig(s.d.Home); return c }

func (s *Service) publish(id string) {
	if s.d.Bus != nil {
		s.d.Bus.Publish(events.TProducts, map[string]any{"kind": "review", "id": id})
	}
}

func (s *Service) view(p rec) Panel {
	cfg := s.config()
	nz := func(l []string) []string {
		if l == nil {
			return []string{}
		}
		return l
	}
	ls := p.LensSession
	if ls == nil {
		ls = map[string]string{}
	}
	return Panel{ID: p.ID, Repo: p.Repo, Artifact: p.Artifact, Lenses: nz(p.Lenses), RootSession: p.RootSession,
		Round: p.Round, MaxRounds: p.max(cfg), Dropped: nz(p.Dropped), Failed: nz(p.Failed), State: p.State,
		Reason: p.Reason, Phase: p.Phase, LensSession: ls, Status: s.status(p)}
}

// Offers is GET /api/review/offers.
func (s *Service) Offers() ReviewOffers { return s.config().Offers() }

// Get returns one panel.
func (s *Service) Get(id string) (Panel, error) {
	p, err := s.load(id)
	if err != nil {
		return Panel{}, err
	}
	return s.view(p), nil
}

// List returns every readable panel, newest first.
func (s *Service) List() []Panel {
	out := []Panel{}
	for _, id := range s.ids() {
		if p, err := s.load(id); err == nil {
			out = append(out, s.view(p))
		}
	}
	return out
}

// ids are the panel folder names, newest first (the id starts with its UTC time).
func (s *Service) ids() []string {
	ents, err := os.ReadDir(s.panelsDir())
	if err != nil {
		return nil
	}
	var ids []string
	for _, e := range ents {
		if e.IsDir() && ValidID(e.Name()) {
			ids = append(ids, e.Name())
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(ids)))
	return ids
}

// Row is the Inbox view of a panel (W§5.3 rows).
type Row struct {
	ID        string `json:"id"`
	Repo      string `json:"repo"`
	Artifact  string `json:"artifact"`
	State     string `json:"state"`
	Round     int    `json:"round"`
	MaxRounds int    `json:"max_rounds"`
	Approved  int    `json:"approved"`
	Total     int    `json:"total"`
	PRDStatus string `json:"prd_status,omitempty"`
}

var prdStatusRe = regexp.MustCompile(`\*\*Status:\*\*\s*([^·\n\r]+)`)

// Rows lists the panels for the Inbox; prd_status is read from the artifact when it lives under /docs/prds/.
func (s *Service) Rows() []Row {
	var rows []Row
	for _, p := range s.List() {
		r := Row{ID: p.ID, Repo: p.Repo, Artifact: p.Artifact, State: p.State, Round: p.Round,
			MaxRounds: p.MaxRounds, Approved: p.Status.Approved, Total: p.Status.Total}
		if strings.Contains(p.Artifact, "/docs/prds/") {
			if b, err := os.ReadFile(p.Artifact); err == nil {
				if m := prdStatusRe.FindSubmatch(b); m != nil {
					r.PRDStatus = strings.TrimSpace(string(m[1]))
				}
			}
		}
		rows = append(rows, r)
	}
	return rows
}

// State returns a panel's state for Session.panel ("" = unknown).
func (s *Service) State(id string) string {
	p, err := s.load(id)
	if err != nil {
		return ""
	}
	return p.State
}

// ---- starting sessions ----

var slugRe = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)

func (s *Service) account(p rec) string {
	if p.RootSession != nil {
		if r, err := s.d.Sessions.Get(*p.RootSession); err == nil && r.ClaudeCmd != "" {
			return r.ClaudeCmd
		}
	}
	if s.d.Account != nil {
		return s.d.Account(p.Repo)
	}
	return ""
}

func lensPrompt(cfg Config, p rec, lens string, revised bool) string {
	l := cfg.Lenses[lens]
	focus := l.Focus
	if focus == "" {
		focus = lens
	}
	rev := ""
	if revised {
		rev = " The artifact was revised since your last round: re-read it and re-review."
	}
	return fmt.Sprintf("Review the artifact at %s through the %s lens. This is round %d of panel %s.%s "+
		"You are read-only: edit nothing. Reply to the root only. Lens: %s. %s "+
		"Report at most 8 findings, most severe first, each citing the artifact line (or file:line) it is about; "+
		"a finding that needs a fact only the user has is a question, not a fix. "+
		"End your final message with a line `Verdict: approve` or `Verdict: changes`.",
		p.Artifact, lens, p.Round, p.ID, rev, focus, l.Prompt)
}

// startLens launches the lens's session and records it in the panel (caller saves).
func (s *Service) startLens(ctx context.Context, p *rec, lens string) error {
	cfg := s.config()
	if _, ok := cfg.Lenses[lens]; !ok {
		return errs.Invalid("unknown lens %q", lens)
	}
	_, tools, err := s.d.Prompts.Agent("peer-reviewer")
	if err != nil {
		return err
	}
	text := lensPrompt(cfg, *p, lens, p.Round > 1)
	r, err := s.d.Sessions.Launch(ctx, sessions.Spec{
		Prompt:       sessions.Prompt{Step: "peer-review", Display: "Peer review, " + lens + " lens: " + filepath.Base(p.Artifact), Text: text},
		Cwd:          p.Repo,
		Cmd:          s.account(*p),
		Agent:        "peer-reviewer",
		AllowedTools: tools,
		Model:        "opus",
		Kind:         "lens",
		Fields:       map[string]any{"panel": p.ID, "panel_role": "lens", "panel_lens": lens},
	})
	if r.ID != "" {
		p.LensSession[lens] = r.ID
	}
	return err
}

func (s *Service) startLenses(ctx context.Context, p *rec) error {
	for _, l := range p.active() {
		if err := s.startLens(ctx, p, l); err != nil {
			return err
		}
	}
	return nil
}

// Create opens a panel (POST /api/review).
func (s *Service) Create(ctx context.Context, c CreatePanel) (Panel, error) {
	ctx = context.WithoutCancel(ctx)
	if !slugRe.MatchString(c.Repo) && !filepath.IsAbs(c.Repo) {
		return Panel{}, errs.Invalid("repo must be a registered owner/name slug or an absolute checkout path")
	}
	if !filepath.IsAbs(c.Artifact) || strings.ContainsRune(c.Artifact, 0) {
		return Panel{}, errs.Invalid("artifact must be an absolute path")
	}
	if fi, err := os.Stat(c.Artifact); err != nil || !fi.Mode().IsRegular() {
		return Panel{}, errs.Invalid("artifact is not an existing file: %s", c.Artifact)
	}
	cfg := s.config()
	lenses, err := cfg.CheckLenses("custom", c.Lenses)
	if err != nil {
		return Panel{}, err
	}
	var root *string
	if c.RootSession != "" {
		if _, err := s.d.Sessions.Get(c.RootSession); err != nil {
			return Panel{}, errs.Invalid("root session %s not found", c.RootSession)
		}
		r := c.RootSession
		root = &r
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	id, err := s.newPanelID()
	if err != nil {
		return Panel{}, err
	}
	p := rec{ID: id, Repo: c.Repo, Artifact: c.Artifact, Lenses: lenses, RootSession: root, Round: 1,
		State: StRunning, Phase: PhLenses, LensSession: map[string]string{}}
	if err := s.save(p); err != nil {
		return Panel{}, err
	}
	fail := func(err error) (Panel, error) {
		s.failPanel(ctx, &p, "could not start: "+err.Error())
		_ = s.save(p)
		s.publish(id)
		return Panel{}, err
	}
	if root == nil {
		pr, err := s.d.Prompts.Build("peer-review", "--root "+id+" "+c.Artifact)
		if err != nil {
			return fail(err)
		}
		r, err := s.d.Sessions.Launch(ctx, sessions.Spec{
			Prompt: sessions.Prompt{Step: pr.Step, Display: pr.Display, Text: pr.Text}, Cwd: c.Repo,
			Cmd: s.account(p), Gate: true, Kind: "panel-root",
			Fields: map[string]any{"panel": id, "panel_role": "root"},
		})
		if r.ID != "" {
			rid := r.ID
			p.RootSession = &rid
		}
		if err != nil {
			return fail(err)
		}
	} else if _, err := s.d.Sessions.Update(*root, func(r *sessions.Record) error {
		r.Panel, r.PanelRole = id, "root"
		return nil
	}); err != nil {
		return fail(err)
	}
	if c.AfterRoot {
		p.Phase = PhWaitRoot
	} else if err := s.startLenses(ctx, &p); err != nil {
		return fail(err)
	}
	if err := s.save(p); err != nil {
		return Panel{}, err
	}
	s.publish(id)
	return s.view(p), nil
}

// failPanel stops busy lens sessions and marks the panel failed (caller saves).
func (s *Service) failPanel(ctx context.Context, p *rec, reason string) {
	for _, sid := range p.LensSession {
		if r, err := s.d.Sessions.Get(sid); err == nil && r.Status.Live() {
			_, _ = s.d.Sessions.Stop(ctx, sid)
		}
	}
	p.State, p.Phase = StFailed, PhDone
	p.setReason(reason)
}

// ---- the tick ----

// Start runs the panel tick (every 5 s) until ctx ends. It returns at once.
func (s *Service) Start(ctx context.Context) {
	every := s.d.Tick
	if every <= 0 {
		every = 5 * time.Second
	}
	go func() {
		t := time.NewTicker(every)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				func() {
					defer func() {
						if r := recover(); r != nil {
							log.Printf("review: tick panic: %v", r)
						}
					}()
					s.Tick(ctx)
				}()
			}
		}
	}()
}

func (s *Service) sessState(id string) (st sessions.Status, held, gone bool) {
	r, err := s.d.Sessions.Get(id)
	if err != nil {
		return "", false, true
	}
	return r.Status, r.Hold, false
}

func busy(st sessions.Status, held bool) bool {
	return st.Live() || held
}

// Tick advances every running panel once.
func (s *Service) Tick(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, id := range s.ids() {
		_, _ = home.BackupIfCorrupt(s.panelPath(id))
		p, err := s.load(id)
		if err != nil || p.State != StRunning {
			continue
		}
		before := p
		before.Failed = append([]string(nil), p.Failed...)
		if err := s.tickPanel(ctx, &p); err != nil {
			s.failPanel(ctx, &p, "tick failed: "+err.Error())
		}
		if err := s.save(p); err != nil {
			log.Printf("review: save %s: %v", id, err)
			continue
		}
		s.publish(id)
	}
}

func (s *Service) tickPanel(ctx context.Context, p *rec) error {
	if fi, err := os.Stat(p.Artifact); err != nil || !fi.Mode().IsRegular() {
		s.failPanel(ctx, p, "artifact deleted")
		return nil
	}
	var rootSt sessions.Status
	var rootHeld, rootGone bool
	if p.RootSession != nil {
		rootSt, rootHeld, rootGone = s.sessState(*p.RootSession)
		if p.Phase == PhWaitRoot || p.Phase == PhRoot || p.Phase == PhLenses {
			switch {
			case rootGone:
				s.failPanel(ctx, p, "root session gone")
				return nil
			case rootSt == sessions.StFailed || rootSt == sessions.StStopped:
				s.failPanel(ctx, p, "root session "+string(rootSt))
				return nil
			}
		}
	}
	cfg := s.config()
	switch p.Phase {
	case PhWaitRoot:
		if rootSt == sessions.StDone {
			p.Phase = PhLenses
			return s.startLenses(ctx, p)
		}
	case PhRoot:
		if rootSt != sessions.StDone {
			return nil
		}
		for _, l := range p.active() {
			if sid, ok := p.LensSession[l]; ok {
				if st, held, gone := s.sessState(sid); !gone && st == sessions.StDone && held {
					return nil // a held lens: the round starts for all lenses together
				}
			}
		}
		p.Phase = PhLenses
		for _, l := range p.active() {
			if contains(p.Failed, l) {
				continue
			}
			sid, ok := p.LensSession[l]
			if !ok {
				p.markFailed(l)
				continue
			}
			if err := s.d.Sessions.Resume(ctx, sid, lensPrompt(cfg, *p, l, true)); err != nil {
				p.markFailed(l)
			}
		}
	case PhLenses:
		for _, l := range p.active() {
			if contains(p.Failed, l) || s.verdictOf(*p, p.Round, l) != "" {
				continue
			}
			sid, ok := p.LensSession[l]
			if !ok {
				p.markFailed(l)
				continue
			}
			st, _, gone := s.sessState(sid)
			switch {
			case gone || st == sessions.StFailed || st == sessions.StStopped:
				p.markFailed(l)
			case st == sessions.StDone:
				if err := s.recordVerdict(p, l, s.d.Sessions.FinalText(sid)); err != nil {
					return err
				}
			}
		}
		if p.RootSession != nil && busy(rootSt, rootHeld) {
			return nil // verdicts stay on disk until the root is idle
		}
		switch s.advance(p, cfg) {
		case advNext:
			p.Phase = PhRoot
			if p.RootSession == nil {
				p.State, p.Phase = StFailed, PhDone
				p.setReason("no root session to revise the artifact")
				return nil
			}
			if err := s.d.Sessions.Resume(ctx, *p.RootSession, s.rootMessage(*p)); err != nil {
				s.failPanel(ctx, p, "could not resume the root: "+err.Error())
			}
		case advCap:
			s.capNote(*p)
		}
	}
	return nil
}

func (s *Service) capNote(p rec) {
	if s.d.Notify != nil {
		s.d.Notify.Notify("panel-cap", notify.Note{ID: p.ID, Repo: p.Repo, Text: filepath.Base(p.Artifact) + ": round cap reached"})
	}
}

// rootMessage relays the previous round's verdicts (p.Round is already the next round).
func (s *Service) rootMessage(p rec) string {
	prev := p.Round - 1
	var b strings.Builder
	fmt.Fprintf(&b, "Peer-review panel %s, round %d verdicts on %s:", p.ID, prev, p.Artifact)
	for _, l := range p.active() {
		body := "(no verdict)"
		if raw, err := os.ReadFile(s.roundFile(p.ID, prev, l)); err == nil {
			body = string(raw)
		}
		fmt.Fprintf(&b, "\n--- %s ---\n%s", l, body)
	}
	fmt.Fprintf(&b, "\nNow revise the artifact in place to address these findings, then end your turn. "+
		"The panel asks the same lenses to re-review as round %d.", p.Round)
	return b.String()
}

// ---- user actions ----

// LensAction reruns or drops a failed lens.
func (s *Service) LensAction(id, lens, action string) (Panel, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, err := s.load(id)
	if err != nil {
		return Panel{}, err
	}
	if !contains(p.Lenses, lens) {
		return Panel{}, errs.Invalid("unknown lens %q", lens)
	}
	if action != "rerun" && action != "drop" {
		return Panel{}, errs.Invalid("action must be rerun or drop")
	}
	if p.State != StRunning || !contains(p.Failed, lens) {
		return Panel{}, errs.Conflict("lens "+lens+" has not failed", map[string]any{"id": id})
	}
	switch action {
	case "drop":
		p.dropLens(lens)
	case "rerun":
		if err := s.startLens(context.Background(), &p, lens); err != nil {
			return Panel{}, errs.Conflict("could not restart: "+err.Error(), map[string]any{"id": id})
		}
		p.unfail(lens)
	}
	if err := s.save(p); err != nil {
		return Panel{}, err
	}
	s.publish(id)
	return s.view(p), nil
}

// AddRounds raises the cap of a panel that hit it and sends the root back to work.
func (s *Service) AddRounds(id string, add int) (Panel, error) {
	if add < 1 || add > 5 {
		return Panel{}, errs.Invalid("add must be an integer from 1 to 5")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	p, err := s.load(id)
	if err != nil {
		return Panel{}, err
	}
	if p.State != StCap {
		return Panel{}, errs.Conflict("panel has not hit its round cap", map[string]any{"id": id})
	}
	if p.RootSession == nil {
		return Panel{}, errs.Conflict("panel has no root session", map[string]any{"id": id})
	}
	st, held, gone := s.sessState(*p.RootSession)
	if gone || busy(st, held) {
		return Panel{}, errs.Conflict("the root session is not idle", map[string]any{"id": id})
	}
	old := p
	cfg := s.config()
	mr := p.max(cfg) + add
	p.MaxRounds = &mr
	p.Round++
	p.State, p.Reason, p.Phase = StRunning, nil, PhRoot
	if err := s.d.Sessions.Resume(context.Background(), *p.RootSession, s.rootMessage(p)); err != nil {
		_ = s.save(old) // restore max_rounds, round, state, phase
		return Panel{}, errs.Conflict("could not resume the root: "+err.Error(), map[string]any{"id": id})
	}
	if err := s.save(p); err != nil {
		return Panel{}, err
	}
	s.publish(id)
	return s.view(p), nil
}

var (
	_ Sessions = (*sessions.Manager)(nil)
	_ Prompts  = (*prompts.Registry)(nil)
	_ Notifier = (*notify.Service)(nil)
)
