package jev

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func postRoute(t *testing.T, c *Client, ctype, body string) *httptest.ResponseRecorder {
	t.Helper()
	rt := Routes(Deps{Client: c})
	if len(rt) != 1 || rt[0].Pattern != "POST /api/jev/route" {
		t.Fatalf("routes %v", rt)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/jev/route", strings.NewReader(body))
	req.Header.Set("Content-Type", ctype)
	w := httptest.NewRecorder()
	rt[0].Handler.ServeHTTP(w, req)
	return w
}

func TestRouteEndpointOK(t *testing.T) {
	c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"bug","probabilities":{"bug":0.82}}`}})
	w := postRoute(t, c, "application/json", `{"text":"The app crashes when I open settings"}`)
	if w.Code != 200 || strings.TrimSpace(w.Body.String()) != `{"route":"bug","p":0.82,"status":"ok"}` {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
}

func TestRouteEndpointJevFailureIs200(t *testing.T) {
	c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Exit: 1}})
	w := postRoute(t, c, "application/json", `{"text":"anything at all"}`)
	if w.Code != 200 || strings.TrimSpace(w.Body.String()) != `{"route":null,"p":null,"status":"failed"}` {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
}

func TestRouteEndpointRejects(t *testing.T) {
	c, bin, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"bug"}`}})
	long, _ := json.Marshal(map[string]string{"text": strings.Repeat("é", MaxRouteText+1)})
	edge, _ := json.Marshal(map[string]string{"text": strings.Repeat("é", MaxRouteText)})
	tests := []struct {
		name, ctype, body string
		code              int
	}{
		{"missing text", "application/json", `{}`, 400},
		{"null text", "application/json", `{"text":null}`, 400},
		{"blank text", "application/json", `{"text":"  \n "}`, 400},
		{"too long", "application/json", string(long), 400},
		{"wrong type", "application/json", `{"text":5}`, 400},
		{"not json", "application/json", `text=hi`, 400},
		{"content type", "text/plain", `{"text":"hi"}`, 415},
		{"at the limit", "application/json", string(edge), 200},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			w := postRoute(t, c, tc.ctype, tc.body)
			if w.Code != tc.code {
				t.Fatalf("got %d want %d: %s", w.Code, tc.code, w.Body.String())
			}
			if tc.code != 200 && !strings.Contains(w.Body.String(), `"error"`) {
				t.Fatalf("want {error}: %s", w.Body.String())
			}
		})
	}
	if n := len(fakebin.Calls(t, bin)); n != 1 {
		t.Fatalf("only the valid request may run jev: %d calls", n)
	}
}
