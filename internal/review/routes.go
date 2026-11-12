package review

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// RouteDeps is Routes' input.
type RouteDeps struct{ Svc *Service }

// Routes is the review part of API §5.5 and §5.7.
func Routes(d RouteDeps) []server.Route {
	s := d.Svc
	h := server.Handle
	return []server.Route{
		{Pattern: "GET /api/review", Handler: h(func(r *http.Request) (int, any, error) {
			return 200, map[string]any{"panels": s.List()}, nil
		})},
		{Pattern: "GET /api/review/offers", Handler: h(func(r *http.Request) (int, any, error) {
			return 200, s.Offers(), nil
		})},
		{Pattern: "POST /api/review", Handler: h(func(r *http.Request) (int, any, error) {
			var c CreatePanel
			if err := server.Decode(r, &c); err != nil {
				return 0, nil, err
			}
			p, err := s.Create(r.Context(), c)
			if err != nil {
				return 0, nil, err
			}
			return 201, p, nil
		})},
		{Pattern: "GET /api/review/{panel}", Handler: h(func(r *http.Request) (int, any, error) {
			p, err := s.Get(r.PathValue("panel"))
			return 200, p, err
		})},
		{Pattern: "POST /api/review/{panel}/lens", Handler: h(func(r *http.Request) (int, any, error) {
			var b struct{ Lens, Action string }
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			p, err := s.LensAction(r.PathValue("panel"), b.Lens, b.Action)
			return 200, p, err
		})},
		{Pattern: "POST /api/review/{panel}/rounds", Handler: h(func(r *http.Request) (int, any, error) {
			var b struct {
				Add *json.RawMessage `json:"add"`
			}
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			n, err := intOf(b.Add)
			if err != nil {
				return 0, nil, errs.Invalid("add must be an integer from 1 to 5")
			}
			p, err := s.AddRounds(r.PathValue("panel"), n)
			return 200, p, err
		})},
		{Pattern: "GET /api/settings/review", Handler: h(func(r *http.Request) (int, any, error) {
			return 200, View(s.d.Home), nil
		})},
		{Pattern: "PUT /api/settings/review", Handler: h(func(r *http.Request) (int, any, error) {
			var in SaveConfigInput
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			v, err := SaveConfig(s.d.Home, in)
			return 200, v, err
		})},
	}
}

// Commands is `setu review lenses`: the ReviewConfig JSON the peer-review prompt reads.
func Commands() []cli.Command {
	return []cli.Command{{
		Name:    "review",
		Summary: "peer-review settings: lenses (ReviewConfig JSON, with each lens's focus)",
		Run: func(ctx context.Context, env cli.Env, args []string) int {
			if len(args) != 1 || args[0] != "lenses" {
				fmt.Fprintln(env.Stderr, "usage: setu review lenses")
				return cli.ExitUsage
			}
			if env.Home == nil {
				fmt.Fprintln(env.Stderr, "setu review: the data dir could not be opened")
				return 1
			}
			cfg, _ := LoadConfig(env.Home)
			out := struct {
				ReviewConfig
				Focus map[string]string `json:"focus"`
			}{View(env.Home), map[string]string{}}
			for k, l := range cfg.Lenses {
				out.Focus[k] = l.Focus
			}
			b, _ := json.MarshalIndent(out, "", "  ")
			fmt.Fprintf(env.Stdout, "%s\n", b)
			return 0
		},
	}}
}
