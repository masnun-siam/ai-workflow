package notify

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hkdf"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

type env struct {
	s   *Service
	h   *home.Home
	bus *events.Bus
	env map[string]string
}

func newEnv(t *testing.T) *env {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("SETU_HOME", t.TempDir())
	for _, k := range []string{"SETU", "AIW"} {
		for _, f := range []string{"SERVER", "TOPIC", "TOKEN", "USER", "PASSWORD"} {
			t.Setenv(k+"_NTFY_"+f, "")
		}
		t.Setenv(k+"_NO_MAC_BANNER", "")
	}
	e := &env{h: &home.Home{Root: os.Getenv("SETU_HOME")}, bus: events.New(), env: map[string]string{}}
	e.s = New(e.h, nil, e.bus)
	e.s.logf = func(string, ...any) {}
	return e
}

func (e *env) ui(t *testing.T, mode os.FileMode, v any) {
	t.Helper()
	b, _ := json.Marshal(v)
	p := filepath.Join(e.h.Root, "ui.json")
	if err := os.WriteFile(p, b, mode); err != nil {
		t.Fatal(err)
	}
	os.Chmod(p, mode)
}

type got struct {
	method, path, body string
	hdr                http.Header
}

func ntfyServer(t *testing.T, status int) (*httptest.Server, *[]got, *sync.Mutex) {
	t.Helper()
	var mu sync.Mutex
	var reqs []got
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		reqs = append(reqs, got{r.Method, r.URL.EscapedPath(), string(b), r.Header.Clone()})
		mu.Unlock()
		w.WriteHeader(status)
	}))
	t.Cleanup(srv.Close)
	return srv, &reqs, &mu
}

func TestComposeTable(t *testing.T) {
	link := &Link{Owner: "o", Repo: "r", Issue: 5}
	tests := []struct {
		name   string
		event  string
		n      Note
		pub    string
		hdr    map[string]string
		absent []string
		body   string
	}{
		{"waiting", "waiting", Note{SessionID: "sid1", Repo: "o/r", Command: "/blubird:implement-issue 5", Question: "Which approach?\nmore", Recommended: "A", Link: link},
			"https://box.ts.net", map[string]string{"Title": "setu: #5 waiting on you", "Priority": "high", "Tags": "speech_balloon,implement-issue,r,#5",
				"Click": "https://box.ts.net/#/sessions/sid1", "Actions": "view, Answer, https://box.ts.net/#/sessions/sid1"}, nil,
			"Which approach?\nSuggested: A\no/r · /blubird:implement-issue 5"},
		{"failed", "failed", Note{ID: "s2", Repo: "o/r", Command: "/implement-issue 5", Error: "claude exited 1\ntrace", Link: link},
			"", map[string]string{"Title": "setu: #5 failed", "Priority": "high"}, []string{"Click", "Actions"},
			"claude exited 1\no/r · /implement-issue 5"},
		{"done default prio", "done", Note{SessionID: "s", Repo: "o/r", Command: "/create-prd x"}, "https://x/",
			map[string]string{"Title": "setu: run done", "Priority": "default", "Tags": "white_check_mark,create-prd,r", "Click": "https://x/#/sessions/s"}, nil, "o/r · /create-prd x"},
		{"free text no family", "done", Note{Repo: "o/r", Command: "hello there"}, "", map[string]string{"Tags": "white_check_mark,r"}, nil, "o/r · hello there"},
		{"step wins", "done", Note{Repo: "o/r", Command: "hi", Step: "refine-issues"}, "", map[string]string{"Tags": "white_check_mark,refine-issues,r"}, nil, "o/r · hi"},
		{"board", "pr-ready", Note{Repo: "o/r", Text: "PR #9 ready", SessionID: "ignored", Link: link}, "https://x.ts.net",
			map[string]string{"Title": "setu: #5 PR is ready", "Click": "https://x.ts.net/#/inbox"}, nil, "PR #9 ready\no/r"},
		{"grind", "grind-paused", Note{SessionID: "g1", Repo: "o/r", Text: "needs a human", Link: link}, "https://x",
			map[string]string{"Title": "setu: #5 grind paused", "Click": "https://x/#/sessions/g1"}, nil, "needs a human\no/r"},
		{"grind-done prio", "grind-done", Note{Repo: "o/r"}, "", map[string]string{"Priority": "default", "Title": "setu: grind finished"}, nil, "o/r"},
		{"stalled lane", "stalled", Note{Repo: "o/r", Text: "o/r#5 stopped before a PR", Link: link}, "https://x",
			map[string]string{"Title": "setu: #5 stalled", "Priority": "high", "Tags": "zzz,r,#5", "Click": "https://x/#/inbox"}, nil, "o/r#5 stopped before a PR\no/r"},
		{"stalled session opens inbox", "stalled", Note{SessionID: "s9", Repo: "o/r", Command: "/blubird:implement-issue 5", Text: "stopped twice"}, "https://x",
			map[string]string{"Title": "setu: stalled", "Click": "https://x/#/inbox"}, nil, "stopped twice\no/r · /blubird:implement-issue 5"},
		{"afk", "afk", Note{Text: "3 handled"}, "", map[string]string{"Title": "setu: away mode ended", "Priority": "default"}, nil, "3 handled"},
		{"unknown", "wat", Note{}, "https://x", map[string]string{"Title": "setu: update", "Tags": "bell", "Click": "https://x/#/activity"}, nil, ""},
		{"non-ascii url no actions", "done", Note{SessionID: "s"}, "https://x/é", map[string]string{"Click": "https://x/é/#/sessions/s"}, []string{"Actions"}, ""},
		{"id escaped", "done", Note{SessionID: "a b/c"}, "https://x", map[string]string{"Click": "https://x/#/sessions/a%20b%2Fc"}, nil, ""},
		{"tag sanitised", "done", Note{Repo: "o/we ird\r\nX-Evil: 1", Command: "/x y"}, "", map[string]string{"Tags": "white_check_mark,x,weirdX-Evil1"}, nil, "o/we ird\r\nX-Evil: 1 · /x y"},
		{"long question ellipsis", "waiting", Note{Question: strings.Repeat("é", 300)}, "", nil, nil, strings.Repeat("é", 199) + "…"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			h, body := Compose(tc.event, tc.n, tc.pub)
			for k, v := range tc.hdr {
				if h[k] != v {
					t.Errorf("%s = %q, want %q", k, h[k], v)
				}
			}
			for _, k := range tc.absent {
				if _, ok := h[k]; ok {
					t.Errorf("%s should be absent", k)
				}
			}
			if tc.body != "" && body != tc.body {
				t.Errorf("body %q want %q", body, tc.body)
			}
			if !isASCII(h["Title"]) || strings.ContainsAny(h["Tags"], "\r\n ") {
				t.Errorf("unsafe headers %v", h)
			}
		})
	}
}

func TestMatrixDefaults(t *testing.T) {
	m := Config{}.Matrix()
	for _, e := range Events {
		c := m[e.Key]
		if e.Key == "stalled" {
			if c["browser"] || c["ntfy"] || c["mac"] || c["push"] || e.Group != "Needs you" {
				t.Errorf("stalled must be off everywhere by default: %v", c)
			}
			continue
		}
		if !c["ntfy"] || c["push"] {
			t.Errorf("%s ntfy/push defaults: %v", e.Key, c)
		}
		wantBM := e.Group != "Finished" && e.Key != "grind-done"
		if c["browser"] != wantBM || c["mac"] != wantBM {
			t.Errorf("%s browser/mac = %v", e.Key, c)
		}
	}
	if len(m) != 12 || m["release"] == nil || m["stalled"] == nil || m["prd-comment"] != nil || m["pipeline"] != nil {
		t.Errorf("events: %v", m)
	}
	cfg := Config{Stored: map[string]map[string]bool{"done": {"browser": true, "ntfy": false}}}
	if c := cfg.Matrix()["done"]; !c["browser"] || c["ntfy"] || c["mac"] {
		t.Errorf("overlay %v", c)
	}
	if c := cfg.cellsFor("nope"); c["browser"] || !c["ntfy"] || c["mac"] || c["push"] {
		t.Errorf("unknown event %v", c)
	}
}

func TestLoadConfigRules(t *testing.T) {
	e := newEnv(t)
	var warns []string
	e.s.logf = func(f string, a ...any) { warns = append(warns, f) }
	ui := map[string]any{
		"ntfy":       map[string]any{"server": "https://ntfy.sh", "topic": "t", "token": "tok"},
		"public_url": "https://box.ts.net",
		"channels":   map[string]any{"done": map[string]any{"browser": true, "mac": "yes"}, "bogus": map[string]any{"ntfy": false}},
	}
	e.ui(t, 0o644, ui)
	cfg := e.s.LoadConfig()
	if cfg.Ntfy.Server != "" || cfg.PublicURL != "" || len(warns) == 0 {
		t.Fatalf("looser than 0600 must be ignored with a warning: %+v %v", cfg, warns)
	}
	e.ui(t, 0o600, ui)
	cfg = e.s.LoadConfig()
	if cfg.Ntfy.Server != "https://ntfy.sh" || cfg.Ntfy.Token != "tok" || cfg.PublicURL != "https://box.ts.net" {
		t.Fatalf("%+v", cfg)
	}
	if cfg.Stored["done"]["browser"] != true || len(cfg.Stored["done"]) != 1 || cfg.Stored["bogus"] != nil {
		t.Fatalf("stored %v", cfg.Stored)
	}
	// env: SETU_ wins over AIW_, both win over the file
	t.Setenv("AIW_NTFY_SERVER", "http://aiw")
	t.Setenv("AIW_NTFY_TOPIC", "aiwtopic")
	t.Setenv("SETU_NTFY_TOPIC", "setutopic")
	cfg = e.s.LoadConfig()
	if cfg.Ntfy.Server != "http://aiw" || cfg.Ntfy.Topic != "setutopic" || cfg.Ntfy.Token != "tok" {
		t.Fatalf("%+v", cfg.Ntfy)
	}
	if strings.Join(cfg.EnvKeys, ",") != "server,topic" {
		t.Fatalf("env keys %v", cfg.EnvKeys)
	}
	// malformed / non-object ignored
	os.WriteFile(filepath.Join(e.h.Root, "ui.json"), []byte("[1]"), 0o600)
	if cfg = e.s.LoadConfig(); cfg.PublicURL != "" {
		t.Fatal("non-object must be ignored")
	}
	os.WriteFile(filepath.Join(e.h.Root, "ui.json"), []byte("{nope"), 0o600)
	e.s.LoadConfig()
}

