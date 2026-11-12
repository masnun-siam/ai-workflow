package inbox

import (
	"net/http"

	"github.com/masnun-siam/setu/internal/server"
)

// Routes serves GET /api/inbox?product=&repo=. It marks every watched repo viewed (the inbox is
// the global board).
func Routes(b *Builder) []server.Route {
	return []server.Route{{Pattern: "GET /api/inbox", Handler: server.Handle(func(r *http.Request) (int, any, error) {
		if b.d.Snapshots != nil {
			b.d.Snapshots.MarkViewed("*")
		}
		q := r.URL.Query()
		return http.StatusOK, b.Build(r.Context(), q.Get("product"), q.Get("repo")), nil
	})}}
}
