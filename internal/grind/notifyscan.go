package grind

import (
	"os"
	"sort"

	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
)

const notifiedFile = "grind_notified.json"

// NotifyScan pushes `grind-done` and `grind-paused` once per key `<owner>/<repo>#<n>:done` or
// `...:paused:<reason>` (W§6.3). The seen set is grind_notified.json, a sorted list of the keys
// currently present. The first scan (no file yet) records silently. A loop that resumes and pauses
// again for the same reason notifies again because its key left the set in between.
func (s *Service) NotifyScan() {
	s.notifyMu.Lock()
	defer s.notifyMu.Unlock()
	path := s.d.Home.Path(notifiedFile)
	var prev []string
	first := !fileExists(path)
	if !first {
		if err := home.ReadJSON(path, &prev); err != nil {
			s.warn("%s: %v", notifiedFile, err)
			return
		}
	}
	seen := map[string]bool{}
	for _, k := range prev {
		seen[k] = true
	}
	type note struct {
		event, text string
		e           entry
	}
	cur := map[string]note{}
	for _, e := range s.entries() {
		id := e.Key.Slug() + "#" + itoa(e.Key.N)
		if v := e.Doc.Get("done"); v != "" {
			cur[id+":done"] = note{"grind-done", afterStamp(v), e}
		} else if v := e.Doc.Get("paused"); v != "" {
			r := afterStamp(v)
			cur[id+":paused:"+r] = note{"grind-paused", r, e}
		}
	}
	keys := make([]string, 0, len(cur))
	for k := range cur {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	if !first && s.d.Notify != nil {
		for _, k := range keys {
			if seen[k] {
				continue
			}
			n := cur[k]
			thread := n.e.Doc.Get("thread")
			s.d.Notify.Notify(n.event, notify.Note{
				ID: k, Repo: n.e.Key.Slug(), Command: "/pr-grind " + thread, Text: n.text,
				Link: &notify.Link{Owner: n.e.Key.Owner, Repo: n.e.Key.Repo, Issue: n.e.Key.N},
			})
		}
	}
	if keys == nil {
		keys = []string{}
	}
	if first || !equalStrings(prev, keys) {
		if err := home.WriteJSON(path, keys); err != nil {
			s.warn("%s: %v", notifiedFile, err)
		}
	}
}

func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }
