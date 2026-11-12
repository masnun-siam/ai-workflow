package server

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/fstest"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func testServer(t *testing.T, routes ...Route) *Server {
	t.Helper()
	s := New(Config{Port: 8420, Version: "test"}, events.New(), routes)
	s.fs = fstest.MapFS{
		"index.html":           {Data: []byte("<html>app</html>")},
		"assets/app-1a2b.js":   {Data: []byte("console.log(1)")},
		"sw.js":                {Data: []byte("//sw")},
		"manifest.webmanifest": {Data: []byte("{}")},
	}
	return s
}

func do(s *Server, method, target, host string, hdr map[string]string, body string) *httptest.ResponseRecorder {
	var rd io.Reader
	if body != "" {
		rd = strings.NewReader(body)
	}
	r := httptest.NewRequest(method, target, rd)
	r.Host = host
	for k, v := range hdr {
		r.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	return w
}

func TestGuardMatrix(t *testing.T) {
	s := testServer(t)
	s.SetTailnet([]string{"mac.tail1234.ts.net"}, "Me@Example.com")
	s.cfg.AllowHosts = []string{"alias.example"}
	own := map[string]string{"Tailscale-User-Login": "me@example.com"}
	cases := []struct {
		name string
		host string
		hdr  map[string]string
		want int
	}{
		{"loopback ip", "127.0.0.1:8420", nil, 200},
		{"localhost", "localhost:8420", nil, 200},
		{"wrong port", "127.0.0.1:9999", nil, 403},
		{"missing host", "", nil, 403},
		{"unknown host", "evil.example", nil, 403},
		{"tailnet host no login", "mac.tail1234.ts.net", nil, 403},
		{"tailnet host wrong login", "mac.tail1234.ts.net", map[string]string{"Tailscale-User-Login": "x@y.z"}, 403},
		{"tailnet host owner", "mac.tail1234.ts.net", own, 200},
		{"allow-host owner", "alias.example", own, 200},
		{"allow-host no login", "alias.example", nil, 403},
		{"origin same", "127.0.0.1:8420", map[string]string{"Origin": "http://127.0.0.1:8420"}, 200},
		{"origin other", "127.0.0.1:8420", map[string]string{"Origin": "http://evil.example"}, 403},
		{"origin null", "127.0.0.1:8420", map[string]string{"Origin": "null"}, 403},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			w := do(s, "GET", "/api/health", c.host, c.hdr, "")
			if w.Code != c.want {
				t.Fatalf("got %d want %d", w.Code, c.want)
			}
			if c.want == 403 && !strings.HasPrefix(w.Header().Get("Content-Type"), "text/plain") {
				t.Errorf("403 should be text/plain, got %q", w.Header().Get("Content-Type"))
			}
		})
	}
	// the guard runs before the method check
	if w := do(s, "HEAD", "/", "evil.example", nil, ""); w.Code != 403 {
		t.Errorf("bad host + HEAD = %d", w.Code)
	}
}

func TestMethods(t *testing.T) {
	s := testServer(t)
	for _, m := range []string{"HEAD", "OPTIONS", "TRACE", "CONNECT"} {
		w := do(s, m, "/api/health", "127.0.0.1:8420", nil, "")
		if w.Code != 405 || w.Header().Get("Allow") != "GET" {
			t.Errorf("%s: %d %q", m, w.Code, w.Header().Get("Allow"))
		}
	}
	if w := do(s, "POST", "/", "127.0.0.1:8420", nil, ""); w.Code != 405 {
		t.Errorf("POST /: %d", w.Code)
	}
}

type body struct {
	A string `json:"a"`
	N int    `json:"n"`
}

