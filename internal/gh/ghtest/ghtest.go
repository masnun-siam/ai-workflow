// Package ghtest is a scripted gh.Client for tests of packages that use gh without the real binary.
package ghtest

import (
	"context"
	"strings"
	"sync"

	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh"
)

// Rule answers a call. Match is a prefix of the args; Contains (optional) must be a substring of
// the args joined by a space. The first matching rule wins; Once rules are used up after one call.
type Rule struct {
	Prefix   []string
	Contains string
	Stdout   string
	Stderr   string
	Code     int
	Once     bool
	// Func, when set, computes the result from the args (Stdout/Stderr/Code are then ignored).
	Func func(args []string) execx.Result

	used bool
}

// Client is the scripted client. It records every call's args in Calls.
type Client struct {
	gh.Client
	mu    sync.Mutex
	rules []*Rule
	Calls [][]string
}

// New builds a scripted client. An unmatched call answers exit 99 / "ghtest: no rule".
func New(rules ...Rule) *Client {
	c := &Client{}
	for i := range rules {
		r := rules[i]
		c.rules = append(c.rules, &r)
	}
	c.Client = gh.Wrap(c.run)
	return c
}

// Add appends a rule.
func (c *Client) Add(r Rule) {
	c.mu.Lock()
	c.rules = append(c.rules, &r)
	c.mu.Unlock()
}

// Reset drops every rule and recorded call.
func (c *Client) Reset() {
	c.mu.Lock()
	c.rules, c.Calls = nil, nil
	c.mu.Unlock()
}

// CallsMatching returns the recorded calls whose args start with prefix.
func (c *Client) CallsMatching(prefix ...string) [][]string {
	c.mu.Lock()
	defer c.mu.Unlock()
	var out [][]string
	for _, a := range c.Calls {
		if hasPrefix(a, prefix) {
			out = append(out, a)
		}
	}
	return out
}

func hasPrefix(a, p []string) bool {
	if len(a) < len(p) {
		return false
	}
	for i := range p {
		if a[i] != p[i] {
			return false
		}
	}
	return true
}

func (c *Client) run(_ context.Context, args []string, _ execx.Opts) execx.Result {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.Calls = append(c.Calls, append([]string(nil), args...))
	joined := strings.Join(args, " ")
	for _, r := range c.rules {
		if r.used || !hasPrefix(args, r.Prefix) || (r.Contains != "" && !strings.Contains(joined, r.Contains)) {
			continue
		}
		if r.Once {
			r.used = true
		}
		if r.Func != nil {
			return r.Func(args)
		}
		return execx.Result{Code: r.Code, Stdout: []byte(r.Stdout), Stderr: []byte(r.Stderr)}
	}
	return execx.Result{Code: 99, Stderr: []byte("ghtest: no rule")}
}
