package claude

import (
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/settings"
)

type Deps struct{ Settings *settings.Store }

// Routes: POST /api/settings/test-account.
func Routes(d Deps) []server.Route {
	return []server.Route{{Pattern: "POST /api/settings/test-account", Handler: server.Handle(func(r *http.Request) (int, any, error) {
		var body struct {
			Label string `json:"label"`
		}
		if err := server.Decode(r, &body); err != nil {
			return 0, nil, err
		}
		if strings.TrimSpace(body.Label) == "" {
			return 200, map[string]any{"ok": false, "message": "label required"}, nil
		}
		acc, ok := d.Settings.Account(body.Label)
		if !ok {
			return 0, nil, errs.Invalid("label must be an account saved in Settings: save the account first")
		}
		okLogin, msg := TestAccount(r.Context(), acc.Cmd)
		return 200, map[string]any{"ok": okLogin, "message": msg}, nil
	})}}
}