func TestDecodeRules(t *testing.T) {
	var got body
	s := testServer(t, Route{"POST /api/echo", Handle(func(r *http.Request) (int, any, error) {
		if err := Decode(r, &got); err != nil {
			return 0, nil, err
		}
		return 201, got, nil
	})})
	post := func(ct, payload string, cl int) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/api/echo", strings.NewReader(payload))
		r.Host = "127.0.0.1:8420"
		if ct != "" {
			r.Header.Set("Content-Type", ct)
		}
		r.ContentLength = int64(cl)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		return w
	}
	big := `{"a":"` + strings.Repeat("x", 70000) + `"}`
	cases := []struct {
		name, ct, payload string
		cl                int
		code              int
		msg               string
	}{
		{"ok", "application/json", `{"a":"x","n":2}`, 15, 201, ""},
		{"ok charset", "application/json; charset=utf-8", `{"a":"x"}`, 9, 201, ""},
		{"no content type", "", `{"a":"x"}`, 9, 415, "Content-Type"},
		{"text type", "text/plain", `{"a":"x"}`, 9, 415, "Content-Type"},
		{"unknown length", "application/json", `{"a":"x"}`, -1, 400, "bad Content-Length"},
		{"too large", "application/json", big, len(big), 413, "body too large"},
		{"array", "application/json", `[1]`, 3, 400, "body must be a JSON object"},
		{"empty", "application/json", ``, 0, 400, "body must be a JSON object"},
		{"invalid json", "application/json", `{"a":`, 5, 400, "body must be a JSON object"},
		{"wrong type", "application/json", `{"n":"x"}`, 9, 400, `has the wrong type`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			w := post(c.ct, c.payload, c.cl)
			if w.Code != c.code {
				t.Fatalf("code %d want %d (%s)", w.Code, c.code, w.Body)
			}
			if !strings.Contains(w.Body.String(), c.msg) {
				t.Fatalf("body %q want %q", w.Body, c.msg)
			}
			if ct := w.Header().Get("Content-Type"); ct != "application/json; charset=utf-8" {
				t.Errorf("content type %q", ct)
			}
		})
	}
}

func TestErrorKindsToStatus(t *testing.T) {
	cases := []struct {
		err  error
		code int
		body string
	}{
		{errs.Invalid("bad"), 400, `{"error":"bad"}`},
		{errs.NotFound("gone"), 404, `{"error":"gone"}`},
		{errs.Conflict("busy", map[string]any{"id": "s1", "href": "/api/sessions/s1"}), 409, `{"error":"busy","href":"/api/sessions/s1","id":"s1"}`},
		{errs.Upstream("gh down"), 502, `{"error":"gh down"}`},
		{errs.Forbidden("no"), 403, `{"error":"no"}`},
		{errors.New("secret detail"), 500, `{"error":"internal error"}`},
	}
	for _, c := range cases {
		s := testServer(t, Route{"GET /api/x", Handle(func(*http.Request) (int, any, error) { return 0, nil, c.err })})
		w := do(s, "GET", "/api/x", "127.0.0.1:8420", nil, "")
		if w.Code != c.code || strings.TrimSpace(w.Body.String()) != c.body {
			t.Errorf("%v: %d %s", c.err, w.Code, w.Body)
		}
	}
	s := testServer(t)
	if w := do(s, "GET", "/api/nope", "127.0.0.1:8420", nil, ""); w.Code != 404 || !strings.Contains(w.Body.String(), `"error"`) {
		t.Errorf("unknown api: %d %s", w.Code, w.Body)
	}
}

func TestPathHelpers(t *testing.T) {
	s := testServer(t, Route{"GET /api/repos/{owner}/{name}/issues/{n}", Handle(func(r *http.Request) (int, any, error) {
		slug, err := Slug(r)
		if err != nil {
			return 0, nil, err
		}
		n, err := PathInt(r, "n")
		if err != nil {
			return 0, nil, err
		}
		return 200, map[string]any{"slug": slug, "n": n}, nil
	})})
	for target, code := range map[string]int{
		"/api/repos/o/r/issues/12":    200,
		"/api/repos/o/r.x-y/issues/1": 200,
		"/api/repos/o/r/issues/0":     400,
		"/api/repos/o/r/issues/abc":   400,
		"/api/repos/.o/r/issues/1":    400,
		"/api/repos/o/-r/issues/1":    400,
	} {
		if w := do(s, "GET", target, "127.0.0.1:8420", nil, ""); w.Code != code {
			t.Errorf("%s: %d want %d", target, w.Code, code)
		}
	}
}

