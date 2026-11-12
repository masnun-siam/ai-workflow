package dispatch

import (
	"context"
	"errors"
	"fmt"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/sessions"
)

// target is what a session is started for: a lane, or an end action's QA / grind session.
type target struct {
	Repo  string
	N     int
	Label string // the Session.dispatch.lane value; "" = the lane key
}

func (t target) label() string {
	if t.Label != "" {
		return t.Label
	}
	return store.Key(t.Repo, t.N)
}

// render turns a Msg into the step, display and text a session gets.
func (s *Service) render(m Msg, repo string) (step, display, text string, err error) {
	if m.Step == "" {
		return "", m.Plain, m.Plain, nil
	}
	if s.d.Prompts == nil {
		return "", "", "", errs.Upstream("no prompt registry")
	}
	p, err := s.d.Prompts.BuildIn(m.Step, m.Args, repo)
	if err != nil {
		return "", "", "", err
	}
	return m.Step, p.Display + m.Suffix, p.Text + m.Suffix, nil
}

func (s *Service) accountCmd(d *store.Dispatch) string {
	if d.Settings.Account != nil && s.d.Accounts != nil {
		if a, ok := s.d.Accounts.Account(*d.Settings.Account); ok {
			return a.Cmd
		}
	}
	return ""
}

// startSession launches a headless session for the lane (permissions are skipped by the session
// runner; the dispatch's model and effort go through as the direct flags).
func (s *Service) startSession(ctx context.Context, d *store.Dispatch, t target, m Msg) (*store.Handle, error) {
	if s.d.Sessions == nil {
		return nil, errs.Upstream("no session manager")
	}
	step, display, text, err := s.render(m, t.Repo)
	if err != nil {
		return nil, err
	}
	o, n := splitSlug(t.Repo)
	rec, err := s.d.Sessions.Launch(ctx, sessions.Spec{
		Prompt: sessions.Prompt{Step: step, Display: display, Text: text},
		Args:   m.Args,
		Cwd:    t.Repo,
		Link:   &sessions.Link{Owner: o, Repo: n, Issue: t.N},
		Cmd:    s.accountCmd(d),
		Gate:   true,
		Model:  store.Str(d.Settings.Model),
		Effort: store.Str(d.Settings.Effort),
		Kind:   "lane",
		Fields: map[string]any{"dispatch": d.ID, "lane": t.label()},
	})
	if err != nil {
		return nil, err
	}
	return &store.Handle{Session: rec.ID}, nil
}

// sendSession prompts a lane session: a held one stores the text for its Resume, a finished one
// is resumed, a running one queues it.
func (s *Service) sendSession(ctx context.Context, h *store.Handle, text string) error {
	rec, err := s.d.Sessions.Get(h.Session)
	if err != nil {
		return err
	}
	if rec.Hold && rec.Status != sessions.StStopped {
		_, err := s.d.Sessions.Update(h.Session, func(r *sessions.Record) error { r.QueuedPrompt = text; return nil })
		return err
	}
	_, err = s.d.Sessions.SendPrompt(ctx, h.Session, text, sendLimit)
	return err
}

// closeSession stops the session; one whose record is gone has nothing left to stop.
func (s *Service) closeSession(ctx context.Context, h *store.Handle) error {
	_, err := s.d.Sessions.Stop(ctx, h.Session)
	if err != nil && errs.KindOf(err) == errs.KNotFound {
		return nil
	}
	var e *errs.Error
	if errors.As(err, &e) && e.Kind == errs.KNotFound {
		return nil
	}
	return err
}

// agentOf maps a session record to the lane agent state (W§2.8).
func agentOf(rec sessions.Record) string {
	if rec.Hold && rec.Status != sessions.StStopped {
		return "working"
	}
	switch rec.Status {
	case sessions.StLimited, sessions.StStarting, sessions.StRunning, sessions.StQueued:
		return "working" // limited: the session runner resumes it at the reset by itself
	case sessions.StWaiting:
		return "blocked"
	case sessions.StDone, sessions.StStopped:
		return "idle"
	case sessions.StFailed:
		return "gone"
	}
	return "working"
}

// agentStatus is the runner's view of the lane session; an unreachable store reads as "unknown".
func (s *Service) agentStatus(h *store.Handle) string {
	if s.d.Sessions == nil {
		return "unknown"
	}
	rec, err := s.d.Sessions.Get(h.Session)
	if err != nil {
		if errs.KindOf(err) == errs.KNotFound {
			return "gone"
		}
		logf("status of %s: %v", h.Session, err)
		return "unknown"
	}
	return agentOf(rec)
}

func errText(err error) string { return fmt.Sprint(err) }
