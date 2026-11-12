package grind

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/sessions"
)

// grindKeyOf is the PR a pr-grind session works on: the PR URL in its args or command, else its link.
func grindKeyOf(r sessions.Record) (Key, bool) {
	for _, t := range []string{r.Args, r.Command} {
		if m := reURLRepo.FindStringSubmatch(t); m != nil && ValidName(m[1]) && ValidName(m[2]) {
			return Key{m[1], m[2], atoi(m[3])}, true
		}
	}
	if r.Link != nil && r.Link.Issue > 0 && ValidName(r.Link.Owner) && ValidName(r.Link.Repo) {
		return Key{r.Link.Owner, r.Link.Repo, r.Link.Issue}, true
	}
	return Key{}, false
}

func keyID(k Key) string { return strings.ToLower(k.Slug()) + "#" + itoa(k.N) }

// grindSessions summarises the pr-grind sessions of one key.
type grindSessions struct {
	Key      Key
	Live     string // newest live session id
	LiveAt   string // its started_at
	Latest   string // newest session id of any status
	Finished *sessions.Record
	Cwd      string // cwd of the newest session that has one
	Cmd      string // account command of the newest session
}

type sessionIndex struct {
	by       map[string]*grindSessions
	liveSess int
}

// sessionIndex scans the pr-grind sessions (newest first) once.
func (s *Service) sessionIndex() sessionIndex {
	ix := sessionIndex{by: map[string]*grindSessions{}}
	if s.d.Sessions == nil {
		return ix
	}
	for _, r := range s.d.Sessions.List(sessions.Filter{Step: "pr-grind"}) {
		if r.Role != "" { // away answerers and panel roles are never grinds
			continue
		}
		k, ok := grindKeyOf(r)
		if !ok {
			continue
		}
		if r.Status.Live() {
			ix.liveSess++
		}
		g := ix.by[keyID(k)]
		if g == nil {
			g = &grindSessions{Key: k}
			ix.by[keyID(k)] = g
		}
		if g.Latest == "" {
			g.Latest, g.Cmd = r.ID, r.ClaudeCmd
		}
		if g.Cwd == "" && r.CwdPath != "" {
			g.Cwd = r.CwdPath
		}
		if r.Status.Live() && g.Live == "" {
			g.Live, g.LiveAt = r.ID, r.StartedAt
		}
		if r.Status.Terminal() && r.SessionID != "" && g.Finished == nil {
			rr := r
			g.Finished = &rr
		}
	}
	return ix
}

func splitSlug(slug string) (owner, repo string, ok bool) {
	o, r, found := strings.Cut(slug, "/")
	if !found || !ValidName(o) || !ValidName(r) {
		return "", "", false
	}
	return o, r, true
}

func keyOf(slug string, pr int) (Key, error) {
	o, r, ok := splitSlug(slug)
	if !ok || pr < 1 {
		return Key{}, errs.Invalid("repo must be owner/name and pr a positive number")
	}
	return Key{o, r, pr}, nil
}

func (s *Service) fallbackMode() string { return settingsMode(s.d.Settings) }

// decorate turns the offline status into the served one: a live session makes a loop running, an
// active loop without one is idle, and the dispatch lane that owns the PR decides the mode.
func (s *Service) decorate(st Status, k Key, ix sessionIndex) Status {
	g := ix.by[keyID(k)]
	if g != nil {
		st.Session = strp(g.Live)
		if g.Live == "" {
			st.Session = strp(g.Latest)
		}
	}
	live := g != nil && g.Live != ""
	switch st.State {
	case StRunning:
		if !live {
			st.State = StIdle
		}
	case StDone, StApproved:
		// a session started after the loop ended is a restart that has not cleared `done:` yet
		if live && startedAfter(g.LiveAt, s.doneAt(k)) {
			st.State, st.Reason = StRunning, nil
		}
	case StNone:
		if live {
			st.State = StRunning
		}
	}
	if s.d.Lanes != nil {
		if m, ok := s.d.Lanes.GrindMode(k.URL()); ok && ModeOf(m) != "" {
			st.Mode = strp(ModeOf(m))
		}
	} else if m, ok := DispatchMode(s.d.Home, k.Slug(), k.N); ok {
		st.Mode = strp(m)
	}
	return st
}