func TestStaticAndSPA(t *testing.T) {
	s := testServer(t)
	h := "127.0.0.1:8420"
	cases := []struct {
		target string
		code   int
		body   string
		cache  string
	}{
		{"/", 200, "app", "no-cache"},
		{"/sessions/20260101T000000000000Z-abcd1234", 200, "app", "no-cache"},
		{"/inbox", 200, "app", "no-cache"},
		{"/assets/app-1a2b.js", 200, "console.log", "public, max-age=31536000, immutable"},
		{"/assets/missing.js", 404, "", ""},
		{"/sw.js", 200, "//sw", "no-cache"},
		{"/manifest.webmanifest", 200, "{}", "no-cache"},
		{"/index.html", 200, "app", "no-cache"},
		{"/../etc/passwd", 404, "", ""},
		{"/%2e%2e/etc/passwd", 404, "", ""},
		{"/%252e%252e/etc/passwd", 404, "", ""},
		{"/assets/%2e%2e/index.html", 404, "", ""},
		{"/assets/..%2findex.html", 404, "", ""},
	}
	for _, c := range cases {
		t.Run(c.target, func(t *testing.T) {
			w := do(s, "GET", c.target, h, nil, "")
			if w.Code != c.code || !strings.Contains(w.Body.String(), c.body) {
				t.Fatalf("%d %q", w.Code, w.Body)
			}
			if c.cache != "" && w.Header().Get("Cache-Control") != c.cache {
				t.Errorf("cache %q want %q", w.Header().Get("Cache-Control"), c.cache)
			}
		})
	}
}

func TestEmbeddedPlaceholderServes(t *testing.T) {
	s := New(Config{Port: 8420}, nil, nil)
	if w := do(s, "GET", "/", "127.0.0.1:8420", nil, ""); w.Code != 200 || !strings.Contains(w.Body.String(), "<title>") {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
}

type sseReader struct {
	br *bufio.Reader
}

// next returns the next frame (up to a blank line) as lines.
func (r *sseReader) next(t *testing.T) []string {
	t.Helper()
	var lines []string
	for {
		l, err := r.br.ReadString('\n')
		if err != nil {
			t.Fatalf("read: %v (got %v)", err, lines)
		}
		l = strings.TrimRight(l, "\n")
		if l == "" {
			return lines
		}
		lines = append(lines, l)
	}
}

func TestSSE(t *testing.T) {
	bus := events.New()
	s := New(Config{Port: 0, Version: "9.9"}, bus, nil)
	s.pingEvery = 50 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Listen(ctx) }()
	select {
	case <-s.Ready():
	case <-time.After(3 * time.Second):
		t.Fatal("not ready")
	}
	req, _ := http.NewRequest("GET", "http://"+s.Addr()+"/api/events", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	for k, v := range map[string]string{"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"} {
		if resp.Header.Get(k) != v {
			t.Errorf("%s = %q", k, resp.Header.Get(k))
		}
	}
	r := &sseReader{bufio.NewReader(resp.Body)}
	if f := r.next(t); len(f) != 1 || f[0] != "retry: 3000" {
		t.Fatalf("first frame %v", f)
	}
	f := r.next(t)
	if len(f) != 3 || f[1] != "event: hello" || !strings.Contains(f[2], `"version":"9.9"`) || !strings.Contains(f[2], `"resync":false`) || !strings.Contains(f[2], s.BootID()) {
		t.Fatalf("hello frame %v", f)
	}
	if bus.Subscribers() != 1 {
		t.Fatalf("subscribers %d", bus.Subscribers())
	}
	bus.Publish(events.TSessions, map[string]any{"id": "x", "status": "running", "change": "record"})
	for {
		f = r.next(t)
		if len(f) == 1 && f[0] == ": ping" {
			continue
		}
		break
	}
	if len(f) != 3 || !strings.HasPrefix(f[0], "id: ") || f[1] != "event: sessions" || f[2] != `data: {"change":"record","id":"x","status":"running"}` {
		t.Fatalf("event frame %v", f)
	}
	resp.Body.Close()
	deadline := time.Now().Add(2 * time.Second)
	for bus.Subscribers() != 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if bus.Subscribers() != 0 {
		t.Error("subscription not freed on disconnect")
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Listen did not return")
	}
}

func TestSSEPingAndShutdownEndsStream(t *testing.T) {
	s := New(Config{Port: 0}, nil, nil)
	s.pingEvery = 30 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Listen(ctx) }()
	<-s.Ready()
	resp, err := http.Get("http://" + s.Addr() + "/api/events")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	r := &sseReader{bufio.NewReader(resp.Body)}
	r.next(t)
	r.next(t)
	if f := r.next(t); len(f) != 1 || f[0] != ": ping" {
		t.Fatalf("expected ping, got %v", f)
	}
	start := time.Now()
	cancel()
	<-done
	if time.Since(start) > 2500*time.Millisecond {
		t.Error("shutdown waited for the SSE stream")
	}
}

