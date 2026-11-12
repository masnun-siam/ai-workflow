package prompts

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRegistryRoute(t *testing.T) {
	r := load(t, false)
	rt := Routes(Deps{Registry: r})
	if len(rt) != 1 || rt[0].Pattern != "GET /api/registry" {
		t.Fatalf("%v", rt)
	}
	w := httptest.NewRecorder()
	rt[0].Handler.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/registry", nil))
	var out struct {
		Steps []struct {
			ID, Command, Reason, Source string
			RunsIn                      string `json:"runs_in"`
			Available                   bool
		}
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &out) != nil || len(out.Steps) != 22 {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
	for _, s := range out.Steps {
		switch s.ID {
		case "implement-issue":
			if s.Available || s.Reason != "blubird is not installed" || s.Command != "/blubird:implement-issue" {
				t.Fatalf("%+v", s)
			}
		case "release-pr":
			if !s.Available || s.Command != "/release-pr" || s.RunsIn != "repo" {
				t.Fatalf("%+v", s)
			}
		}
	}
}
