package views

import (
	"net/http"

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
			return http.StatusOK, s.River(r.Context(), p), nil
		})},
		{Pattern: "GET /api/ops", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p, err := product(r)
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, s.Ops(r.Context(), p), nil
		})},
		{Pattern: "GET /api/features", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p, err := product(r)
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, s.Features(r.Context(), p), nil
		})},
		{Pattern: "GET /api/me", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return http.StatusOK, s.Me(r.Context()), nil
		})},
	}
}
