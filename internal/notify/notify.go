// Package notify composes and delivers notifications: the in-app toast (SSE), ntfy, macOS banners
// and Web Push. Delivery never blocks the caller and never raises.
package notify

import (
	"context"
	"fmt"
	"log"
	"os"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
)

// Link points at the issue a note is about.
type Link struct {
	Owner string `json:"owner"`
	Repo  string `json:"repo"`
	Issue int    `json:"issue"`
}

// Note is one notification. Text is the first-line body of grind and board events; Question and
// Recommended feed `waiting`; Error feeds `failed`. Role "away-answerer" never notifies.
type Note struct {
	ID, Repo, Command, Text, SessionID, Question, Recommended, Error, Step string
	Role                                                                   string
	Link                                                                   *Link
}

// Service delivers notifications.
type Service struct {
	h   *home.Home
	bus *events.Bus

	away   atomic.Value // func() bool
	toasts atomic.Int64
	wg     sync.WaitGroup

	getenv func(string) string
	goos   string
	now    func() time.Time
	logf   func(string, ...any)
	tnOnce sync.Once
	tn     string
}

// New builds the service. st is the settings store; notification config lives in ui.json, which
// the service reads itself (so st may be nil).
func New(h *home.Home, st any, bus *events.Bus) *Service {
	_ = st
	return &Service{h: h, bus: bus, getenv: os.Getenv, goos: runtime.GOOS, now: time.Now, logf: log.Printf}
}

func (s *Service) warnf(format string, a ...any) { s.logf("notify: "+format, a...) }

// SetAway installs the Away mode probe.
func (s *Service) SetAway(active func() bool) { s.away.Store(active) }

func (s *Service) awayActive() bool {
	f, _ := s.away.Load().(func() bool)
	return f != nil && f()
}

// Wait blocks until the deliveries in flight finish or d passes.
func (s *Service) Wait(d time.Duration) {
	done := make(chan struct{})
	go func() { s.wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(d):
	}
}

func suppressed(event string, n Note) bool {
	if n.Role == "away-answerer" {
		return true
	}
	if event == "done" {
		// A grind round ends its session every time; grind-done/grind-paused is the signal.
		if n.Step == "pr-grind" || skillOf(n.Command) == "pr-grind" || strings.HasPrefix(n.Command, "Start the review grind for PR ") {
			return true
		}
	}
	return false
}

// Notify routes one event to every channel its matrix cell turns on. It returns at once.
func (s *Service) Notify(event string, n Note) {
	if suppressed(event, n) {
		return
	}
	switch event {
	case "waiting", "failed", "grind-paused":
		if s.awayActive() { // the single afk push at the end sums it up
			return
		}
	}
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer func() {
			if r := recover(); r != nil {
				s.warnf("notification failed (%s): %v", event, r)
			}
		}()
		s.deliver(event, n)
	}()
}

func level(event string) string {
	switch event {
	case "failed":
		return "error"
	case "waiting", "panel-cap", "grind-paused", "dispatch":
		return "warn"
	}
	return "info"
}

func (s *Service) toast(event, title, body, path string) {
	if s.bus == nil {
		return
	}
	s.bus.Publish(events.TToast, map[string]any{
		"id": s.toasts.Add(1), "event": event, "title": title, "body": body, "path": path, "level": level(event),
	})
}

func (s *Service) deliver(event string, n Note) {
	cfg := s.LoadConfig()
	cells := cfg.cellsFor(event)
	h, text := Compose(event, n, cfg.PublicURL)
	path := ClickPath(event, n)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if cells["browser"] {
		s.toast(event, h["Title"], text, path)
	}
	var wg sync.WaitGroup
	run := func(f func()) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					s.warnf("channel failed (%s): %v", event, r)
				}
			}()
			f()
		}()
	}
	if cells["ntfy"] {
		run(func() { s.sendNtfy(ctx, cfg, h, text) })
	}
	if cells["mac"] {
		run(func() { s.sendMac(ctx, h["Title"], text, h["Click"]) })
	}
	if cells["push"] {
		urg := "high"
		if h["Priority"] == "default" {
			urg = "normal"
		}
		run(func() {
			s.sendPush(ctx, pushPayload{Event: event, Title: h["Title"], Body: text, Path: path, Tag: fmt.Sprintf("setu-%s-%s", event, sessionID(n))}, urg)
		})
	}
	wg.Wait()
}

// Test sends one sample on channel (ntfy, mac or push) alone, ignoring the matrix and Away mode.
// The error never contains the URL (it holds the topic).
func (s *Service) Test(ctx context.Context, channel string) error {
	cfg := s.LoadConfig()
	title, body := "setu: test notification", "This is a test from setu."
	link := ""
	if cfg.PublicURL != "" {
		link = strings.TrimRight(cfg.PublicURL, "/") + "/#/settings/notifications"
	}
	var msg string
	switch channel {
	case "mac":
		msg = s.sendMac(ctx, title, body, link)
	case "ntfy":
		h := Headers{"Title": title, "Priority": "default", "Tags": "bell"}
		if link != "" {
			h["Click"] = link
		}
		msg = s.sendNtfy(ctx, cfg, h, body)
	case "push":
		msg = s.sendPush(ctx, pushPayload{Event: "test", Title: title, Body: body, Path: "#/settings/notifications", Tag: "setu-test"}, "normal")
	default:
		return fmt.Errorf("channel must be push, mac or ntfy")
	}
	if msg != "" {
		return fmt.Errorf("%s", msg)
	}
	return nil
}
