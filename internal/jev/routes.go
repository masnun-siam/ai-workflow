package jev

import (
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// MaxRouteText is the longest text POST /api/jev/route accepts, in characters.
const MaxRouteText = 20000

// Deps is what Routes needs.
type Deps struct{ Client *Client }

// Routes serves POST /api/jev/route (the Create box route pick).
func Routes(d Deps) []server.Route {
	return []server.Route{
		{Pattern: "POST /api/jev/route", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var b struct {
				Text *string `json:"text"`
			}
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			if b.Text == nil || strings.TrimSpace(*b.Text) == "" {
				return 0, nil, errs.Invalid("text is required")
			}
			if utf8.RuneCountInString(*b.Text) > MaxRouteText {
				return 0, nil, errs.Invalid("text is longer than 20000 characters")
			}
			return 200, d.Client.Route(r.Context(), *b.Text), nil
		})},
	}
}
