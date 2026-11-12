package release

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/sessions"
)

const (
	tickEvery    = 10 * time.Second
	viewEvery    = 30 * time.Second
	maxNoteBytes = 64 << 10
)

// Start runs the flow tick until ctx ends. A panic in a tick is logged, never fatal.
func (s *Service) Start(ctx context.Context) {
	go func() {
		t := time.NewTicker(tickEvery)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				s.safeTick(ctx, false)
			}
		}
	}()
}

func (s *Service) safeTick(ctx context.Context, force bool) {
	defer func() {
		if p := recover(); p != nil {
			fmt.Fprintf(os.Stderr, "release: tick panic: %v\n", p)
		}
	}()
	s.tick(ctx, force)
}

// Tick advances every open release once (the poller's fresh hook may call it too).
func (s *Service) Tick(ctx context.Context) { s.safeTick(ctx, false) }

func (s *Service) tick(ctx context.Context, force bool) {
	for _, r := range s.records() {
		if open(r.Stage) {
			s.advance(ctx, r.ID, force)
		}
	}
}

func (s *Service) advance(ctx context.Context, id string, force bool) {
	r, err := s.load(id)
	if err != nil {
		return
	}
	switch r.Stage {
	case StCut:
		s.advanceCut(r)
	case StGrind, StMerge:
		s.advanceGrind(ctx, r, force)
	case StNotify:
		s.advanceNotify(r)
	}
}

func (s *Service) advanceCut(r record) {
	if r.CutSess == nil {
		return
	}
	rec, err := s.d.Sessions.Get(*r.CutSess)
	if err != nil || !rec.Status.Terminal() {
		return
	}
	if rec.Status != sessions.StDone {
		msg := rec.Error
		if msg == "" {
			msg = "the release-pr session " + string(rec.Status)
		}
		s.fail(r.ID, msg)
		return
	}
	res, ok := ParseResult(s.d.Sessions.FinalText(rec.ID))
	if !ok {
		s.fail(r.ID, "release-pr finished without a SETU-RELEASE line")
		return
	}
	switch {
	case res.PR == nil && res.DryRun != "":
		s.mutate(r.ID, func(x *record) error {
			if x.Stage != StCut {
				return errs.Conflict("moved on", nil)
			}
			x.Stage, x.DryRunDir = StDryRun, sp(res.DryRun)
			return nil
		})
	case res.PR == nil:
		reason := res.Reason
		if reason == "" {
			reason = "release-pr stopped before opening a PR"
		}
		s.fail(r.ID, reason)
	default:
		n, ok := PRNumber(*res.PR)
		if !ok {
			s.fail(r.ID, "release-pr reported a bad PR url: "+*res.PR)
			return
		}
		s.mutate(r.ID, func(x *record) error {
			if x.Stage != StCut {
				return errs.Conflict("moved on", nil)
			}
			x.Stage, x.PR, x.PRURL, x.Thread = StGrind, &n, res.PR, res.Thread
			return nil
		})
	}
}

// prState asks whether the release PR is merged: the poller's list first, else `gh pr view`
// (at most every 30 s per release). state is MERGED, CLOSED, OPEN, or "" when unknown.
func (s *Service) prState(ctx context.Context, r record, force bool) (state, mergedAt string) {
	if r.PR == nil {
		return "", ""
	}
	if s.d.Merged != nil {
		if at, ok := s.d.Merged(r.Repo, *r.PR); ok {
			return "MERGED", at
		}
	}
	if !force {
		if v, ok := s.viewAt.Load(r.ID); ok && s.now().Sub(v.(time.Time)) < viewEvery {
			return "", ""
		}
	}
	s.viewAt.Store(r.ID, s.now())
	var out struct {
		State    string `json:"state"`
		MergedAt string `json:"mergedAt"`
	}
	if _, err := s.d.GH.JSON(ctx, []string{"pr", "view", fmt.Sprint(*r.PR), "--repo", r.Repo, "--json", "state,mergedAt"}, 30*time.Second, &out); err != nil {
		return "", ""
	}
	return strings.ToUpper(out.State), out.MergedAt
}

