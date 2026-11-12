package grind

import (
	"context"
	"fmt"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/sessions"
)

// SkipCIText is what skip-ci tells the paused grind's session.
func skipCIText(pr int) string {
	return fmt.Sprintf("Human decision on the paused grind (PR #%d): Skip CI for now, complete the grind, then come back and fix the CI", pr)
}

// StartGrind starts a pr-grind session for the PR through the sessions manager. It refuses a PR
// that a dispatch lane owns or that is not an open, ready PR (409), and a repo with nobody to ask
// (400). A live grind session for the PR gives the sessions manager's 409. by names the caller
// ("ui", "release", "autostart") for the log.
func (s *Service) StartGrind(ctx context.Context, repo string, pr int, by string) (sessions.Record, error) {
	k, err := keyOf(repo, pr)
	if err != nil {
		return sessions.Record{}, err
	}
	if s.d.Sessions == nil || s.d.Prompts == nil {
		return sessions.Record{}, errs.Upstream("grind is not available")
	}
	s.startMu.Lock()
	defer s.startMu.Unlock()
	if s.d.Lanes != nil {
		if id, owned := s.d.Lanes.ActiveLane(k.Slug(), 0, pr); owned {
			return sessions.Record{}, errs.Conflict("a dispatch lane owns this PR", map[string]any{"id": id, "href": "/api/dispatches/" + id})
		}
	}
	rv, err := s.skipReason(k.Slug())
	if err != nil {
		return sessions.Record{}, err
	}
	if s.d.GH != nil {
		info, err := viewPR(ctx, s.d.GH, k)
		if err != nil {
			return sessions.Record{}, errs.Upstream("cannot read %s: %v", k.URL(), err)
		}
		if info.State != "OPEN" {
			return sessions.Record{}, errs.Conflict(fmt.Sprintf("PR #%d is %s; nothing to grind", pr, strings.ToLower(info.State)), nil)
		}
		if info.IsDraft {
			return sessions.Record{}, errs.Conflict(fmt.Sprintf("PR #%d is a draft; mark it ready for review before grinding", pr), nil)
		}
	}
	args := k.URL()
	if rv.Channel != nil && rv.Path != nil && *rv.Path == "slack" {
		args += " --channel " + *rv.Channel
	}
	_ = by
	rec, err := s.d.Sessions.StartSession(ctx, sessions.StartRequest{Step: "pr-grind", Args: args, Repo: k.Slug(), Guard: true})
	if err != nil {
		return rec, err
	}
	s.changed(k.Slug())
	return rec, nil
}

// skipReason is the resolver for the repo; a skip becomes a 400.
func (s *Service) skipReason(slug string) (Reviewers, error) {
	rv, err := ResolvePR(s.d.Home, s.d.Settings, "https://github.com/"+slug+"/pull/1", false)
	if err != nil {
		return rv, errs.Upstream("%v", err)
	}
	if rv.Skip != nil {
		return rv, errs.Invalid("%s", *rv.Skip)
	}
	return rv, nil // an unknown repo has no answer and no skip: the session's CLI decides
}

// grindOn is whether a PR of repo, closing refs, should be grinded automatically: the per-issue
// switch of the first ref that has one overrides the repo's auto_grind.
func (s *Service) grindOn(repo string, refs []int) bool {
	for _, n := range refs {
		if on, set := s.d.Settings.IssueGrind(repo, n); set {
			return on
		}
	}
	return s.d.Settings.Get().Repo(repo).AutoGrind
}

// OnFresh is the poller hook: a PR that was a draft in the previous snapshot and is ready now
// starts a grind (W§6.3). Stale data, a first sight, a PR with a state file, a switch that is off,
// a dispatch-owned PR and a resolver skip all start nothing. The start runs in the background so the
// poller never waits on a session.
func (s *Service) OnFresh(repo string, snap poller.Snapshot, prev poller.Data) {
	for _, pr := range s.turnedReady(repo, snap, prev) {
		pr := pr
		go func() {
			if err := s.autostart(context.Background(), repo, pr); err != nil && errs.KindOf(err) != errs.KConflict {
				s.warn("autostart %s#%d: %v", repo, pr.N, err)
			}
		}()
	}
}