func deliverNtfy(t *testing.T, e *env, ntfy map[string]any, extra map[string]any) {
	t.Helper()
	ui := map[string]any{"ntfy": ntfy}
	for k, v := range extra {
		ui[k] = v
	}
	e.ui(t, 0o600, ui)
	e.s.Notify("done", Note{SessionID: "s1", Repo: "o/r", Command: "/x 1"})
	e.s.Wait(5 * time.Second)
}

func TestNtfyPublisher(t *testing.T) {
	tests := []struct {
		name   string
		ntfy   map[string]any
		auth   string
		topic  string
		server func(u string) string
	}{
		{"bearer wins", map[string]any{"token": "tk", "user": "u", "password": "p"}, "Bearer tk", "my%20topic", nil},
		{"basic", map[string]any{"user": "u", "password": "p"}, "Basic " + base64.StdEncoding.EncodeToString([]byte("u:p")), "my%20topic", nil},
		{"incomplete pair no auth", map[string]any{"user": "u"}, "", "my%20topic", nil},
		{"trailing slash", map[string]any{"token": "tk"}, "Bearer tk", "my%20topic", func(u string) string { return u + "/" }},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			e := newEnv(t)
			srv, reqs, mu := ntfyServer(t, 200)
			n := map[string]any{"server": srv.URL, "topic": "my topic"}
			if tc.server != nil {
				n["server"] = tc.server(srv.URL)
			}
			for k, v := range tc.ntfy {
				n[k] = v
			}
			deliverNtfy(t, e, n, nil)
			mu.Lock()
			defer mu.Unlock()
			if len(*reqs) != 1 {
				t.Fatalf("%d requests", len(*reqs))
			}
			r := (*reqs)[0]
			if r.method != "POST" || r.path != "/"+tc.topic || r.hdr.Get("Authorization") != tc.auth {
				t.Fatalf("%+v", r)
			}
			if r.hdr.Get("User-Agent") != "setu (ntfy publisher)" || r.hdr.Get("Title") != "setu: run done" || r.hdr.Get("Priority") != "default" {
				t.Fatalf("headers %v", r.hdr)
			}
			if r.body != "o/r · /x 1" {
				t.Fatalf("body %q", r.body)
			}
		})
	}
}

func TestNtfyEnvOverridesAndErrors(t *testing.T) {
	e := newEnv(t)
	srv, reqs, mu := ntfyServer(t, 200)
	t.Setenv("AIW_NTFY_SERVER", srv.URL)
	t.Setenv("AIW_NTFY_TOPIC", "envtopic")
	t.Setenv("SETU_NTFY_TOKEN", "envtok")
	e.ui(t, 0o600, map[string]any{"ntfy": map[string]any{"server": "http://127.0.0.1:1", "topic": "file", "token": "file"}})
	e.s.Notify("done", Note{})
	e.s.Wait(5 * time.Second)
	mu.Lock()
	if len(*reqs) != 1 || (*reqs)[0].path != "/envtopic" || (*reqs)[0].hdr.Get("Authorization") != "Bearer envtok" {
		t.Fatalf("%+v", *reqs)
	}
	mu.Unlock()

	// error strings
	cfg := e.s.LoadConfig()
	check := func(c Config, want string) {
		t.Helper()
		if got := e.s.sendNtfy(context.Background(), c, Headers{}, "x"); got != want {
			t.Errorf("got %q want %q", got, want)
		}
	}
	check(Config{}, "ntfy is not set up")
	check(Config{Ntfy: NtfyConfig{Server: "ftp://x", Topic: "t"}}, "ntfy server must be an http(s) URL")
	bad, _, _ := ntfyServer(t, 503)
	cfg.Ntfy = NtfyConfig{Server: bad.URL, Topic: "secret-topic"}
	check(cfg, "HTTP 503")
	cfg.Ntfy.Server = "http://127.0.0.1:1"
	if got := e.s.sendNtfy(context.Background(), cfg, Headers{}, "x"); got == "" || strings.Contains(got, "secret-topic") || strings.Contains(got, "127.0.0.1") {
		t.Errorf("connection error must not leak the url: %q", got)
	}
}

