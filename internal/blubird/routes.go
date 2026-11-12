package blubird

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps are the routes' dependencies.
type Deps struct{ Manager *Manager }

func Routes(d Deps) []server.Route {
	m := d.Manager
	return []server.Route{
		{Pattern: "GET /api/blubird", Handler: server.Handle(func(*http.Request) (int, any, error) {
			return 0, m.Status(), nil
		})},
		{Pattern: "POST /api/blubird/install", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			if err := m.Install(r.Context()); err != nil {
				return 0, nil, err
			}
			return http.StatusAccepted, m.Status(), nil
		})},
		{Pattern: "POST /api/blubird/update", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			if err := m.Update(r.Context()); err != nil {
				return 0, nil, err
			}
			return http.StatusAccepted, m.Status(), nil
		})},
	}
}

// Commands is `setu blubird status|install|update`. The CLI has no server, so install and update
// run to completion before printing the status; exit 1 when the job failed.
func Commands() []cli.Command {
	return []cli.Command{{
		Name:    "blubird",
		Summary: "blubird status|install|update",
		Run: func(ctx context.Context, env cli.Env, args []string) int {
			if len(args) != 1 {
				fmt.Fprintln(env.Stderr, "usage: setu blubird status|install|update")
				return cli.ExitUsage
			}
			m := New(env.Home, nil)
			switch args[0] {
			case "status":
			case "install", "update":
				var err error
				if args[0] == "install" {
					err = m.Install(ctx)
				} else {
					err = m.Update(ctx)
				}
				if err != nil {
					fmt.Fprintln(env.Stderr, err)
					return 1
				}
				m.Wait()
			default:
				fmt.Fprintln(env.Stderr, "usage: setu blubird status|install|update")
				return cli.ExitUsage
			}
			st := m.Status()
			b, _ := json.MarshalIndent(st, "", "  ")
			fmt.Fprintf(env.Stdout, "%s\n", b)
			if st.Error != "" {
				return 1
			}
			return 0
		},
	}}
}
