// Package wire builds the setu services and adapts the small interfaces each package defined for
// itself. cmd/setu/main.go calls Build; nothing here is business logic.
package wire

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/masnun-siam/setu/internal/away"
	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

// convert re-encodes v as T through JSON (the mirror types carry the API JSON names).
func convert[T any](v any) T {
	var out T
	b, err := json.Marshal(v)
	if err != nil {
		return out
	}
	_ = json.Unmarshal(b, &out)
	return out
}

func convertList[T any](v any) []T {
	out := convert[[]T](v)
	if out == nil {
		return []T{}
	}
	return out
}

// ---- sessions ----

// sessSettings adapts *settings.Store to sessions.Settings.
type sessSettings struct{ st *settings.Store }

func (s sessSettings) AccountCmd(label string) (string, bool) {
	a, ok := s.st.Account(label)
	return a.Cmd, ok
}
func (s sessSettings) DefaultCmd() string { return s.st.Default().Cmd }
func (s sessSettings) LabelFor(cmd string) string {
	for _, a := range s.st.Accounts() {
		if a.Cmd == cmd {
			return a.Label
		}
	}
	return ""
}
func (s sessSettings) CheckRun(model, effort string) error { return s.st.CheckRun(model, effort) }
func (s sessSettings) RunDefaults() (string, string) {
	g := s.st.Get()
	var m, e string
	if g.RunModel != nil {
		m = *g.RunModel
	}
	if g.RunEffort != nil {
		e = *g.RunEffort
	}
	return m, e
}
func (s sessSettings) VaultDir() string {
	if v := s.st.Get().VaultDir; v != nil {
		return *v
	}
	return ""
}
func (s sessSettings) IdleGuard() bool { return s.st.Get().IdleGuard }

// sessClaude adapts the claude package functions to sessions.Claude.
type sessClaude struct{}

func (sessClaude) Argv(cmd string) ([]string, error) { return claude.Argv(cmd) }
func (sessClaude) Preflight(ctx context.Context, cmd string, isDefault bool) error {
	return claude.Preflight(ctx, cmd, isDefault)
}
func (sessClaude) CopyTranscript(from, to, cwd, id string) error {
	return claude.CopyTranscript(from, to, cwd, id)
}

// sessPrompts adapts *prompts.Registry to sessions.Prompts.
type sessPrompts struct{ r *prompts.Registry }

func (p sessPrompts) Step(id string) (sessions.Step, bool) {
	s, ok := p.r.Step(id)
	return sessions.Step{ID: s.ID, Source: string(s.Source), Skill: s.Skill, RunsIn: string(s.RunsIn)}, ok
}
func (p sessPrompts) Build(stepID, args string) (sessions.Prompt, error) {
	x, err := p.r.Build(stepID, args)
	return sessions.Prompt{Step: x.Step, Display: x.Display, Text: x.Text}, err
}
func (p sessPrompts) Available(stepID string) error { return p.r.Available(stepID) }
func (p sessPrompts) Agent(name string) (string, []string, error) {
	return p.r.Agent(name)
}

// sessNotifier adapts *notify.Service to sessions.Notifier.
type sessNotifier struct{ n *notify.Service }

func (s sessNotifier) Notify(event string, n sessions.Note) {
	out := notify.Note{ID: n.ID, Repo: n.Repo, Command: n.Command, Text: n.Text, SessionID: n.SessionID,
		Question: n.Question, Recommended: n.Recommended, Error: n.Error, Step: n.Step}
	if n.Link != nil {
		out.Link = &notify.Link{Owner: n.Link.Owner, Repo: n.Link.Repo, Issue: n.Link.Issue}
	}
	s.n.Notify(event, out)
}

// ---- dispatch -> away.Lanes ----

// lanes implements away.Lanes over the dispatch store: stuck = a lane of a running or paused
// dispatch that is held or needs the owner for a reason other than a question.
type lanes struct{ d *dispatch.Service }

func (l lanes) Stuck() []away.StuckLane {
	var out []away.StuckLane
	for _, d := range l.d.List() {
		if !store.Live(d.State) {
			continue
		}
		for k, x := range d.Lanes {
			if !store.Active(x.Stage) || (x.Paused && x.PausedBy == "user") {
				continue
			}
			why := x.Held
			if why == "" {
				why = x.NeedsYou
			}
			if why == "" || strings.Contains(why, "waiting on you") || strings.Contains(why, "waits on you") {
				continue
			}
			out = append(out, away.StuckLane{Dispatch: d.ID, Lane: k, Issue: x.N, Repo: x.Repo, Why: why})
		}
	}
	return out
}

func (l lanes) Retry(id, lane string) error {
	_, err := l.d.LaneAction(id, lane, "retry", "")
	return err
}