func TestNtfyTimeout(t *testing.T) {
	e := newEnv(t)
	stop := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-stop }))
	defer srv.Close()
	defer close(stop)
	start := time.Now()
	got := e.s.sendNtfy(context.Background(), Config{Ntfy: NtfyConfig{Server: srv.URL, Topic: "t"}}, Headers{}, "x")
	if got != "timeout" || time.Since(start) > 7*time.Second {
		t.Fatalf("%q after %v", got, time.Since(start))
	}
}

func TestSuppression(t *testing.T) {
	e := newEnv(t)
	srv, reqs, mu := ntfyServer(t, 200)
	e.ui(t, 0o600, map[string]any{"ntfy": map[string]any{"server": srv.URL, "topic": "t"}})
	away := false
	e.s.SetAway(func() bool { return away })
	count := func() int { e.s.Wait(5 * time.Second); mu.Lock(); defer mu.Unlock(); return len(*reqs) }

	e.s.Notify("done", Note{Role: "away-answerer"})
	e.s.Notify("done", Note{Command: "/blubird:pr-grind 12"})
	e.s.Notify("done", Note{Command: "Start the review grind for PR #12"})
	e.s.Notify("done", Note{Step: "pr-grind"})
	if n := count(); n != 0 {
		t.Fatalf("suppressed notes delivered: %d", n)
	}
	e.s.Notify("grind-done", Note{Command: "/pr-grind 12"}) // only `done` is dropped for grind
	if n := count(); n != 1 {
		t.Fatalf("grind-done: %d", n)
	}
	away = true
	for _, ev := range []string{"waiting", "failed", "grind-paused"} {
		e.s.Notify(ev, Note{})
	}
	if n := count(); n != 1 {
		t.Fatalf("away must mute: %d", n)
	}
	e.s.Notify("afk", Note{})
	e.s.Notify("done", Note{})
	e.s.Notify("pr-ready", Note{})
	if n := count(); n != 4 {
		t.Fatalf("away passes other events: %d", n)
	}
	away = false
	e.s.Notify("waiting", Note{})
	if n := count(); n != 5 {
		t.Fatalf("after away: %d", n)
	}
}

func TestMatrixRoutingAndToast(t *testing.T) {
	e := newEnv(t)
	srv, reqs, mu := ntfyServer(t, 200)
	e.ui(t, 0o600, map[string]any{
		"ntfy":     map[string]any{"server": srv.URL, "topic": "t"},
		"channels": map[string]any{"waiting": map[string]any{"ntfy": false}, "done": map[string]any{"browser": true}},
	})
	ch, cancel := e.bus.Subscribe(16)
	defer cancel()
	e.s.Notify("waiting", Note{SessionID: "w1", Repo: "o/r", Question: "Q?", Link: &Link{Issue: 3}})
	e.s.Notify("done", Note{SessionID: "d1"})
	e.s.Notify("grind-done", Note{}) // browser default off
	e.s.Wait(5 * time.Second)
	mu.Lock()
	n := len(*reqs)
	mu.Unlock()
	if n != 2 { // done + grind-done on ntfy; waiting ntfy disabled
		t.Fatalf("ntfy requests %d", n)
	}
	var toasts []map[string]any
	for len(ch) > 0 {
		ev := <-ch
		if ev.Topic != events.TToast {
			t.Fatalf("topic %v", ev.Topic)
		}
		toasts = append(toasts, ev.Data.(map[string]any))
	}
	if len(toasts) != 2 {
		t.Fatalf("toasts %v", toasts)
	}
	byEv := map[string]map[string]any{}
	for _, m := range toasts {
		byEv[m["event"].(string)] = m
	}
	w := byEv["waiting"]
	if w["title"] != "setu: #3 waiting on you" || w["body"] != "Q?\no/r" || w["path"] != "#/sessions/w1" || w["level"] != "warn" {
		t.Fatalf("%v", w)
	}
	if byEv["done"]["level"] != "info" || byEv["done"]["id"] == w["id"] {
		t.Fatalf("%v", byEv["done"])
	}
}

func TestMacArgv(t *testing.T) {
	long := strings.Repeat("x", 300)
	got := macArgv("/bin/tn", strings.Repeat("t", 100), long, "https://x/#/inbox")
	if got[0] != "/bin/tn" || got[1] != "-title" || len(got[2]) != 80 || got[3] != "-message" || len(got[4]) != 200 || got[5] != "-open" || got[6] != "https://x/#/inbox" || len(got) != 7 {
		t.Fatalf("%q", got)
	}
	if g := macArgv("/bin/tn", "T", "", ""); len(g) != 5 || g[4] != "T" {
		t.Fatalf("body falls back to title: %q", g)
	}
	evil := `"; do shell script "rm -rf ~"`
	osa := macArgv("", "title", evil, "")
	want := []string{"osascript", "-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)", "-e", "end run", evil, "title"}
	if strings.Join(osa, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("%q", osa)
	}
}

