// Package gh is the thin wrapper over the `gh` CLI: JSON and GraphQL calls, the sign-in cache, the
// CI snapshot, review threads, popups, PR/issue writes and the `setu ci` / `setu threads` verbs.
// gh is the only GitHub client; no token is ever handled here.
package gh

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
)

// Default timeouts (G§1).
const (
	JSONTimeout    = 120 * time.Second
	GraphQLTimeout = 60 * time.Second
)

// Client runs gh. Args never include the leading "gh".
type Client interface {
	Run(ctx context.Context, args []string, o execx.Opts) execx.Result
	// JSON runs gh and decodes stdout into v (G§ gh_json). A non-zero exit returns the Result and a
	// non-nil error (an *errs.Error, Upstream) and leaves v untouched. Stdout that is not JSON (a bare
	// --jq scalar) is stored as the stripped string when v is a *string or *any; empty stdout is null.
	// timeout 0 means JSONTimeout.
	JSON(ctx context.Context, args []string, timeout time.Duration, v any) (execx.Result, error)
	// GraphQL runs `gh api graphql`. String variables are sent with -f, numbers and bools with -F.
	// The whole response envelope ({data, errors}) is decoded into v even when the call returns an
	// error. The error is nil, ErrRateLimited (wrapped in a *GQLError), or a *GQLError.
	GraphQL(ctx context.Context, query string, vars map[string]any, v any) (RateLimit, execx.Result, error)
}

// RateLimit is data.rateLimit of a GraphQL response. Zero ResetAt means the response had none.
type RateLimit struct {
	Cost, Remaining int
	ResetAt         time.Time
}

// ErrRateLimited marks a rate-limited GraphQL call: gh's stderr says "rate limit", or the
// response carries errors[].type == "RATE_LIMITED". The payload text is never matched.
var ErrRateLimited = errors.New("rate limited")

// GQLItem is one entry of a response's errors array.
type GQLItem struct {
	Type    string `json:"type"`
	Message string `json:"message"`
	Path    []any  `json:"path"`
}

// GQLError is a failed GraphQL call. Msg is at most 200 chars.
type GQLError struct {
	Msg         string
	Items       []GQLItem
	RateLimited bool
}

func (e *GQLError) Error() string { return e.Msg }

// Is makes errors.Is(err, ErrRateLimited) work.
func (e *GQLError) Is(target error) bool { return target == ErrRateLimited && e.RateLimited }

// RunFunc is the raw process runner behind a Client.
type RunFunc func(ctx context.Context, args []string, o execx.Opts) execx.Result

type client struct{ run RunFunc }

// New is the real client: it execs `gh`.
func New() Client {
	return Wrap(func(ctx context.Context, args []string, o execx.Opts) execx.Result {
		return execx.Run(ctx, append([]string{"gh"}, args...), o)
	})
}

// Wrap builds a Client on top of a runner (tests script the runner).
func Wrap(run RunFunc) Client { return &client{run: run} }

func (c *client) Run(ctx context.Context, args []string, o execx.Opts) execx.Result {
	return c.run(ctx, args, o)
}

func (c *client) JSON(ctx context.Context, args []string, timeout time.Duration, v any) (execx.Result, error) {
	if timeout <= 0 {
		timeout = JSONTimeout
	}
	res := c.run(ctx, args, execx.Opts{Timeout: timeout})
	if res.Code != 0 {
		return res, errs.Upstream("%s", orDefault(res.LastLine(), "gh failed"))
	}
	return res, parseOut(res, v)
}

// parseOut decodes a successful result's stdout like gh_json.
func parseOut(res execx.Result, v any) error {
	raw := bytes.TrimSpace(res.Stdout)
	if len(raw) == 0 {
		raw = []byte("null")
	}
	if v == nil {
		return nil
	}
	if err := json.Unmarshal(raw, v); err != nil {
		var te *json.UnmarshalTypeError
		if errors.As(err, &te) {
			return errs.Upstream("unexpected gh output: %s", te.Error())
		}
		switch p := v.(type) { // a bare --jq scalar is not JSON
		case *string:
			*p = string(raw)
		case *any:
			*p = string(raw)
		default:
			return errs.Upstream("gh did not return JSON")
		}
	}
	return nil
}

// runJSONIn is JSON with a working directory.
func runJSONIn(ctx context.Context, c Client, args []string, dir string, v any) (execx.Result, error) {
	res := c.Run(ctx, args, execx.Opts{Dir: dir, Timeout: JSONTimeout})
	if res.Code != 0 {
		return res, errs.Upstream("%s", orDefault(res.LastLine(), "gh failed"))
	}
	return res, parseOut(res, v)
}

func (c *client) GraphQL(ctx context.Context, query string, vars map[string]any, v any) (RateLimit, execx.Result, error) {
	args := []string{"api", "graphql", "-f", "query=" + query}
	keys := make([]string, 0, len(vars))
	for k := range vars {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		switch x := vars[k].(type) {
		case nil:
		case string:
			args = append(args, "-f", k+"="+x)
		default:
			args = append(args, "-F", fmt.Sprintf("%s=%v", k, x))
		}
	}
	res := c.run(ctx, args, execx.Opts{Timeout: GraphQLTimeout})

	var env struct {
		Data *struct {
			RateLimit *struct {
				Cost      int    `json:"cost"`
				Remaining int    `json:"remaining"`
				ResetAt   string `json:"resetAt"`
			} `json:"rateLimit"`
		} `json:"data"`
		Errors []GQLItem `json:"errors"`
	}
	parseErr := json.Unmarshal(bytes.TrimSpace(res.Stdout), &env)
	if parseErr == nil && v != nil {
		_ = json.Unmarshal(bytes.TrimSpace(res.Stdout), v)
	}
	var rl RateLimit
	if parseErr == nil && env.Data != nil && env.Data.RateLimit != nil {
		rl.Cost, rl.Remaining = env.Data.RateLimit.Cost, env.Data.RateLimit.Remaining
		if t, err := time.Parse(time.RFC3339, env.Data.RateLimit.ResetAt); err == nil {
			rl.ResetAt = t
		}
	}

	limited := strings.Contains(strings.ToLower(string(res.Stderr)), "rate limit")
	for _, e := range env.Errors {
		if e.Type == "RATE_LIMITED" {
			limited = true
		}
	}
	switch {
	case limited:
		return rl, res, &GQLError{Msg: "rate limited", Items: env.Errors, RateLimited: true}
	case parseErr != nil || res.Code != 0 || len(env.Errors) > 0:
		msg := ""
		if len(env.Errors) > 0 {
			b, _ := json.Marshal(env.Errors)
			msg = string(b)
		} else {
			msg = res.LastLine()
		}
		if msg == "" {
			msg = "gh did not return a GraphQL response"
		}
		return rl, res, &GQLError{Msg: trunc(msg, 200), Items: env.Errors}
	}
	return rl, res, nil
}

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

// trunc cuts s to n characters (not bytes), like Python's s[:n].
func trunc(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

// tail keeps the last n characters, like Python's s[-n:].
func tail(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[len(r)-n:])
}
