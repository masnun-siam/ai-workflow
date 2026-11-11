// Package server is the net/http core: guard, JSON helpers, SSE, static UI with SPA fallback.
package server

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"path"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/web"
)

// Route is one API route; Pattern is a Go 1.22 mux pattern such as "POST /api/sessions/{id}/answer".
type Route struct {
	Pattern string
	Handler http.Handler
}

type Config struct {
	Port               int
	AllowHosts         []string
	Tailscale          bool
	TailscaleHTTPSPort int
	Version            string
}

type Server struct {
	cfg    Config
	bus    *events.Bus
	api    *http.ServeMux
	fs     fs.FS
	bootID string
	logf   func(format string, a ...any)

	mu        sync.RWMutex
	port      int
	tsHosts   []string // tailnet host names, as they appear in the Host header
	tsOwner   string   // lowercased node owner login
	pingEvery time.Duration

	ready    chan struct{}
	readyOne sync.Once
	quit     chan struct{}
	quitOne  sync.Once
}

// New builds the server. A route pattern registered twice panics (a wiring bug).
func New(cfg Config, bus *events.Bus, routes []Route) *Server {
	if bus == nil {
		bus = events.New()
	}
	b := make([]byte, 4)
	_, _ = rand.Read(b)
	s := &Server{
		cfg: cfg, bus: bus, api: http.NewServeMux(), fs: web.FS, bootID: hex.EncodeToString(b),
		logf: log.Printf, pingEvery: 15 * time.Second,
		ready: make(chan struct{}), quit: make(chan struct{}),
	}
	s.api.Handle("GET /api/health", Handle(func(*http.Request) (int, any, error) {
		return http.StatusOK, map[string]bool{"ok": true}, nil
	}))
	s.api.HandleFunc("GET /api/events", s.serveEvents)
	for _, r := range routes {
		s.api.Handle(r.Pattern, r.Handler)
	}
	s.api.HandleFunc("/api/", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
	})
	return s
}

// Handler is the full handler chain (guard, method check, API mux, static UI).
func (s *Server) Handler() http.Handler { return http.HandlerFunc(s.serve) }

// BootID is sent in the SSE hello so the UI can detect a restart.
func (s *Server) BootID() string { return s.bootID }

func (s *Server) serve(w http.ResponseWriter, r *http.Request) {
	if !s.allowed(r) {
		http.Error(w, "forbidden", http.StatusForbidden)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodPost && r.Method != http.MethodPut &&
		r.Method != http.MethodDelete && r.Method != http.MethodPatch {
		w.Header().Set("Allow", "GET")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	p := r.URL.Path
	if p == "/api" || strings.HasPrefix(p, "/api/") {
		if path.Clean(p) != p {
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
			return
		}
		s.api.ServeHTTP(w, r)
		return
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	s.static(w, r)
}

// Addr is the bound loopback address; valid after Ready is closed.
func (s *Server) Addr() string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return net.JoinHostPort("127.0.0.1", strconv.Itoa(s.port))
}

// Ready is closed once the listener is bound.
func (s *Server) Ready() <-chan struct{} { return s.ready }

// Listen binds 127.0.0.1:port and serves until ctx is cancelled. It first probes the port
// (macOS lets a 127.0.0.1 bind succeed over a 0.0.0.0 holder) and fails with
// "port N is already in use by PID p (name)". With cfg.Tailscale it also exposes the port
// through `tailscale serve`; tailscale problems are logged, never fatal.
func (s *Server) Listen(ctx context.Context) error {
	port := s.cfg.Port
	if port > 0 {
		if c, err := net.DialTimeout("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)), time.Second); err == nil {
			c.Close()
			return fmt.Errorf("port %d is already in use%s", port, holderOf(ctx, port))
		}
	}
	ln, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.port = ln.Addr().(*net.TCPAddr).Port
	s.mu.Unlock()

	var tsOff func()
	if s.cfg.Tailscale {
		off, err := s.tailscaleUp(ctx)
		if err != nil {
			s.logf("tailscale: %v", err)
		} else {
			tsOff = off
		}
	}
	srv := &http.Server{Handler: s.Handler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 120 * time.Second}
	errc := make(chan error, 1)
	go func() { errc <- srv.Serve(ln) }()
	s.readyOne.Do(func() { close(s.ready) })

	var serveErr error
	select {
	case <-ctx.Done():
	case serveErr = <-errc:
	}
	s.quitOne.Do(func() { close(s.quit) }) // ends SSE streams
	sctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := srv.Shutdown(sctx); err != nil {
		_ = srv.Close()
	}
	if tsOff != nil {
		tsOff()
	}
	if serveErr != nil && !errors.Is(serveErr, http.ErrServerClosed) {
		return serveErr
	}
	return nil
}

// holderOf renders " by PID p (name)" using lsof, or "" when unknown.
func holderOf(ctx context.Context, port int) string {
	r := execx.Run(ctx, []string{"lsof", "-nP", "-iTCP:" + strconv.Itoa(port), "-sTCP:LISTEN", "-Fpc"}, execx.Opts{Timeout: 3 * time.Second})
	var pid, name string
	for _, l := range strings.Split(string(r.Stdout), "\n") {
		switch {
		case strings.HasPrefix(l, "p") && pid == "":
			pid = l[1:]
		case strings.HasPrefix(l, "c") && name == "":
			name = l[1:]
		}
	}
	if pid == "" {
		return ""
	}
	return fmt.Sprintf(" by PID %s (%s)", pid, name)
}