func TestMacSend(t *testing.T) {
	e := newEnv(t)
	e.s.goos = "linux"
	if got := e.s.sendMac(context.Background(), "t", "b", ""); got != "Only on macOS" {
		t.Fatal(got)
	}
	bin := t.TempDir()
	fakebin.Install(t, bin)
	e = newEnv(t)
	e.s.goos = "darwin"
	fakebin.WriteRules(t, bin, []fakebin.Rule{{Bin: "terminal-notifier", Exit: 0}})
	if got := e.s.sendMac(context.Background(), "T", "B", "https://x"); got != "" {
		t.Fatal(got)
	}
	calls := fakebin.Calls(t, bin)
	if len(calls) != 1 || strings.Join(calls[0].Args, " ") != "-title T -message B -open https://x" {
		t.Fatalf("%+v", calls)
	}
	fakebin.WriteRules(t, bin, []fakebin.Rule{{Bin: "terminal-notifier", Exit: 3}})
	if got := e.s.sendMac(context.Background(), "T", "B", ""); got != "exit 3" {
		t.Fatal(got)
	}
	t.Setenv("SETU_NO_MAC_BANNER", "1")
	if got := e.s.sendMac(context.Background(), "T", "B", ""); !strings.HasPrefix(got, "Turned off") {
		t.Fatal(got)
	}
	t.Setenv("SETU_NO_MAC_BANNER", "")
	t.Setenv("AIW_NO_MAC_BANNER", "1")
	if got := e.s.sendMac(context.Background(), "T", "B", ""); !strings.HasPrefix(got, "Turned off") {
		t.Fatal(got)
	}
}

// ---- Web Push ----

type uaKeys struct {
	priv *ecdh.PrivateKey
	auth []byte
}

func newUA(t *testing.T) (uaKeys, PushSubscription) {
	t.Helper()
	k, _ := ecdh.P256().GenerateKey(rand.Reader)
	auth := make([]byte, 16)
	rand.Read(auth)
	var s PushSubscription
	s.Keys.P256dh = b64.EncodeToString(k.PublicKey().Bytes())
	s.Keys.Auth = b64.EncodeToString(auth)
	return uaKeys{k, auth}, s
}

// decrypt is the user agent side of RFC 8291.
func (u uaKeys) decrypt(t *testing.T, body []byte) []byte {
	t.Helper()
	salt, idlen := body[:16], int(body[20])
	asPub := body[21 : 21+idlen]
	ct := body[21+idlen:]
	pub, err := ecdh.P256().NewPublicKey(asPub)
	if err != nil {
		t.Fatal(err)
	}
	shared, _ := u.priv.ECDH(pub)
	prkKey, _ := hkdf.Extract(sha256.New, shared, u.auth)
	info := append(append([]byte("WebPush: info\x00"), u.priv.PublicKey().Bytes()...), asPub...)
	ikm, _ := hkdf.Expand(sha256.New, prkKey, string(info), 32)
	prk, _ := hkdf.Extract(sha256.New, ikm, salt)
	cek, _ := hkdf.Expand(sha256.New, prk, "Content-Encoding: aes128gcm\x00", 16)
	nonce, _ := hkdf.Expand(sha256.New, prk, "Content-Encoding: nonce\x00", 12)
	blk, _ := aes.NewCipher(cek)
	gcm, _ := cipher.NewGCM(blk)
	pt, err := gcm.Open(nil, nonce, ct, nil)
	if err != nil {
		t.Fatal(err)
	}
	if pt[len(pt)-1] != 2 {
		t.Fatal("missing delimiter")
	}
	return pt[:len(pt)-1]
}

func TestEncryptRFC8291Vector(t *testing.T) {
	// the example of RFC 8291 section 5 (decrypting the published ciphertext)
	d := func(s string) []byte { b, _ := b64.DecodeString(s); return b }
	uaPriv, _ := ecdh.P256().NewPrivateKey(d("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"))
	auth := d("BTBZMqHH6r4Tts7J_aSIgg")
	body := d("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")
	got := uaKeys{uaPriv, auth}.decrypt(t, body)
	if string(got) != "When I grow up, I want to be a watermelon" {
		t.Fatalf("%q", got)
	}
}