func (s *Service) turnedReady(repo string, snap poller.Snapshot, prev poller.Data) []poller.OpenPR {
	if !snap.Fresh() {
		return nil
	}
	wasDraft := map[int]bool{}
	for _, p := range prev.OpenPRs {
		if p.Draft {
			wasDraft[p.N] = true
		}
	}
	var out []poller.OpenPR
	for _, p := range snap.Data.OpenPRs {
		if !p.Draft && wasDraft[p.N] {
			out = append(out, p)
		}
	}
	return out
}

func (s *Service) autostart(ctx context.Context, repo string, pr poller.OpenPR) error {
	k, err := keyOf(repo, pr.N)
	if err != nil {
		return err
	}
	if s.files().Exists(k) || !s.grindOn(repo, pr.Refs) {
		return nil
	}
	if s.d.Lanes != nil {
		issue := 0
		if len(pr.Refs) > 0 {
			issue = pr.Refs[0]
		}
		if _, owned := s.d.Lanes.ActiveLane(repo, issue, pr.N); owned {
			return nil
		}
	}
	_, err = s.StartGrind(ctx, repo, pr.N, "autostart")
	return err
}

// SetIssue stores the per-issue grind switch. Turning it on starts a grind for the issue's ready
// open PR when it has no loop yet; turning it off stops a loop that is not done.
func (s *Service) SetIssue(ctx context.Context, repo string, issue int, on bool) error {
	if !slugRE.MatchString(repo) {
		return errs.Invalid("repo must be owner/name")
	}
	if issue < 1 {
		return errs.Invalid("issue must be a positive number")
	}
	if err := s.d.Settings.SetIssueGrind(repo, issue, on); err != nil {
		return err
	}
	if s.d.Poller == nil {
		return nil
	}
	data := s.d.Poller.Snapshot(repo).Data
	var prs []poller.OpenPR
	for _, p := range data.OpenPRs {
		for _, r := range p.Refs {
			if r == issue {
				prs = append(prs, p)
			}
		}
	}
	for _, p := range prs {
		k, err := keyOf(repo, p.N)
		if err != nil {
			continue
		}
		if on {
			if p.Draft || s.files().Exists(k) {
				continue
			}
			if _, err := s.StartGrind(ctx, repo, p.N, "issue-switch"); err != nil {
				switch errs.KindOf(err) {
				case errs.KConflict:
				case errs.KInvalid:
					return err
				default:
					return errs.Upstream("%v", err)
				}
			}
			continue
		}
		if st, ok := s.Get(repo, p.N); ok && st.State != StDone && st.State != StApproved {
			if err := s.Stop(repo, p.N); err != nil {
				return err
			}
		}
	}
	return nil
}

// SkipCI answers a paused grind with "skip CI for now": the loop must be paused and not done, and
// a finished grind session must exist to reply to. The `paused:` line is removed after the prompt
// is sent.
func (s *Service) SkipCI(ctx context.Context, repo string, pr int) error {
	k, err := keyOf(repo, pr)
	if err != nil {
		return err
	}
	d, err := s.files().Read(k)
	if err != nil || d.Get("paused") == "" || d.Get("done") != "" {
		return errs.Conflict("this grind is not paused", nil)
	}
	g := s.sessionIndex().by[keyID(k)]
	if g == nil || g.Finished == nil {
		return errs.Conflict("no finished grind session to reply to", nil)
	}
	if _, err := s.d.Sessions.SendPrompt(ctx, g.Finished.ID, skipCIText(pr), 0); err != nil {
		return err
	}
	if err := s.files().Update(k, s.now(), func(d *Doc) error { d.Del("paused"); return nil }); err != nil {
		return errs.Upstream("cannot update the state: %v", err)
	}
	s.changed(k.Slug())
	return nil
}

// Stop ends a loop from the UI: `done: <ISO> - stopped from the UI`, unless it is already done.
// The PR stays open.
func (s *Service) Stop(repo string, pr int) error {
	k, err := keyOf(repo, pr)
	if err != nil {
		return err
	}
	if !s.files().Exists(k) {
		return errs.NotFound("no grind for %s#%d", repo, pr)
	}
	now := s.now()
	if err := s.files().Update(k, now, func(d *Doc) error {
		if d.Get("done") == "" {
			d.Set("done", stamp(now)+" - stopped from the UI")
		}
		return nil
	}); err != nil {
		return errs.Upstream("cannot update the state: %v", err)
	}
	s.changed(k.Slug())
	return nil
}