func (s *Service) advanceGrind(ctx context.Context, r record, force bool) {
	switch state, at := s.prState(ctx, r, force); state {
	case "MERGED":
		s.merged(ctx, r.ID, at)
		return
	case "CLOSED":
		s.mutate(r.ID, func(x *record) error {
			if !open(x.Stage) || x.Stage == StNotify {
				return errs.Conflict("moved on", nil)
			}
			x.Stage, x.Error = StFailed, sp("the release PR was closed without merging")
			return nil
		})
		return
	}
	if r.Stage != StGrind || r.PR == nil || s.d.Grind == nil {
		return
	}
	if g, ok := s.d.Grind.Get(r.Repo, *r.PR); ok && (g.State == "approved" || g.State == "done") {
		s.mutate(r.ID, func(x *record) error {
			if x.Stage != StGrind {
				return errs.Conflict("moved on", nil)
			}
			x.Stage = StMerge
			return nil
		})
	}
}

// merged moves a release to notify and starts the note draft, once.
func (s *Service) merged(ctx context.Context, id, at string) {
	if at == "" {
		at = ts(s.now())
	}
	moved := false
	r, err := s.mutate(id, func(x *record) error {
		if x.Stage != StGrind && x.Stage != StMerge {
			return errs.Conflict("moved on", nil)
		}
		x.Stage, x.MergedAt, x.Error = StNotify, sp(at), nil
		moved = true
		return nil
	})
	if err != nil || !moved {
		return
	}
	if s.d.Notify != nil {
		s.d.Notify.Notify("release", notify.Note{ID: "release-" + r.ID, Repo: r.Repo, Step: "release",
			Text: fmt.Sprintf("%s release PR #%d is merged: the release note is next", r.Repo, deref(r.PR))})
	}
	if _, err := s.startDraft(ctx, r.ID); err != nil {
		_, _ = s.mutate(r.ID, func(x *record) error { x.Error = sp("release note draft did not start: " + err.Error()); return nil })
	}
}

func deref(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

func (s *Service) advanceNotify(r record) {
	if r.NoteSess == nil || r.DraftNotified || r.PostAttemptedAt != "" {
		return
	}
	rec, err := s.d.Sessions.Get(*r.NoteSess)
	if err != nil || !rec.Status.Terminal() {
		return
	}
	_, statErr := os.Stat(s.noteFile(r.ID))
	var msg *string
	switch {
	case rec.Status != sessions.StDone:
		m := rec.Error
		if m == "" {
			m = "the release-note session " + string(rec.Status)
		}
		msg = sp("release note draft failed: " + m)
	case statErr != nil:
		msg = sp("the release-note session finished without writing the note")
	}
	_, _ = s.mutate(r.ID, func(x *record) error {
		if x.DraftNotified || x.NoteSess == nil || *x.NoteSess != *r.NoteSess {
			return errs.Conflict("moved on", nil)
		}
		x.DraftNotified = true
		if msg != nil {
			x.Error = msg
		}
		return nil
	})
	if s.d.Notify != nil {
		n := notify.Note{ID: "release-note-" + r.ID, Repo: r.Repo, Step: "release-note", Text: r.Repo + " release note draft is ready to review"}
		if msg != nil {
			n.Text, n.Error = *msg, *msg
		}
		s.d.Notify.Notify("release", n)
	}
}

// ---- grind ----

// Grind starts a pr-grind session for the release PR unless one is live.
func (s *Service) Grind(ctx context.Context, id string) (Release, error) {
	r, err := s.load(id)
	if err != nil {
		return Release{}, err
	}
	if (r.Stage != StGrind && r.Stage != StMerge) || r.PR == nil {
		return Release{}, errs.Conflict("the release has no open PR to grind (stage "+r.Stage+")", nil)
	}
	if s.d.Grind == nil {
		return Release{}, errs.Upstream("grind is not available")
	}
	if g, ok := s.d.Grind.Get(r.Repo, *r.PR); ok && g.State == "running" {
		return s.Public(r), nil
	}
	if _, err := s.d.Grind.StartGrind(ctx, r.Repo, *r.PR, "release"); err != nil {
		return Release{}, err
	}
	s.changed(r.Repo)
	return s.Get(id)
}

// ---- skip ----

// Skip abandons a release that is still open.
func (s *Service) Skip(id string) (Release, error) {
	var stop string
	r, err := s.mutate(id, func(x *record) error {
		if !open(x.Stage) {
			return errs.Conflict("the release is already "+x.Stage, nil)
		}
		if x.PostAttemptedAt != "" {
			return errs.Conflict("the release note post is in progress or was attempted", nil)
		}
		if x.Stage == StCut && x.CutSess != nil {
			stop = *x.CutSess
		}
		x.Stage = StSkipped
		return nil
	})
	if err != nil {
		return Release{}, err
	}
	if stop != "" {
		_, _ = s.d.Sessions.Stop(context.Background(), stop)
	}
	return s.Public(r), nil
}