func TestVAPIDKeyOnceAnd0600(t *testing.T) {
	e := newEnv(t)
	k1 := e.s.VAPIDPublicKey()
	k2 := e.s.VAPIDPublicKey()
	if k1 == "" || k1 != k2 {
		t.Fatalf("%q %q", k1, k2)
	}
	raw, err := b64.DecodeString(k1)
	if err != nil || len(raw) != 65 || raw[0] != 4 {
		t.Fatalf("public key shape %d %v", len(raw), err)
	}
	st, err := os.Stat(filepath.Join(e.h.Root, "push.json"))
	if err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("push.json mode %v %v", st, err)
	}
	e2 := New(e.h, nil, nil)
	if e2.VAPIDPublicKey() != k1 {
		t.Fatal("key must persist")
	}
}

func TestPushDeliveryAndPruning(t *testing.T) {
	e := newEnv(t)
	ua, sub := newUA(t)
	var mu sync.Mutex
	var reqs []got
	status := 201
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		reqs = append(reqs, got{r.Method, r.URL.Path, string(b), r.Header.Clone()})
		mu.Unlock()
		w.WriteHeader(status)
	}))
	defer srv.Close()
	sub.Endpoint = srv.URL + "/push/abc"
	if err := e.s.Subscribe(sub, "UA/1"); err != nil {
		t.Fatal(err)
	}
	if err := e.s.Subscribe(sub, "UA/2"); err != nil || e.s.subscriptions() != 1 {
		t.Fatalf("dedupe: %v %d", err, e.s.subscriptions())
	}
	e.ui(t, 0o600, map[string]any{"channels": map[string]any{"waiting": map[string]any{"push": true, "ntfy": false, "browser": false}}})
	e.s.Notify("waiting", Note{SessionID: "s9", Repo: "o/r", Question: "Pick?", Link: &Link{Issue: 4}})
	e.s.Wait(5 * time.Second)
	mu.Lock()
	if len(reqs) != 1 {
		t.Fatalf("requests %d", len(reqs))
	}
	r := reqs[0]
	mu.Unlock()
	if r.hdr.Get("Content-Encoding") != "aes128gcm" || r.hdr.Get("TTL") != "86400" || r.hdr.Get("Urgency") != "high" {
		t.Fatalf("headers %v", r.hdr)
	}
	var pl pushPayload
	if err := json.Unmarshal(ua.decrypt(t, []byte(r.body)), &pl); err != nil {
		t.Fatal(err)
	}
	if pl.Title != "setu: #4 waiting on you" || pl.Path != "#/sessions/s9" || pl.Body != "Pick?\no/r" || pl.Event != "waiting" {
		t.Fatalf("%+v", pl)
	}
	// verify the VAPID header
	auth := r.hdr.Get("Authorization")
	pf := e.s.readPush()
	if !strings.HasPrefix(auth, "vapid t=") || !strings.HasSuffix(auth, ", k="+pf.VapidPublic) {
		t.Fatalf("auth %q", auth)
	}
	jwt := strings.TrimSuffix(strings.TrimPrefix(auth, "vapid t="), ", k="+pf.VapidPublic)
	parts := strings.Split(jwt, ".")
	if len(parts) != 3 {
		t.Fatal(jwt)
	}
	pubRaw, _ := b64.DecodeString(pf.VapidPublic)
	x, y := new(big.Int).SetBytes(pubRaw[1:33]), new(big.Int).SetBytes(pubRaw[33:])
	sig, _ := b64.DecodeString(parts[2])
	sum := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if len(sig) != 64 || !ecdsa.Verify(&ecdsa.PublicKey{Curve: elliptic.P256(), X: x, Y: y}, sum[:], new(big.Int).SetBytes(sig[:32]), new(big.Int).SetBytes(sig[32:])) {
		t.Fatal("bad JWT signature")
	}
	claims, _ := b64.DecodeString(parts[1])
	var cl struct {
		Aud, Sub string
		Exp      int64
	}
	json.Unmarshal(claims, &cl)
	if cl.Aud != srv.URL || cl.Sub != "mailto:setu@localhost" || cl.Exp < time.Now().Unix() {
		t.Fatalf("claims %+v", cl)
	}
	// stored subscription keeps ua and created_at
	if s0 := pf.Subscriptions[0]; s0.UA != "UA/2" || s0.CreatedAt == "" {
		t.Fatalf("%+v", s0)
	}

	// 410 removes the subscription; 500 keeps it
	status = 500
	if err := e.s.Test(context.Background(), "push"); err == nil || e.s.subscriptions() != 1 {
		t.Fatalf("500: %v %d", err, e.s.subscriptions())
	}
	status = 410
	if err := e.s.Test(context.Background(), "push"); err == nil || e.s.subscriptions() != 0 {
		t.Fatalf("410: %v %d", err, e.s.subscriptions())
	}
	if err := e.s.Test(context.Background(), "push"); err == nil || !strings.Contains(err.Error(), "no push subscription") {
		t.Fatalf("%v", err)
	}
}

