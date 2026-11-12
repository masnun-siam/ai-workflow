package inbox

import "github.com/masnun-siam/setu/internal/settings"

// StoreGrind adapts *settings.Store to GrindSettings: the per-issue switch wins, else the repo's
// auto_grind.
type StoreGrind struct{ Store *settings.Store }

func (s StoreGrind) GrindOn(slug string, issue int) bool {
	if on, set := s.Store.IssueGrind(slug, issue); set {
		return on
	}
	for k, r := range s.Store.Get().Repos {
		if equalFold(k, slug) {
			return r.AutoGrind
		}
	}
	return false
}
