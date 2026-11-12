package gh

import (
	"context"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
)

// AuthTTL is how long a sign-in answer is fresh (G§1.3).
const (
	AuthTTL     = 60 * time.Second
	authTimeout = 60 * time.Second
)

// Auth is the `gh` sign-in state.
type Auth struct {
	OK    bool   `json:"ok"`
	Login string `json:"login"`
	Error string `json:"error"`
}

// Solo reports whether the repo owner is the signed-in user (a PR needs no approval then).
func (a Auth) Solo(owner string) bool {
	return a.Login != "" && strings.EqualFold(owner, a.Login)
}

// AuthCache caches `gh api user --jq .login`. A cold cache blocks on the call, a stale one is served
// while one background refresh runs, and a refresh that timed out keeps the previous value (a slow
// network is not a sign-out).
type AuthCache struct {
	c        Client
	now      func() time.Time
	mu       sync.Mutex
	value    *Auth
	at       time.Time
	busy     bool
	onChange func(Auth)
}

func NewAuth(c Client) *AuthCache { return &AuthCache{c: c, now: time.Now} }

// OnChange registers fn, called (off the caller's goroutine) when the signed-in state flips
// (ok, or login, changes). The first answer counts as a flip.
func (a *AuthCache) OnChange(fn func(Auth)) {
	a.mu.Lock()
	a.onChange = fn
	a.mu.Unlock()
}

func (a *AuthCache) Get(ctx context.Context) Auth {
	a.mu.Lock()
	if a.value != nil {
		v := *a.value
		if a.now().Sub(a.at) < AuthTTL {
			a.mu.Unlock()
			return v
		}
		if !a.busy {
			a.busy = true
			go a.refresh(context.WithoutCancel(ctx))
		}
		a.mu.Unlock()
		return v
	}
	a.mu.Unlock()
	return a.refresh(ctx)
}

func (a *AuthCache) refresh(ctx context.Context) Auth {
	v := check(ctx, a.c)
	a.mu.Lock()
	prev := a.value
	if prev != nil && strings.HasPrefix(v.Error, "timed out") {
		v = *prev
	}
	a.value, a.at, a.busy = &v, a.now(), false
	fn := a.onChange
	changed := prev == nil || prev.OK != v.OK || prev.Login != v.Login
	a.mu.Unlock()
	if changed && fn != nil {
		go fn(v)
	}
	return v
}

func check(ctx context.Context, c Client) Auth {
	r := c.Run(ctx, []string{"api", "user", "--jq", ".login"}, execx.Opts{Timeout: authTimeout})
	login := strings.TrimSpace(string(r.Stdout))
	if r.Code == 0 && login != "" {
		return Auth{OK: true, Login: login}
	}
	msg := firstLine(string(r.Stderr))
	if msg == "" {
		msg = firstLine(string(r.Stdout))
	}
	if msg == "" {
		msg = "gh did not answer"
	}
	return Auth{Error: trunc(msg, 200)}
}

// firstLine is the first non-empty line of the stripped text.
func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return ""
	}
	line, _, _ := strings.Cut(s, "\n")
	return strings.TrimSpace(line)
}