func TestListenPortInUse(t *testing.T) {
	a := New(Config{Port: 0}, nil, nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go a.Listen(ctx)
	<-a.Ready()
	port := a.loopbackPort()
	b := New(Config{Port: port}, nil, nil)
	err := b.Listen(context.Background())
	if err == nil || !strings.Contains(err.Error(), "already in use") {
		t.Fatalf("err = %v", err)
	}
}

func TestTailscaleUp(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	dir := t.TempDir()
	fakebin.Install(t, dir)
	status := `{"BackendState":"Running","Self":{"DNSName":"mac.tail1234.ts.net.","UserID":7},"User":{"7":{"LoginName":"Owner@Example.com"}}}`
	fakebin.WriteRules(t, dir, []fakebin.Rule{
		{Bin: "tailscale", ArgsPrefix: []string{"status", "--json"}, Stdout: status},
		{Bin: "tailscale", ArgsPrefix: []string{"serve", "status"}, Stdout: `{}`},
		{Bin: "tailscale", ArgsPrefix: []string{"serve"}},
	})
	s := New(Config{Port: 0, Tailscale: true, TailscaleHTTPSPort: 8443}, nil, nil)
	s.logf = t.Logf
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Listen(ctx) }()
	<-s.Ready()
	if w := do(s, "GET", "/api/health", "mac.tail1234.ts.net:8443", map[string]string{"Tailscale-User-Login": "owner@example.com"}, ""); w.Code != 200 {
		t.Errorf("tailnet request: %d", w.Code)
	}
	cancel()
	<-done
	var serveArgs [][]string
	for _, c := range fakebin.Calls(t, dir) {
		if len(c.Args) > 0 && c.Args[0] == "serve" {
			serveArgs = append(serveArgs, c.Args)
		}
	}
	if len(serveArgs) != 3 || serveArgs[1][1] != "--bg" || serveArgs[1][2] != "--https=8443" || !strings.HasPrefix(serveArgs[1][3], "http://127.0.0.1:") ||
		strings.Join(serveArgs[2], " ") != "serve --https=8443 off" {
		t.Fatalf("serve calls: %v", serveArgs)
	}
}

func TestTailscaleForeignHandlerNotOverwritten(t *testing.T) {
	dir := t.TempDir()
	fakebin.Install(t, dir)
	fakebin.WriteRules(t, dir, []fakebin.Rule{
		{Bin: "tailscale", ArgsPrefix: []string{"status", "--json"}, Stdout: `{"BackendState":"Running","Self":{"DNSName":"m.ts.net.","UserID":1},"User":{"1":{"LoginName":"o@x"}}}`},
		{Bin: "tailscale", ArgsPrefix: []string{"serve", "status"}, Stdout: `{"Web":{"m.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:3000"}}}}}`},
	})
	s := New(Config{Port: 0, Tailscale: true}, nil, nil)
	if _, err := s.tailscaleUp(context.Background()); err == nil || !strings.Contains(err.Error(), "not overwriting") {
		t.Fatalf("err = %v", err)
	}
}
