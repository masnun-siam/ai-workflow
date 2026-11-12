package away

import (
	"math"
	"net/http"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// RouteDeps wires Routes.
type RouteDeps struct{ Service *Service }

// Routes is the away part of API §5.5.
func Routes(d RouteDeps) []server.Route {
	s, h := d.Service, server.Handle
	return []server.Route{
		{Pattern: "POST /api/away", Handler: h(func(r *http.Request) (int, any, error) {
			var b struct {
				Until *float64 `json:"until"`
			}
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			if b.Until == nil || math.IsNaN(*b.Until) || math.IsInf(*b.Until, 0) {
				return 0, nil, errs.Invalid("until must be a time within the next 24 hours")
			}
			a, err := s.Begin(int64(math.Ceil(*b.Until)))
			return 0, a, err
		})},
		{Pattern: "POST /api/away/stop", Handler: h(func(*http.Request) (int, any, error) {
			a, err := s.End()
			return 0, a, err
		})},
		{Pattern: "POST /api/away/dismiss", Handler: h(func(*http.Request) (int, any, error) {
			a, err := s.Dismiss()
			return 0, a, err
		})},
		{Pattern: "POST /api/away/change", Handler: h(func(r *http.Request) (int, any, error) {
			var b struct {
				Changes []AwayChange `json:"changes"`
			}
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			res, err := s.Change(b.Changes)
			return 0, res, err
		})},
	}
}