func TestSubscribeValidation(t *testing.T) {
	e := newEnv(t)
	_, good := newUA(t)
	good.Endpoint = "https://push.example/abc"
	mk := func(f func(*PushSubscription)) PushSubscription { s := good; f(&s); return s }
	bad := []PushSubscription{
		mk(func(s *PushSubscription) { s.Endpoint = "" }),
		mk(func(s *PushSubscription) { s.Endpoint = "http://evil.example/x" }),
		mk(func(s *PushSubscription) { s.Endpoint = "javascript:alert(1)" }),
		mk(func(s *PushSubscription) { s.Keys.P256dh = "AAAA" }),
		mk(func(s *PushSubscription) { s.Keys.Auth = "AAAA" }),
		mk(func(s *PushSubscription) { s.Keys.P256dh = "!!" }),
	}
	for i, s := range bad {
		if err := e.s.Subscribe(s, ""); err == nil {
			t.Errorf("case %d accepted", i)
		}
	}
	if err := e.s.Subscribe(good, ""); err != nil {
		t.Fatal(err)
	}
	if err := e.s.Unsubscribe("https://nope"); err != nil || e.s.subscriptions() != 1 {
		t.Fatal("unsubscribe of an unknown endpoint is a no-op")
	}
	if err := e.s.Unsubscribe(good.Endpoint); err != nil || e.s.subscriptions() != 0 {
		t.Fatal("unsubscribe failed")
	}
	// cap
	for i := 0; i < maxSubs+5; i++ {
		_, s := newUA(t)
		s.Endpoint = "https://push.example/" + string(rune('a'+i))
		if err := e.s.Subscribe(s, ""); err != nil {
			t.Fatal(err)
		}
	}
	if e.s.subscriptions() != maxSubs {
		t.Fatalf("cap: %d", e.s.subscriptions())
	}
}

// ---- routes ----

func call(t *testing.T, h http.Handler, method, path, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	req.Host = "127.0.0.1:8420"
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	var m map[string]any
	json.Unmarshal(rec.Body.Bytes(), &m)
	return rec.Code, m
}

