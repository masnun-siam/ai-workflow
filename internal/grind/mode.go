package grind

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/settings"
)

// DispatchMode is the grind mode of the running or paused dispatch that owns the PR: simple when
// its settings.grind is "simple", else deep. ok is false when no dispatch owns the PR. It reads
// dispatches/*.json directly so the CLI works without the dispatch package (a leaf reader that
// matches dispatch/store.GrindMode, API §2).
func DispatchMode(h *home.Home, repo string, pr int) (string, bool) {
	ents, err := os.ReadDir(h.Path("dispatches"))
	if err != nil {
		return "", false
	}
	for _, e := range ents {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		var d struct {
			State    string `json:"state"`
			Settings struct {
				Grind string `json:"grind"`
			} `json:"settings"`
			Lanes map[string]struct {
				Repo string `json:"repo"`
				PR   *int   `json:"pr"`
			} `json:"lanes"`
		}
		if home.ReadJSON(filepath.Join(h.Path("dispatches"), e.Name()), &d) != nil {
			continue
		}
		if d.State != "running" && d.State != "paused" {
			continue
		}
		for _, l := range d.Lanes {
			if l.PR != nil && *l.PR == pr && strings.EqualFold(l.Repo, repo) {
				if d.Settings.Grind == "simple" {
					return "simple", true
				}
				return "deep", true
			}
		}
	}
	return "", false
}

// GrindMode is deep or simple for prURL: the dispatch that owns the PR decides, then a mode pinned
// in the PR's state file (an explicit `grind start --mode`), else Settings (default deep).
func GrindMode(h *home.Home, st *settings.Store, prURL string) string {
	if m := reURLRepo.FindStringSubmatch(prURL); m != nil {
		n := atoi(m[3])
		if mode, ok := DispatchMode(h, m[1]+"/"+m[2], n); ok {
			return mode
		}
		k := Key{m[1], m[2], n}
		if d, err := (Files{h}).Read(k); err == nil {
			if pin := ModeOf(d.Get("mode")); pin != "" {
				return pin
			}
		}
	}
	return settingsMode(st)
}

func settingsMode(st *settings.Store) string {
	if st != nil {
		if m := ModeOf(st.Get().GrindMode); m != "" {
			return m
		}
	}
	return "deep"
}
