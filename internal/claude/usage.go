package claude

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/settings"
)

const (
	usageURL     = "https://api.anthropic.com/api/oauth/usage"
	usagePoll    = 300 * time.Second
	usageRetry   = 900 * time.Second
	usageTick    = 5 * time.Second
	keychainWait = 15 * time.Second
	fetchWait    = 15 * time.Second
	maxBody      = 1 << 20
)

// Meter is one usage window; null when the API did not report it.
type Meter struct {
	Pct      float64 `json:"pct"`
	ResetsAt *string `json:"resets_at"`
}

// Limit mirrors sessions.Limit; the views fill it in.
type Limit struct {
	LimitedUntil int64         `json:"limited_until,omitempty"`
	Warning      *LimitWarning `json:"warning,omitempty"`
}

type LimitWarning struct {
	Type        string  `json:"type"`
	Utilization float64 `json:"utilization"`
}

// AccountUsage is the API §4 type. At is the epoch seconds of the last good fetch.
type AccountUsage struct {
	Label    string  `json:"label"`
	Cmd      string  `json:"cmd"`
	FiveHour *Meter  `json:"five_hour"`
	SevenDay *Meter  `json:"seven_day"`
	At       *int64  `json:"at"`
	Error    *string `json:"error"`
	Limit    Limit   `json:"limit"`
}

type entry struct {
	five, seven *Meter
	at          *int64
	err         *string
	next        time.Time
}

// Usage polls the 5 h / 7 d plan usage of every account, only while a UI is present (S§3.2).
// The OAuth token is read from the macOS Keychain and is never refreshed here (that would
// rotate the refresh token under the CLI) nor logged.
type Usage struct {
	st      *settings.Store
	bus     *events.Bus
	present func() bool

	// injectable for tests
	url      string
	client   *http.Client
	keychain func(ctx context.Context, service string) ([]byte, error)
	now      func() time.Time

	mu    sync.Mutex
	cache map[string]*entry
}

func NewUsage(st *settings.Store, bus *events.Bus, present func() bool) *Usage {
	u := &Usage{st: st, bus: bus, present: present, url: usageURL, now: time.Now, cache: map[string]*entry{},
		client: &http.Client{Timeout: fetchWait}}
	u.keychain = readKeychain
	return u
}

func readKeychain(ctx context.Context, service string) ([]byte, error) {
	r := execx.Run(ctx, []string{"security", "find-generic-password", "-s", service, "-w"}, execx.Opts{Timeout: keychainWait})
	if r.Code != 0 {
		return nil, os.ErrPermission
	}
	return r.Stdout, nil
}

// KeychainService is the Keychain item holding an account's credentials: Claude Code suffixes
// it with a hash of a non-default config dir.
func KeychainService(cmd string) string {
	d := ConfigDir(cmd)
	if u, err := os.UserHomeDir(); err == nil && d == filepath.Join(u, ".claude") {
		return "Claude Code-credentials"
	}
	return "Claude Code-credentials-" + shaHex8(d)
}

type fetched struct {
	five, seven *Meter
	err         string
}

func window(raw json.RawMessage) *Meter {
	var w struct {
		Utilization *float64        `json:"utilization"`
		ResetsAt    json.RawMessage `json:"resets_at"`
	}
	if json.Unmarshal(raw, &w) != nil || w.Utilization == nil {
		return nil
	}
	m := &Meter{Pct: *w.Utilization}
	if s, ok := rawStr(w.ResetsAt); ok {
		m.ResetsAt = &s
	}
	return m
}

func (u *Usage) fetch(ctx context.Context, cmd string) fetched {
	out, err := u.keychain(ctx, KeychainService(cmd))
	if err != nil {
		return fetched{err: "usage unavailable (keychain read denied or no login)"}
	}
	var cred struct {
		OAuth struct {
			AccessToken string  `json:"accessToken"`
			ExpiresAt   float64 `json:"expiresAt"`
		} `json:"claudeAiOauth"`
	}
	if json.Unmarshal(out, &cred) != nil || cred.OAuth.AccessToken == "" {
		log.Printf("claude usage: %s: unreadable credentials", cmd)
		return fetched{err: "usage unavailable"}
	}
	if cred.OAuth.ExpiresAt/1000 < float64(u.now().Unix()) {
		return fetched{err: "re-login needed"}
	}
	req, err := http.NewRequestWithContext(ctx, "GET", u.url, nil)
	if err != nil {
		return fetched{err: "usage unavailable"}
	}
	req.Header.Set("Authorization", "Bearer "+cred.OAuth.AccessToken)
	req.Header.Set("anthropic-beta", "oauth-2025-04-20")
	resp, err := u.client.Do(req)
	if err != nil {
		log.Printf("claude usage: %s: request failed", cmd) // never the token or the response
		return fetched{err: "usage unavailable"}
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBody))
	var data map[string]json.RawMessage
	if err != nil || resp.StatusCode/100 != 2 || json.Unmarshal(body, &data) != nil || data == nil {
		log.Printf("claude usage: %s: HTTP %d", cmd, resp.StatusCode)
		return fetched{err: "usage unavailable"}
	}
	return fetched{five: window(data["five_hour"]), seven: window(data["seven_day"])}
}

// Refresh fetches every account whose next fetch is due and publishes usage{kind:"usage"} on a change.
func (u *Usage) Refresh(ctx context.Context) {
	now := u.now()
	changed := false
	live := map[string]bool{}
	for _, a := range u.st.Accounts() {
		live[a.Cmd] = true
		u.mu.Lock()
		e := u.cache[a.Cmd]
		due := e == nil || !e.next.After(now)
		u.mu.Unlock()
		if !due {
			continue
		}
		res := u.fetch(ctx, a.Cmd)
		u.mu.Lock()
		if e == nil {
			e = &entry{}
			u.cache[a.Cmd] = e
		}
		if res.err != "" { // keep the last good numbers, flagged stale by error
			msg := res.err
			e.err = &msg
			e.next = now.Add(usageRetry)
		} else {
			at := now.Unix()
			e.five, e.seven, e.at, e.err = res.five, res.seven, &at, nil
			e.next = now.Add(usagePoll)
		}
		u.mu.Unlock()
		changed = true
	}
	u.mu.Lock()
	for cmd := range u.cache {
		if !live[cmd] {
			delete(u.cache, cmd)
		}
	}
	u.mu.Unlock()
	if changed && u.bus != nil {
		u.bus.Publish(events.TUsage, map[string]any{"kind": "usage"})
	}
}

// Start ticks every 5 s and refreshes only while a UI is present. It returns at once.
func (u *Usage) Start(ctx context.Context) {
	go func() {
		t := time.NewTicker(usageTick)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if u.present != nil && u.present() {
					u.tick(ctx)
				}
			}
		}
	}()
}

func (u *Usage) tick(ctx context.Context) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("claude usage: tick panic: %v", r)
		}
	}()
	u.Refresh(ctx)
}

// Snapshot is the latest usage of every saved account, keyed by account cmd.
func (u *Usage) Snapshot() map[string]AccountUsage {
	out := map[string]AccountUsage{}
	u.mu.Lock()
	defer u.mu.Unlock()
	for _, a := range u.st.Accounts() {
		au := AccountUsage{Label: a.Label, Cmd: a.Cmd}
		if e := u.cache[a.Cmd]; e != nil {
			au.FiveHour, au.SevenDay, au.At = e.five, e.seven, e.at
			if e.err != nil {
				s := *e.err
				au.Error = &s
			}
		}
		out[a.Cmd] = au
	}
	return out
}

func shaHex8(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])[:8]
}
