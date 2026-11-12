package settings

import (
	"encoding/json"
	"net/http"

	"github.com/masnun-siam/setu/internal/server"
)

type Deps struct{ Store *Store }

// Routes: GET/PUT /api/settings.
func Routes(d Deps) []server.Route {
	return []server.Route{
		{Pattern: "GET /api/settings", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return 200, d.Store.View(), nil
		})},
		{Pattern: "PUT /api/settings", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var body json.RawMessage
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			v, err := d.Store.Save(body)
			return 200, v, err
		})},
	}
}
