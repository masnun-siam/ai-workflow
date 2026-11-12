package views

import (
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Routes serves /api/status, /api/river, /api/features, /api/ops and /api/me. (/api/inbox is inbox.Routes.)
func Routes(s *Service) []server.Route {
	product := func(r *http.Request) (string, error) {
		q := r.URL.Query().Get("product")
		if q == "" {
			return "", nil
		}
		p, ok := s.Product(q)
		if !ok {
			return "", errs.Invalid("unknown product %q", q)
		}
		return p.DocsRepo, nil
	}
	return []server.Route{
		{Pattern: "GET /api/status", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return http.StatusOK, s.Status(r.Context()), nil
		})},
		{Pattern: "GET /api/river", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p, err := product(r)
			if err != nil {
				return 0, nil, err
			}
			repo, err := s.registeredRepo(r.URL.Query().Get("repo"))
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, s.River(r.Context(), p, repo), nil
		})},
		{Pattern: "GET /api/ops", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p, err := product(r)
			if err != nil {
				return 0, nil, err
			}
			repo, err := s.registeredRepo(r.URL.Query().Get("repo"))
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, s.Ops(r.Context(), p, repo), nil
		})},
		{Pattern: "GET /api/features", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p, err := product(r)
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, s.Features(r.Context(), p), nil
		})},
		{Pattern: "GET /api/changes", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return http.StatusOK, s.Changes(r.Context(), r.URL.Query().Get("repo")), nil
		})},
		{Pattern: "GET /api/me", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return http.StatusOK, s.Me(r.Context()), nil
		})},
	}
}

// registeredRepo resolves ?repo= to its registered slug ("" stays ""); an unknown repo is invalid.
func (s *Service) registeredRepo(q string) (string, error) {
	if q == "" || s.d.Products == nil {
		return "", nil
	}
	for _, r := range s.d.Products.Repos() {
		if strings.EqualFold(r.Slug, q) {
			return r.Slug, nil
		}
	}
	return "", errs.Invalid("unknown repo %q", q)
}
