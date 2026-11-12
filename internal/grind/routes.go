package grind

import (
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Routes is the grind part of API §5.5. (It takes the Service, as release does, instead of Deps.)
func Routes(s *Service) []server.Route {
	h := server.Handle
	target := func(r *http.Request) (string, int, error) {
		slug, err := server.Slug(r)
		if err != nil {
			return "", 0, err
		}
		pr, err := server.PathInt(r, "pr")
		return slug, pr, err
	}
	status := func(repo string, pr int) (Status, error) {
		st, ok := s.Get(repo, pr)
		if !ok {
			return st, errs.NotFound("no grind for %s#%d", repo, pr)
		}
		return st, nil
	}
	return []server.Route{
		{Pattern: "GET /api/grinds", Handler: h(func(r *http.Request) (int, any, error) {
			repo := r.URL.Query().Get("repo")
			if repo != "" && !slugRE.MatchString(repo) {
				return 0, nil, errs.Invalid("bad repo")
			}
			out := []Status{}
			for _, st := range s.Index() {
				if repo == "" || strings.EqualFold(st.Repo, repo) {
					out = append(out, st)
				}
			}
			return 200, map[string]any{"grinds": out}, nil
		})},
		{Pattern: "POST /api/grinds", Handler: h(func(r *http.Request) (int, any, error) {
			var body struct {
				Repo string `json:"repo"`
				PR   int    `json:"pr"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if !slugRE.MatchString(body.Repo) || body.PR < 1 {
				return 0, nil, errs.Invalid("repo (owner/name) and pr (a positive number) are required")
			}
			rec, err := s.StartGrind(r.Context(), body.Repo, body.PR, "ui")
			if err != nil {
				return 0, nil, err
			}
			return 201, s.d.Sessions.Public(rec), nil
		})},
		{Pattern: "POST /api/grinds/issue", Handler: h(func(r *http.Request) (int, any, error) {
			var body struct {
				Repo  string `json:"repo"`
				Issue int    `json:"issue"`
				On    *bool  `json:"on"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if !slugRE.MatchString(body.Repo) || body.Issue < 1 || body.On == nil {
				return 0, nil, errs.Invalid("repo (owner/name), issue (>= 1) and on (boolean) are required")
			}
			if err := s.SetIssue(r.Context(), body.Repo, body.Issue, *body.On); err != nil {
				return 0, nil, err
			}
			return 200, map[string]any{"ok": true}, nil
		})},
		{Pattern: "POST /api/grinds/{owner}/{name}/{pr}/skip-ci", Handler: h(func(r *http.Request) (int, any, error) {
			repo, pr, err := target(r)
			if err != nil {
				return 0, nil, err
			}
			if err := s.SkipCI(r.Context(), repo, pr); err != nil {
				return 0, nil, err
			}
			return 200, map[string]any{"state": "running"}, nil
		})},
		{Pattern: "POST /api/grinds/{owner}/{name}/{pr}/stop", Handler: h(func(r *http.Request) (int, any, error) {
			repo, pr, err := target(r)
			if err != nil {
				return 0, nil, err
			}
			if err := s.Stop(repo, pr); err != nil {
				return 0, nil, err
			}
			st, err := status(repo, pr)
			return 200, st, err
		})},
	}
}
