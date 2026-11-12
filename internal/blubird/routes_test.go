package blubird

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func call(_ []string, h http.Handler, method, path string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(method, path, nil))
	return w
}

func TestRoutes(t *testing.T) {
	setup(t, true)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	fakebin.WriteRules(t, bin, []fakebin.Rule{{Bin: "claude", ArgsPrefix: []string{"plugin"}, SleepMs: 200}})
	m := newMgr(t)
	routes := Routes(Deps{Manager: m})
	byPat := map[string]http.Handler{}
	for _, r := range routes {
		byPat[r.Pattern] = r.Handler
	}
	w := call(nil, byPat["GET /api/blubird"], "GET", "/api/blubird")
	var st Status
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &st) != nil || !st.Installed {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
	w = call(nil, byPat["POST /api/blubird/update"], "POST", "/api/blubird/update")
	if w.Code != 202 || !strings.Contains(w.Body.String(), `"busy":"updating"`) {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
	w = call(nil, byPat["POST /api/blubird/install"], "POST", "/api/blubird/install")
	if w.Code != 409 {
		t.Fatalf("busy: %d %s", w.Code, w.Body.String())
	}
	m.Wait()
}

func TestRoutesClaudeMissing(t *testing.T) {
	setup(t, false)
	t.Setenv("PATH", t.TempDir())
	h := Routes(Deps{Manager: newMgr(t)})[1].Handler
	if w := call(nil, h, "POST", "/api/blubird/install"); w.Code != 502 {
		t.Fatalf("%d %s", w.Code, w.Body.String())
	}
}

func TestCommand(t *testing.T) {
	setup(t, true)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	fakebin.WriteRules(t, bin, []fakebin.Rule{{Bin: "claude", ArgsPrefix: []string{"plugin"}}})
	var out, errb bytes.Buffer
	env := cli.Env{Stdout: &out, Stderr: &errb}
	cmd := Commands()[0]
	if code := cmd.Run(context.Background(), env, []string{"status"}); code != 0 || !strings.Contains(out.String(), `"installed": true`) {
		t.Fatalf("%d %s", code, out.String())
	}
	out.Reset()
	if code := cmd.Run(context.Background(), env, []string{"update"}); code != 0 || !strings.Contains(out.String(), `"busy": ""`) {
		t.Fatalf("%d %s %s", code, out.String(), errb.String())
	}
	if code := cmd.Run(context.Background(), env, nil); code != cli.ExitUsage {
		t.Fatalf("usage %d", code)
	}
	fakebin.WriteRules(t, bin, []fakebin.Rule{{Bin: "claude", ArgsPrefix: []string{"plugin"}, Stderr: "no", Exit: 3}})
	out.Reset()
	if code := cmd.Run(context.Background(), env, []string{"install"}); code != 1 || !strings.Contains(out.String(), `"error": "plugin marketplace add`) {
		t.Fatalf("%d %s", code, out.String())
	}
}
