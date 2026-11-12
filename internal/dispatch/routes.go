package dispatch

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// RouteDeps for Routes.
type RouteDeps struct{ Service *Service }

func dispatchID(r *http.Request) (string, error) {
	id := r.PathValue("id")
	if !store.ValidID(id) {
		return "", errs.NotFound("no dispatch %s", id)
	}
	return id, nil
}

type createBody struct {
	Epic     json.RawMessage `json:"epic"`
	Issues   []string        `json:"issues"`
	Settings json.RawMessage `json:"settings"`
}

func (b createBody) request() (CreateRequest, error) {
	var r CreateRequest
	switch s := strings.TrimSpace(string(b.Epic)); {
	case s == "" || s == "null":
	case strings.HasPrefix(s, `"`):
		if err := json.Unmarshal(b.Epic, &r.Epic); err != nil {
			return r, errs.Invalid("epic must be owner/repo#N")
		}
		if strings.TrimSpace(r.Epic) == "" {
			return r, errs.Invalid("give either epic or issues")
		}
	default:
		r.Epic = s // a bare number
	}
	r.Issues = b.Issues
	set, err := ParseSettings(b.Settings)
	if err != nil {
		return r, err
	}
	// only the known keys are taken from the UI's settings object; the rest is rejected by ApplySettings
	r.Settings = set
	return r, nil
}

// Routes: §5.5 dispatch and coordinator routes.
func Routes(d RouteDeps) []server.Route {
	s := d.Service
	one := func(f func(r *http.Request, id string) (store.Dispatch, error)) http.Handler {
		return server.Handle(func(r *http.Request) (int, any, error) {
			id, err := dispatchID(r)
			if err != nil {
				return 0, nil, err
			}
			disp, err := f(r, id)
			if err != nil {
				return 0, nil, err
			}
			return 0, s.Public(disp, true), nil
		})
	}
	optionalBody := func(r *http.Request, v any) error {
		if r.ContentLength == 0 {
			return nil
		}
		return server.Decode(r, v)
	}
	return []server.Route{
		{Pattern: "GET /api/dispatches", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			out := []PublicDispatch{}
			for _, x := range s.List() {
				out = append(out, s.Public(x, false))
			}
			return 0, map[string]any{"dispatches": out}, nil
		})},
		{Pattern: "POST /api/dispatches", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var b createBody
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			req, err := b.request()
			if err != nil {
				return 0, nil, err
			}
			disp, err := s.Create(r.Context(), req)
			if err != nil {
				return 0, nil, err
			}
			return http.StatusCreated, s.Public(disp, true), nil
		})},
		{Pattern: "POST /api/dispatches/plan", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var b createBody
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			req, err := b.request()
			if err != nil {
				return 0, nil, err
			}
			p, err := s.Plan(r.Context(), req)
			return 0, p, err
		})},
		{Pattern: "GET /api/dispatches/{id}", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			return s.Get(id)
		})},
		{Pattern: "POST /api/dispatches/{id}/settings", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var raw json.RawMessage
			if err := server.Decode(r, &raw); err != nil {
				return store.Dispatch{}, err
			}
			patch, err := ParseSettings(raw)
			if err != nil {
				return store.Dispatch{}, err
			}
			return s.SetSettings(id, patch)
		})},
		{Pattern: "POST /api/dispatches/{id}/state", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var b struct {
				State string `json:"state"`
				Now   bool   `json:"now"`
			}
			if err := server.Decode(r, &b); err != nil {
				return store.Dispatch{}, err
			}
			return s.SetState(id, b.State, b.Now)
		})},
		{Pattern: "POST /api/dispatches/{id}/lane", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var b struct {
				Lane   string `json:"lane"`
				Action string `json:"action"`
				Text   string `json:"text"`
			}
			if err := server.Decode(r, &b); err != nil {
				return store.Dispatch{}, err
			}
			return s.LaneAction(id, b.Lane, b.Action, b.Text)
		})},
		{Pattern: "POST /api/dispatches/{id}/lanes", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var b struct {
				Issues []string `json:"issues"`
			}
			if err := server.Decode(r, &b); err != nil {
				return store.Dispatch{}, err
			}
			return s.AddLanes(r.Context(), id, b.Issues)
		})},
		{Pattern: "POST /api/dispatches/{id}/retry-failed", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			d, _, err := s.RetryFailed(id)
			return d, err
		})},
		{Pattern: "POST /api/dispatches/{id}/seen", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var b struct {
				Undo bool `json:"undo"`
			}
			if err := optionalBody(r, &b); err != nil {
				return store.Dispatch{}, err
			}
			return s.Seen(id, b.Undo)
		})},
		{Pattern: "POST /api/dispatches/{id}/end", Handler: one(func(r *http.Request, id string) (store.Dispatch, error) {
			var b struct {
				Action string `json:"action"`
			}
			if err := server.Decode(r, &b); err != nil {
				return store.Dispatch{}, err
			}
			return s.RequestEnd(id, b.Action)
		})},
		{Pattern: "GET /api/coordinators", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return 0, map[string]any{"coordinators": s.Coordinators()}, nil
		})},
		{Pattern: "POST /api/coordinators/{run}/stop", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			if err := s.StopCoordinator(r.Context(), r.PathValue("run")); err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"ok": true}, nil
		})},
	}
}