func (s *Service) doneAt(k Key) string {
	d, err := s.files().Read(k)
	if err != nil {
		return ""
	}
	return d.Get("done")
}

func startedAfter(started, done string) bool {
	a, ok1 := ParseTime(started)
	b, ok2 := ParseTime(done)
	if len(done) >= 20 {
		b, ok2 = ParseTime(done[:20])
	}
	return ok1 && ok2 && a.After(b)
}

// Index lists every grind: the valid state files with their served state, plus live pr-grind
// sessions that have no state file yet (running, round 0). Sorted by repo then PR.
func (s *Service) Index() []Status {
	ix := s.sessionIndex()
	have := map[string]bool{}
	out := []Status{}
	for _, st := range Index(s.files(), s.fallbackMode()) {
		o, r, ok := splitSlug(st.Repo)
		if !ok {
			continue
		}
		k := Key{o, r, st.PR}
		have[keyID(k)] = true
		out = append(out, s.decorate(st, k, ix))
	}
	for id, g := range ix.by {
		if have[id] || g.Live == "" {
			continue
		}
		out = append(out, s.decorate(Status{Repo: g.Key.Slug(), PR: g.Key.N, State: StNone}, g.Key, ix))
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Repo != out[j].Repo {
			return out[i].Repo < out[j].Repo
		}
		return out[i].PR < out[j].PR
	})
	return out
}

// Get is the served status of one grind; ok is false when it has no state file and no live session.
func (s *Service) Get(repo string, pr int) (Status, bool) {
	k, err := keyOf(repo, pr)
	if err != nil {
		return Status{Repo: repo, PR: pr, State: StNone}, false
	}
	ix := s.sessionIndex()
	st, ok := ReadStatus(s.files(), k, s.fallbackMode())
	if ok {
		if o, r, good := splitSlug(st.Repo); good {
			k = Key{o, r, pr}
		}
	} else if g := ix.by[keyID(k)]; g == nil || g.Live == "" {
		return st, false
	}
	return s.decorate(st, k, ix), true
}

// liveGrinds counts the live pr-grind sessions.
func (s *Service) liveGrinds() int { return s.sessionIndex().liveSess }

// entry is one valid state file.
type entry struct {
	Key  Key
	Doc  *Doc
	Path string
	Mod  time.Time
}

// entries reads every valid state file.
func (s *Service) entries() []entry {
	f := s.files()
	ents, err := os.ReadDir(f.Dir())
	if err != nil {
		return nil
	}
	var out []entry
	for _, e := range ents {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		p := filepath.Join(f.Dir(), e.Name())
		b, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		d := parseDoc(b)
		k, ok := validDoc(d)
		if !ok {
			continue
		}
		var mod time.Time
		if fi, err := e.Info(); err == nil {
			mod = fi.ModTime()
		}
		out = append(out, entry{k, d, p, mod})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out
}

// scanChange publishes products{grind} when the served index differs from the last one seen.
func (s *Service) scanChange() {
	idx := s.Index()
	var b strings.Builder
	for _, st := range idx {
		fmt.Fprintf(&b, "%s#%d|%s|%d|%v|%v|%v\n", st.Repo, st.PR, st.State, st.Rounds, derefStr(st.Reason), derefStr(st.Session), derefStr(st.Updated))
	}
	h := b.String()
	s.hashMu.Lock()
	changed := h != s.lastHash
	s.lastHash = h
	s.hashMu.Unlock()
	if changed {
		s.changed("")
	}
}
