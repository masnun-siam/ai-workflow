package sessions

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// RouteDeps wires Routes.
type RouteDeps struct {
	Manager *Manager
}

// Routes is the sessions part of API §5.2.
func Routes(d RouteDeps) []server.Route {
	m := d.Manager
	h := server.Handle
	pub := func(r Record) Session { return m.Public(r) }
	action := func(name string, fn func(*http.Request, string) (Record, error)) server.Route {
		return server.Route{Pattern: "POST /api/sessions/{id}/" + name, Handler: h(func(r *http.Request) (int, any, error) {
			rec, err := fn(r, r.PathValue("id"))
			if err != nil {
				return 0, nil, err
			}
			return 200, pub(rec), nil
		})}
	}
	return []server.Route{
		{Pattern: "GET /api/sessions", Handler: h(m.listHandler)},
		{Pattern: "POST /api/sessions", Handler: h(func(r *http.Request) (int, any, error) {
			var req StartRequest
			if err := server.Decode(r, &req); err != nil {
				return 0, nil, err
			}
			rec, err := m.StartSession(r.Context(), req)
			if err != nil {
				return 0, nil, err
			}
			return 201, pub(rec), nil
		})},
		{Pattern: "GET /api/sessions/cleanup", Handler: h(func(r *http.Request) (int, any, error) {
			return 200, map[string]any{"items": m.CleanupTargets()}, nil
		})},
		{Pattern: "POST /api/sessions/cleanup", Handler: h(func(r *http.Request) (int, any, error) {
			var body struct {
				Keys *[]string `json:"keys"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if body.Keys == nil {
				return 0, nil, errs.Invalid("keys must be a list of session keys")
			}
			return 200, map[string]any{"removed": m.Cleanup(*body.Keys)}, nil
		})},
		{Pattern: "GET /api/sessions/{id}", Handler: h(func(r *http.Request) (int, any, error) {
			rec, err := m.Get(r.PathValue("id"))
			if err != nil {
				return 0, nil, err
			}
			return 200, pub(rec), nil
		})},
		{Pattern: "GET /api/sessions/{id}/stream", Handler: h(func(r *http.Request) (int, any, error) {
			id := r.PathValue("id")
			if _, err := m.Get(id); err != nil {
				return 0, nil, err
			}
			var offset int64
			if s := r.URL.Query().Get("offset"); s != "" {
				n, err := strconv.ParseInt(s, 10, 64)
				if err != nil || n < 0 {
					return 0, nil, errs.Invalid("bad offset")
				}
				offset = n
			}
			evs, next, err := m.Stream(id, offset)
			if err != nil {
				return 0, nil, err
			}
			return 200, map[string]any{"events": evs, "offset": next}, nil
		})},
		{Pattern: "POST /api/sessions/{id}/answer", Handler: h(func(r *http.Request) (int, any, error) {
			id := r.PathValue("id")
			if _, err := m.Get(id); err != nil {
				return 0, nil, err
			}
			var body struct {
				RoundID string            `json:"round_id"`
				Answers map[string]Answer `json:"answers"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			rec, err := m.Answer(r.Context(), id, body.RoundID, body.Answers)
			if err != nil {
				return 0, nil, err
			}
			return 200, pub(rec), nil
		})},
		{Pattern: "POST /api/sessions/{id}/prompt", Handler: h(func(r *http.Request) (int, any, error) {
			id := r.PathValue("id")
			if _, err := m.Get(id); err != nil {
				return 0, nil, err
			}
			var body struct {
				Text string `json:"text"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			state, err := m.SendPrompt(r.Context(), id, body.Text, 4000)
			if err != nil {
				return 0, nil, err
			}
			if state == "queued" {
				return 202, map[string]any{"state": state}, nil
			}
			return 200, map[string]any{"state": state}, nil
		})},
		action("stop", func(r *http.Request, id string) (Record, error) {
			rec, err := m.Get(id)
			if err != nil {
				return rec, err
			}
			if rec.Status.Terminal() {
				return rec, errs.Conflict("session already finished", map[string]any{"id": id})
			}
			out, err := m.Stop(r.Context(), id)
			if err != nil {
				return out, err
			}
			if out.Status != StStopped {
				return out, errs.Conflict("session is starting, retry", map[string]any{"id": id})
			}
			return out, nil
		}),
		action("resume", func(r *http.Request, id string) (Record, error) {
			if _, err := m.Get(id); err != nil {
				return Record{}, err
			}
			var body struct {
				Account string `json:"account"`
			}
			if r.ContentLength > 0 {
				if err := server.Decode(r, &body); err != nil {
					return Record{}, err
				}
			}
			return m.ResumeStopped(r.Context(), id, body.Account)
		}),
		action("cancel-auto", func(_ *http.Request, id string) (Record, error) { return m.CancelAuto(id) }),
		action("hold", func(_ *http.Request, id string) (Record, error) { return m.Hold(id) }),
		action("release", func(_ *http.Request, id string) (Record, error) { return m.Release(id) }),
		action("start-now", func(r *http.Request, id string) (Record, error) { return m.StartNow(r.Context(), id) }),
		action("dismiss", func(_ *http.Request, id string) (Record, error) { return m.Dismiss(id) }),
		{Pattern: "POST /api/sessions/{id}/rerun", Handler: h(func(r *http.Request) (int, any, error) {
			rec, err := m.Rerun(r.Context(), r.PathValue("id"))
			if err != nil {
				return 0, nil, err
			}
			return 201, pub(rec), nil
		})},
	}
}

func (m *Manager) listHandler(r *http.Request) (int, any, error) {
	q := r.URL.Query()
	f := Filter{Limit: 200}
	if s := q.Get("limit"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 1 || n > 1000 {
			return 0, nil, errs.Invalid("limit must be a whole number from 1 to 1000")
		}
		f.Limit = n
	}
	if b := q.Get("before"); b != "" {
		if !ValidID(b) {
			return 0, nil, errs.Invalid("before must be a session id")
		}
		f.Before = b
	}
	if s := q.Get("status"); s != "" {
		for _, p := range strings.Split(s, ",") {
			switch st := Status(strings.TrimSpace(p)); st {
			case StStarting, StRunning, StWaiting, StLimited, StQueued, StDone, StFailed, StStopped:
				f.Statuses = append(f.Statuses, st)
			default:
				return 0, nil, errs.Invalid("unknown status %q", p)
			}
		}
	}
	if repo := q.Get("repo"); repo != "" {
		if !slugRe.MatchString(repo) {
			return 0, nil, errs.Invalid("repo must be owner/name")
		}
		f.Repo = repo
	}
	f.Step = q.Get("step")
	recs := m.List(f)
	out := make([]Session, 0, len(recs))
	for _, rec := range recs {
		out = append(out, m.Public(rec))
	}
	return 200, map[string]any{"sessions": out, "stats": m.Stats(), "limits": m.Limits()}, nil
}
