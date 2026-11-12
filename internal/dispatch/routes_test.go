package dispatch

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/sessions"
)

func mux(t *testing.T, e *env) *http.ServeMux {
	t.Helper()
	m := http.NewServeMux()
	for _, r := range Routes(RouteDeps{Service: e.svc}) {
		m.Handle(r.Pattern, r.Handler)
	}
	return m
}

func call(m http.Handler, method, path, body string) (int, map[string]any) {
	var rd *strings.Reader
	if body != "" {
		rd = strings.NewReader(body)
	} else {
		rd = strings.NewReader("")
	}
	r := httptest.NewRequest(method, path, rd)
	if body != "" {
		r.Header.Set("Content-Type", "application/json")
	}
	w := httptest.NewRecorder()
	m.ServeHTTP(w, r)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func TestRoutes(t *testing.T) {
	e := newEnv(t)
	m := mux(t, e) // registration panics on a pattern conflict
	e.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}, {n: 3, state: "OPEN", refined: true, blocked: []string{"o/r#2:OPEN"}}}))

	code, body := call(m, "GET", "/api/dispatches", "")
	if code != 200 || len(body["dispatches"].([]any)) != 0 {
		t.Fatal(code, body)
	}

	// plan
	code, body = call(m, "POST", "/api/dispatches/plan", `{"epic":"o/r#1"}`)
	if code != 200 || len(body["waves"].([]any)) != 2 || body["title"] != "The epic" {
		t.Fatal(code, body)
	}
	// create
	code, body = call(m, "POST", "/api/dispatches", `{"epic":"o/r#1","settings":{"max":3,"auto_merge":true}}`)
	if code != 201 {
		t.Fatal(code, body)
	}
	id := body["id"].(string)
	if body["state"] != "running" || body["epic"] != "o/r#1" || body["settings"].(map[string]any)["max"] != float64(3) ||
		len(body["lanes"].([]any)) != 2 || body["totals"].(map[string]any)["lanes"] != float64(2) {
		t.Fatalf("%v", body)
	}
	lane0 := body["lanes"].([]any)[0].(map[string]any)
	for _, k := range []string{"key", "repo", "n", "title", "deps", "stage", "pr", "needs_you", "held", "gate", "skip_reason", "paused", "paused_by", "hold_merge",
		"limited_until", "started_at", "ended_at", "session", "usage"} {
		if _, ok := lane0[k]; !ok {
			t.Errorf("lane lacks %q", k)
		}
	}
	if lane0["pr"] != nil || lane0["session"] != nil || lane0["usage"].(map[string]any)["cost"] != float64(0) {
		t.Fatalf("%v", lane0)
	}
	// the same epic again: 409 {error,id}
	code, body = call(m, "POST", "/api/dispatches", `{"epic":"o/r#1"}`)
	if code != 409 || body["id"] != id || !strings.Contains(body["error"].(string), "is already a lane of dispatch "+id) {
		t.Fatal(code, body)
	}
	// bad bodies
	for _, c := range []struct{ body string }{{`{}`}, {`{"epic":"o/r#1","issues":["o/r#2"]}`}, {`{"epic":"nope"}`}, {`{"epic":"o/r#1","settings":{"max":0}}`}, {`{"epic":"o/r#1","settings":[]}`}, {`{"epic":""}`}} {
		if code, b := call(m, "POST", "/api/dispatches", c.body); code != 400 {
			t.Errorf("%s: %d %v", c.body, code, b)
		}
	}
	// list + get (with events)
	code, body = call(m, "GET", "/api/dispatches", "")
	if code != 200 || len(body["dispatches"].([]any)) != 1 || body["dispatches"].([]any)[0].(map[string]any)["events"] != nil {
		t.Fatal(code, body)
	}
	code, body = call(m, "GET", "/api/dispatches/"+id, "")
	if code != 200 || len(body["events"].([]any)) != 1 {
		t.Fatal(code, body)
	}
	for _, bad := range []string{"/api/dispatches/zzz", "/api/dispatches/ffffffffffff", "/api/dispatches/0123456789AB"} {
		if code, _ := call(m, "GET", bad, ""); code != 404 {
			t.Errorf("%s: %d", bad, code)
		}
	}

	// settings
	code, body = call(m, "POST", "/api/dispatches/"+id+"/settings", `{"max":5,"ci":"defer"}`)
	if code != 200 || body["settings"].(map[string]any)["ci"] != "defer" {
		t.Fatal(code, body)
	}
	for _, bad := range []string{`{"base_branch":"x"}`, `{"nope":1}`, `{"max":"2"}`, `{"account":"ghost"}`} {
		if code, _ := call(m, "POST", "/api/dispatches/"+id+"/settings", bad); code != 400 {
			t.Errorf("%s: %d", bad, code)
		}
	}
	// state
	code, body = call(m, "POST", "/api/dispatches/"+id+"/state", `{"state":"paused"}`)
	if code != 200 || body["state"] != "paused" {
		t.Fatal(code, body)
	}
	if code, _ = call(m, "POST", "/api/dispatches/"+id+"/state", `{"state":"flying"}`); code != 400 {
		t.Fatal(code)
	}
	call(m, "POST", "/api/dispatches/"+id+"/state", `{"state":"running"}`)
	// lane actions
	code, body = call(m, "POST", "/api/dispatches/"+id+"/lane", `{"lane":"o/r#2","action":"pause"}`)
	if code != 200 || !body["lanes"].([]any)[0].(map[string]any)["paused"].(bool) {
		t.Fatal(code, body)
	}
	for _, bad := range []string{`{"lane":"o/r#2","action":"dance"}`, `{"lane":"o/r#77","action":"pause"}`, `{"lane":"o/r#2","action":"send","text":"x"}`} {
		if code, _ := call(m, "POST", "/api/dispatches/"+id+"/lane", bad); code != 400 {
			t.Errorf("%s: %d", bad, code)
		}
	}
	// retry-failed / seen need no body
	if code, _ = call(m, "POST", "/api/dispatches/"+id+"/retry-failed", ""); code != 200 {
		t.Fatal(code)
	}
	code, body = call(m, "POST", "/api/dispatches/"+id+"/seen", "")
	if code != 200 || body["seen_done"] != true {
		t.Fatal(code, body)
	}
	code, body = call(m, "POST", "/api/dispatches/"+id+"/seen", `{"undo":true}`)
	if code != 200 || body["seen_done"] != false {
		t.Fatal(code, body)
	}
	// end
	if code, _ = call(m, "POST", "/api/dispatches/"+id+"/end", `{"action":"open-pr"}`); code != 400 {
		t.Fatal("open-pr needs a feature branch:", code)
	}
	call(m, "POST", "/api/dispatches/"+id+"/settings", `{"feature_branch":"feat"}`)
	if code, body = call(m, "POST", "/api/dispatches/"+id+"/end", `{"action":"open-pr"}`); code != 200 {
		t.Fatal(code, body)
	}
	if d := e.svc; len(store.List(d.d.Home)[0].EndReqs) != 1 {
		t.Fatal("end request not stored")
	}
	// unknown dispatch on a POST
	if code, _ = call(m, "POST", "/api/dispatches/ffffffffffff/state", `{"state":"paused"}`); code != 404 {
		t.Fatal(code)
	}
	// the right content type is required
	r := httptest.NewRequest("POST", "/api/dispatches/"+id+"/state", strings.NewReader(`{"state":"paused"}`))
	w := httptest.NewRecorder()
	m.ServeHTTP(w, r)
	if w.Code != 415 {
		t.Fatal(w.Code)
	}
}