func TestRoutes(t *testing.T) {
	e := newEnv(t)
	e.s.goos = "linux"
	srv, reqs, mu := ntfyServer(t, 200)
	e.ui(t, 0o600, map[string]any{
		"ntfy": map[string]any{"server": srv.URL, "topic": "tp", "token": "SECRET"}, "public_url": "https://box.ts.net",
		"future_key": map[string]any{"keep": true},
	})
	h := server.New(server.Config{Port: 8420}, e.bus, Routes(Deps{Svc: e.s})).Handler()

	code, m := call(t, h, "GET", "/api/settings/notify", "")
	if code != 200 || m["public_url"] != "https://box.ts.net" || m["ntfy_ready"] != true || m["token_set"] != true || m["topic"] != "tp" {
		t.Fatalf("%d %v", code, m)
	}
	if b, _ := json.Marshal(m); strings.Contains(string(b), "SECRET") {
		t.Fatal("secret leaked")
	}
	mat := m["matrix"].(map[string]any)
	if len(mat) != 12 || mat["waiting"].(map[string]any)["push"] != false || mat["waiting"].(map[string]any)["ntfy"] != true {
		t.Fatalf("matrix %v", mat)
	}
	for ch, on := range mat["stalled"].(map[string]any) {
		if on != false {
			t.Fatalf("stalled.%s defaults on", ch)
		}
	}
	if m["mac"].(map[string]any)["available"] != false || m["push"].(map[string]any)["subscriptions"] != float64(0) {
		t.Fatalf("%v", m)
	}

	code, m = call(t, h, "PUT", "/api/settings/notify", `{"cell":{"event":"done","channel":"browser","on":true},"public_url":"https://x.example/"}`)
	if code != 200 || m["public_url"] != "https://x.example/" || m["matrix"].(map[string]any)["done"].(map[string]any)["browser"] != true {
		t.Fatalf("%d %v", code, m)
	}
	// ui.json keeps unknown keys and ntfy, and stays 0600
	raw, _ := os.ReadFile(filepath.Join(e.h.Root, "ui.json"))
	var ui map[string]any
	json.Unmarshal(raw, &ui)
	if ui["future_key"] == nil || ui["ntfy"].(map[string]any)["token"] != "SECRET" {
		t.Fatalf("ui.json lost keys: %s", raw)
	}
	if st, _ := os.Stat(filepath.Join(e.h.Root, "ui.json")); st.Mode().Perm() != 0o600 {
		t.Fatal("mode")
	}
	for _, body := range []string{
		`{"cell":{"event":"nope","channel":"browser","on":true}}`,
		`{"cell":{"event":"done","channel":"sms","on":true}}`,
		`{"cell":{"event":"done","channel":"mac"}}`,
		`{"public_url":"ftp://x"}`,
	} {
		if code, _ := call(t, h, "PUT", "/api/settings/notify", body); code != 400 {
			t.Errorf("%s -> %d", body, code)
		}
	}
	// clearing public_url
	if _, m = call(t, h, "PUT", "/api/settings/notify", `{"public_url":""}`); m["public_url"] != "" {
		t.Fatalf("%v", m)
	}

	// test endpoint
	code, m = call(t, h, "POST", "/api/settings/notify/test", `{"channel":"ntfy"}`)
	if code != 200 || m["ok"] != true {
		t.Fatalf("%d %v", code, m)
	}
	mu.Lock()
	if len(*reqs) != 1 || (*reqs)[0].body != "This is a test from setu." || (*reqs)[0].hdr.Get("Title") != "setu: test notification" {
		t.Fatalf("%+v", *reqs)
	}
	mu.Unlock()
	if code, m = call(t, h, "POST", "/api/settings/notify/test", `{"channel":"mac"}`); code != 200 || m["ok"] != false || m["error"] != "Only on macOS" {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = call(t, h, "POST", "/api/settings/notify/test", `{"channel":"carrier-pigeon"}`); code != 400 {
		t.Fatal(code)
	}

	// push key + subscription
	code, m = call(t, h, "GET", "/api/push/key", "")
	if code != 200 || m["public_key"] == "" {
		t.Fatalf("%d %v", code, m)
	}
	_, sub := newUA(t)
	sub.Endpoint = "https://push.example/z"
	b, _ := json.Marshal(sub)
	if code, m = call(t, h, "POST", "/api/push/subscription", string(b)); code != 200 || m["ok"] != true {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = call(t, h, "POST", "/api/push/subscription", `{"endpoint":"https://a","keys":{"p256dh":"x","auth":"y"}}`); code != 400 {
		t.Fatal(code)
	}
	if _, m = call(t, h, "GET", "/api/settings/notify", ""); m["push"].(map[string]any)["subscriptions"] != float64(1) {
		t.Fatalf("%v", m)
	}
	if code, m = call(t, h, "DELETE", "/api/push/subscription", `{"endpoint":"https://push.example/z"}`); code != 200 || m["ok"] != true {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = call(t, h, "DELETE", "/api/push/subscription", `{}`); code != 400 {
		t.Fatal(code)
	}
}

func TestMigratedUIJSONKeepsWorking(t *testing.T) {
	// the owner's live shape: ntfy{server,topic,token}, public_url, channels for the old events
	e := newEnv(t)
	srv, reqs, mu := ntfyServer(t, 200)
	e.ui(t, 0o600, map[string]any{
		"ntfy": map[string]any{"server": srv.URL, "topic": "owner", "token": "tk"}, "public_url": "https://mac.tail.ts.net",
		"channels": map[string]any{
			"waiting":  map[string]any{"browser": true, "ntfy": true, "mac": true},
			"pipeline": map[string]any{"ntfy": true},
			"afk":      map[string]any{"ntfy": false},
		},
	})
	e.s.Notify("waiting", Note{SessionID: "x", Question: "q"})
	e.s.Notify("afk", Note{})
	e.s.Wait(5 * time.Second)
	mu.Lock()
	defer mu.Unlock()
	if len(*reqs) != 1 || (*reqs)[0].hdr.Get("Click") != "https://mac.tail.ts.net/#/sessions/x" {
		t.Fatalf("%+v", *reqs)
	}
}

func TestStalledOffByDefaultOnSendsOne(t *testing.T) {
	e := newEnv(t)
	srv, reqs, mu := ntfyServer(t, 200)
	e.ui(t, 0o600, map[string]any{"ntfy": map[string]any{"server": srv.URL, "topic": "t"}})
	ch, cancel := e.bus.Subscribe(16)
	defer cancel()
	count := func() int { e.s.Wait(5 * time.Second); mu.Lock(); defer mu.Unlock(); return len(*reqs) }

	e.s.Notify("stalled", Note{SessionID: "s1", Repo: "o/r", Text: "stopped twice"})
	if n := count(); n != 0 || len(ch) != 0 {
		t.Fatalf("defaults delivered: ntfy %d, toasts %d", n, len(ch))
	}
	if err := e.s.SetCell("stalled", "ntfy", true); err != nil {
		t.Fatal(err)
	}
	e.s.Notify("stalled", Note{SessionID: "s1", Repo: "o/r", Text: "stopped twice"})
	if n := count(); n != 1 || len(ch) != 0 {
		t.Fatalf("ntfy on: ntfy %d, toasts %d", n, len(ch))
	}
	if err := e.s.SetCell("stalled", "browser", true); err != nil {
		t.Fatal(err)
	}
	e.s.Notify("stalled", Note{SessionID: "s1", Repo: "o/r", Text: "stopped twice"})
	e.s.Wait(5 * time.Second)
	if len(ch) != 1 {
		t.Fatalf("toasts %d", len(ch))
	}
	if m := (<-ch).Data.(map[string]any); m["level"] != "warn" || m["path"] != "#/inbox" {
		t.Fatalf("%v", m)
	}
}
