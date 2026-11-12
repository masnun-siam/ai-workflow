package prompts

import (
	"net/http"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps are the routes' dependencies.
type Deps struct{ Registry *Registry }

type regStep struct {
	Step
	Command   string `json:"command"`
	Available bool   `json:"available"`
	Reason    string `json:"reason,omitempty"`
}

// Routes serves GET /api/registry (API.md §5.1).
func Routes(d Deps) []server.Route {
	return []server.Route{{Pattern: "GET /api/registry", Handler: server.Handle(func(*http.Request) (int, any, error) {
		out := []regStep{}
		for _, s := range d.Registry.Steps() {
			cmd := "/" + s.Skill
			if s.Source == SrcBlubird {
				cmd = "/blubird:" + s.Skill
			}
			rs := regStep{Step: s, Command: cmd, Available: true}
			if err := d.Registry.Available(s.ID); err != nil {
				rs.Available, rs.Reason = false, errs.Body(err)["error"].(string)
			}
			out = append(out, rs)
		}
		return 0, map[string]any{"steps": out}, nil
	})}}
}