func TestRoutesAddLanesAndCoordinators(t *testing.T) {
	e := newEnv(t)
	m := mux(t, e)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 2, Stage: store.StQueued})
	e.gh.Add(issuesRule(node{n: 8, state: "OPEN", refined: true}))
	code, body := call(m, "POST", "/api/dispatches/aaaaaaaaaaaa/lanes", `{"issues":["o/r#8"]}`)
	if code != 200 || len(body["lanes"].([]any)) != 2 {
		t.Fatal(code, body)
	}
	if code, _ = call(m, "POST", "/api/dispatches/aaaaaaaaaaaa/lanes", `{"issues":[]}`); code != 400 {
		t.Fatal(code)
	}

	coordFixture(t, e)
	code, body = call(m, "GET", "/api/coordinators", "")
	if code != 200 || len(body["coordinators"].([]any)) != 2 {
		t.Fatal(code, body)
	}
	c0 := body["coordinators"].([]any)[0].(map[string]any)
	for _, k := range []string{"run", "repo", "source", "destination", "session", "live", "queue", "claims", "prs", "poll", "events"} {
		if _, ok := c0[k]; !ok {
			t.Errorf("coordinator lacks %q", k)
		}
	}
	if code, _ = call(m, "POST", "/api/coordinators/nope/stop", ""); code != 404 {
		t.Fatal(code)
	}
	if code, _ = call(m, "POST", "/api/coordinators/20261111-213742/stop", ""); code != 502 {
		t.Fatal("blubird missing:", code)
	}
	_ = sessions.StDone
}
