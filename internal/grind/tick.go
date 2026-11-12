package grind

import (
	"context"
	"os"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Tick outcomes (W§6.2).
const (
	OutInvalid  = "invalid"
	OutBusy     = "busy"
	OutLocked   = "locked"
	OutError    = "error"
	OutIdle     = "idle"
	OutDispatch = "dispatch"
	OutQueued   = "queued"
	OutStarted  = "started"
	OutClosed   = "closed"
)

const tickTimeout = 120 * time.Second

// Tick is one pass of the re-entry timer over every state file that has a `next-poll:` header. It
// returns the outcome per "owner/repo#n" (for tests and logs).
func (s *Service) Tick(ctx context.Context) map[string]string {
	s.tickMu.Lock()
	defer s.tickMu.Unlock()
	out := map[string]string{}
	ix := s.sessionIndex()
	for _, e := range s.entries() {
		if e.Doc.Get("next-poll") == "" || e.Doc.Get("paused") != "" || e.Doc.Get("done") != "" {
			continue
		}
		if ctx.Err() != nil {
			break
		}
		res := s.tickOne(ctx, e, &ix)
		out[e.Key.Slug()+"#"+itoa(e.Key.N)] = res
		if res == OutStarted || res == OutClosed || res == OutDispatch {
			s.changed(e.Key.Slug())
		}
	}
	return out
}

func (s *Service) tickOne(ctx context.Context, e entry, ix *sessionIndex) string {
	k := e.Key
	if g := ix.by[keyID(k)]; g != nil && g.Live != "" {
		return OutBusy
	}
	lock, ok, err := home.TryLock(strings.TrimSuffix(e.Path, ".md"))
	if err != nil {
		s.warn("%s#%d: lock: %v", k.Slug(), k.N, err)
		return OutError
	}
	if !ok {
		return OutLocked
	}
	defer lock.Close()
	d, err := s.files().Read(k) // re-read under the lock
	if err != nil {
		return OutError
	}
	if d.Get("next-poll") == "" || d.Get("paused") != "" || d.Get("done") != "" {
		return OutIdle
	}
	if s.d.GH == nil {
		return OutError
	}
	cctx, cancel := context.WithTimeout(ctx, tickTimeout)
	defer cancel()
	info, err := viewPR(cctx, s.d.GH, k)
	if err != nil {
		s.warn("%s#%d: %v", k.Slug(), k.N, err)
		return OutError
	}
	now := s.now()
	if info.State == "MERGED" || info.State == "CLOSED" {
		_ = s.files().Update(k, now, func(d *Doc) error {
			d.Set("done", stamp(now)+" - "+strings.ToLower(info.State))
			return nil
		})
		return OutClosed
	}

	due := true
	if np, ok := ParseTime(d.Get("next-poll")); ok {
		due = !np.After(now)
	}
	trigger := due
	ref := gh.PRRef{Owner: k.Owner, Repo: k.Repo, N: k.N}
	if !due {
		review, err := s.reviewTrigger(cctx, k, d, now)
		if err != nil {
			s.warn("%s#%d: reviews: %v", k.Slug(), k.N, err)
			return OutError
		}
		trigger = review
	}
	// the CI snapshot is compared on a quiet tick and refreshed on a start, so a due start does not
	// leave a stale `ci-seen:` that would trigger a second session right after
	if ci := gh.CISnapshot(cctx, s.d.GH, ref); ci.State != gh.CIError {
		now2 := ci.HeadSHA + " " + ci.State
		seen := d.Get("ci-seen")
		if seen != now2 {
			_ = s.files().Update(k, now, func(d *Doc) error { d.Set("ci-seen", now2); return nil })
			if seen != "" && !due {
				trigger = true
			}
		}
	}
	if !trigger {
		return OutIdle
	}

	if s.d.Lanes != nil {
		if _, owned := s.d.Lanes.ActiveLane(k.Slug(), 0, k.N); owned {
			_ = s.files().Update(k, now, func(d *Doc) error {
				d.Set("dispatch-due", stamp(now))
				d.Set("next-poll", stamp(now.Add(Heartbeat)))
				return nil
			})
			return OutDispatch
		}
	}
	g := ix.by[keyID(k)]
	cwd, cmd := "", ""
	if g != nil {
		cwd, cmd = g.Cwd, g.Cmd
	}
	if cwd == "" && s.d.Sessions != nil {
		for _, r := range s.d.Sessions.List(sessions.Filter{Repo: k.Slug()}) {
			if r.CwdPath != "" {
				cwd = r.CwdPath
				break
			}
		}
	}
	if cwd == "" && s.d.Products != nil {
		if p, _, err := s.d.Products.Resolve(ctx, k.Slug()); err == nil {
			cwd = p
		}
	}
	if cwd == "" {
		s.warn("%s#%d: no checkout to run the re-entry in", k.Slug(), k.N)
		return OutInvalid
	}
	if ix.liveSess >= MaxGrinds {
		return OutQueued
	}
	arg := d.Get("thread")
	if !threadRE.MatchString(arg) {
		arg = k.URL()
	}
	pr, err := s.d.Prompts.BuildIn("pr-grind", arg, k.Slug())
	if err != nil {
		s.warn("%s#%d: %v", k.Slug(), k.N, err)
		return OutInvalid
	}
	rec, err := s.d.Sessions.Launch(ctx, sessions.Spec{
		Prompt: sessions.Prompt(pr), Args: arg, Cwd: cwd, Cmd: cmd, Gate: true, Kind: "grind",
		Link:         &sessions.Link{Owner: k.Owner, Repo: k.Repo, Issue: k.N},
		Instructions: []string{prompts.Reentry},
		Env:          []string{"SETU_HEADLESS=1", "AIW_HEADLESS=1"},
		ExtraFiles:   []*os.File{lock},
	})
	if err != nil {
		s.warn("%s#%d: start: %v", k.Slug(), k.N, err)
		return OutError
	}
	ix.liveSess++
	ix.by[keyID(k)] = &grindSessions{Key: k, Live: rec.ID, Latest: rec.ID, Cwd: cwd, Cmd: cmd}
	_ = s.files().Update(k, now, func(d *Doc) error { d.Set("next-poll", stamp(now.Add(Heartbeat))); return nil })
	return OutStarted
}

// reviewTrigger reports whether a review landed after `poll-since:`, and moves `poll-since:`. With
// no `poll-since:` yet it only sets it to now. The reviewers are the `reviewers:` list (or
// `reviewer:`); with `reviewer: UNRESOLVED` anyone but the author counts.
func (s *Service) reviewTrigger(ctx context.Context, k Key, d *Doc, now time.Time) (bool, error) {
	since := d.Get("poll-since")
	if since == "" {
		return false, s.files().Update(k, now, func(d *Doc) error { d.Set("poll-since", stamp(now)); return nil })
	}
	reviews, err := pages[Review](ctx, s.d.GH, "repos/"+k.Slug()+"/pulls/"+itoa(k.N)+"/reviews")
	if err != nil {
		return false, err
	}
	var who []string
	notAuthor := false
	if r := d.Get("reviewer"); r == "" || strings.EqualFold(r, "UNRESOLVED") {
		notAuthor = true
	} else {
		who = splitList(d.Get("reviewers"))
		if len(who) == 0 {
			who = []string{r}
		}
	}
	author := d.Get("author")
	sinceT, okSince := ParseTime(since)
	var newest time.Time
	var newestS string
	for _, r := range reviews {
		l := login(r.User)
		if l == "" || r.SubmittedAt == "" {
			continue
		}
		if notAuthor {
			if strings.EqualFold(l, author) {
				continue
			}
		} else if !inSet(who, l) {
			continue
		}
		t, ok := ParseTime(r.SubmittedAt)
		if !ok || (okSince && !t.After(sinceT)) {
			continue
		}
		if t.After(newest) {
			newest, newestS = t, r.SubmittedAt
		}
	}
	if newestS == "" {
		return false, nil
	}
	return true, s.files().Update(k, now, func(d *Doc) error { d.Set("poll-since", newestS); return nil })
}
