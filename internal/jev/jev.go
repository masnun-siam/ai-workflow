// Package jev is the one place that runs the external `jev` CLI (typed choice, score and noul
// questions): redaction, a cache for three points, and an hourly call ceiling.
package jev

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log"
	"os/exec"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
)

const (
	Model      = "jev-1.14.0" // pinned: an alias moves without notice
	Timeout    = 8 * time.Second
	MaxChars   = 4000
	MaxEntries = 2000
	MaxAge     = 7 * 24 * time.Hour
	Ceiling    = 500
	Window     = time.Hour
	FlushEvery = 60 * time.Second
)

// Cached points; every other point is never cached, counted or refused.
var cached = map[string]bool{"urgency": true, "readiness": true, "duplicate": true}

// Answer is the result of Ask. Status is ok, off, missing, no_answer, failed (Exit set),
// unreadable or capped.
type Answer struct {
	Status     string  `json:"status"`
	Choice     string  `json:"choice,omitempty"`
	P          float64 `json:"p,omitempty"`
	Score      float64 `json:"score,omitempty"`
	Confidence float64 `json:"confidence,omitempty"`
	Exit       int     `json:"exit,omitempty"`
}

type entry struct {
	Answer      Answer   `json:"answer"`
	Probability *float64 `json:"probability"`
	At          float64  `json:"at"`
}

// Client wraps the jev CLI.
type Client struct {
	h       *home.Home
	enabled func() bool

	now  func() time.Time
	logf func(string, ...any)
	look func(string) (string, error)

	mu          sync.Mutex // never held while jev runs
	cache       map[string]entry
	dirty       bool
	server      bool
	windowStart time.Time
	windowCalls int
}

// New builds a client. enabled reports Settings "Use jev"; it is called on every use.
func New(h *home.Home, enabled func() bool) *Client {
	return &Client{h: h, enabled: enabled, now: time.Now, logf: log.Printf, look: exec.LookPath}
}

// Status is off (switch off), missing (not on PATH) or ok. It never runs jev.
func (c *Client) Status() string {
	if c.enabled != nil && !c.enabled() {
		return "off"
	}
	if _, err := c.look("jev"); err != nil {
		return "missing"
	}
	return "ok"
}

var (
	rePrefix = regexp.MustCompile(`\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-|xox[abprs]-|AIza|npm_)[A-Za-z0-9_-]{16,}`)
	reAWS    = regexp.MustCompile(`\b(?:AKIA|ASIA)[A-Z0-9]{16}`)
	reAuth   = regexp.MustCompile(`(?i)(\bauthorization\s*:[ \t]*)[^\n]*`)
	reBearer = regexp.MustCompile(`(?i)(\bbearer\s+)\S+`)
	reAssign = regexp.MustCompile(`(?i)(\b[\w.-]*(?:key|token|secret)[\w.-]*\s*[=:]\s*)[^\s]+`)
	reHex    = regexp.MustCompile(`[0-9a-fA-F]{32,}`)
	reB64    = regexp.MustCompile(`[A-Za-z0-9+/_-]{40,}={0,2}`)
)

const redacted = "[redacted]"

// Redact masks secrets before text is sent to jev.
func Redact(text string) string {
	for _, rx := range []*regexp.Regexp{rePrefix, reAWS, reHex, reB64} {
		text = rx.ReplaceAllString(text, redacted)
	}
	for _, rx := range []*regexp.Regexp{reAuth, reBearer, reAssign} {
		text = rx.ReplaceAllString(text, "${1}"+redacted)
	}
	return text
}

// cut keeps the first n characters (runes).
func cut(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// sentKey is the redacted, cut text that is sent and its cache key; shared by Ask and Peek.
func sentKey(point, kind, question, text string, options map[string]string, levels []string) (string, string) {
	sent := cut(Redact(text), MaxChars)
	// json.Marshal sorts map keys, matching Python's sort_keys.
	b, _ := json.Marshal([]any{kind, question, options, levels, sent})
	sum := sha256.Sum256(b)
	return sent, point + ":" + hex.EncodeToString(sum[:])
}

func (c *Client) cachePath() string { return c.h.Path("jev_cache.json") }

func (c *Client) ts(t time.Time) float64 { return float64(t.UnixNano()) / 1e9 }

func (c *Client) fresh(e entry) bool { return c.ts(c.now())-e.At < MaxAge.Seconds() }

// load reads the cache on first use. Call with mu held.
func (c *Client) load() map[string]entry {
	if c.cache == nil {
		c.cache = map[string]entry{}
		var m map[string]entry
		if err := home.ReadJSON(c.cachePath(), &m); err == nil && m != nil {
			c.cache = m
		}
	}
	return c.cache
}

// Peek reads the cache only: nil on a miss, when jev is off or missing. It never runs jev,
// never counts against the ceiling and never writes.
func (c *Client) Peek(point, kind, question, text string, options map[string]string, levels []string) *Answer {
	if c.Status() != "ok" {
		return nil
	}
	_, key := sentKey(point, kind, question, text, options, levels)
	c.mu.Lock()
	defer c.mu.Unlock()
	if hit, ok := c.load()[key]; ok && c.fresh(hit) {
		a := hit.Answer
		a.Status = "ok"
		return &a
	}
	return nil
}

// Ask runs one question. It never errors and never runs jev while the switch is off.
func (c *Client) Ask(ctx context.Context, point, kind, question, text string, options map[string]string, levels []string) Answer {
	if s := c.Status(); s != "ok" {
		return Answer{Status: s}
	}
	sent, key := sentKey(point, kind, question, text, options, levels)
	if !cached[point] {
		return c.run(ctx, point, kind, question, sent, options, levels)
	}
	c.mu.Lock()
	if c.server {
		if hit, ok := c.load()[key]; ok && c.fresh(hit) {
			c.mu.Unlock()
			a := hit.Answer
			a.Status = "ok"
			return a
		}
	}
	now := c.now()
	if now.Sub(c.windowStart) >= Window {
		c.windowStart, c.windowCalls = now, 0
	}
	if c.windowCalls >= Ceiling {
		c.mu.Unlock()
		return Answer{Status: "capped"}
	}
	c.windowCalls++ // a failed call spent an invocation too
	c.mu.Unlock()

	a := c.run(ctx, point, kind, question, sent, options, levels)
	if a.Status == "ok" && c.server {
		c.mu.Lock()
		cache := c.load()
		var prob *float64
		if kind == "noul" || kind == "choice" {
			p := a.P
			prob = &p
		} else {
			p := a.Confidence
			prob = &p
		}
		stored := a
		stored.Status = ""
		cache[key] = entry{Answer: stored, Probability: prob, At: c.ts(c.now())}
		for len(cache) > MaxEntries {
			oldest, at := "", 0.0
			for k, e := range cache {
				if oldest == "" || e.At < at {
					oldest, at = k, e.At
				}
			}
			delete(cache, oldest)
		}
		c.dirty = true
		c.mu.Unlock()
	}
	return a
}

// Spent is the number of counted calls in the current hour.
func (c *Client) Spent() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.now().Sub(c.windowStart) < Window {
		return c.windowCalls
	}
	return 0
}

func (c *Client) fail(point, status string, exit int) Answer {
	c.logf("jev %s: %s", point, status)
	return Answer{Status: status, Exit: exit}
}

func (c *Client) run(ctx context.Context, point, kind, question, sent string, options map[string]string, levels []string) Answer {
	bin, err := c.look("jev")
	if err != nil {
		return c.fail(point, "no_answer", 0)
	}
	argv := []string{bin, kind, question, "--model", Model, "--state-file", "-", "-o", "json"}
	keys := make([]string, 0, len(options))
	for k := range options {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		argv = append(argv, "--option", k+"="+options[k])
	}
	for _, l := range levels {
		argv = append(argv, "--level", l)
	}
	r := execx.Run(ctx, argv, execx.Opts{Stdin: strings.NewReader(sent), Timeout: Timeout})
	if r.Code == 127 || r.Code == 124 {
		return c.fail(point, "no_answer", 0)
	}
	if r.Code != 0 {
		return c.fail(point, "failed", r.Code)
	}
	return c.parse(point, kind, r.Stdout)
}

func (c *Client) parse(point, kind string, out []byte) Answer {
	var m map[string]json.RawMessage
	dec := json.NewDecoder(bytes.NewReader(out))
	if err := dec.Decode(&m); err != nil || m == nil {
		return c.fail(point, "unreadable", 0)
	}
	num := func(raw json.RawMessage) (float64, bool) {
		var f float64
		if json.Unmarshal(raw, &f) == nil {
			return f, true
		}
		var s string // Python's float() also accepts numeric strings
		if json.Unmarshal(raw, &s) == nil {
			return parseFloat(s)
		}
		return 0, false
	}
	switch kind {
	case "noul":
		p, ok := num(m["noul"])
		if !ok {
			return c.fail(point, "unreadable", 0)
		}
		return Answer{Status: "ok", P: p}
	case "choice":
		var choice string
		if json.Unmarshal(m["choice"], &choice) != nil || m["choice"] == nil {
			return c.fail(point, "unreadable", 0)
		}
		var probs map[string]json.RawMessage
		_ = json.Unmarshal(m["probabilities"], &probs)
		raw, has := probs[choice]
		if !has {
			raw = m["confidence"]
		}
		p := 0.0
		if raw != nil {
			var ok bool
			if p, ok = num(raw); !ok {
				return c.fail(point, "unreadable", 0)
			}
		}
		return Answer{Status: "ok", Choice: choice, P: p}
	default:
		sc, ok := num(m["score"])
		if !ok {
			return c.fail(point, "unreadable", 0)
		}
		cf := 0.0
		if raw, has := m["confidence"]; has {
			if cf, ok = num(raw); !ok {
				return c.fail(point, "unreadable", 0)
			}
		}
		return Answer{Status: "ok", Score: sc, Confidence: cf}
	}
}

// Flush writes the cache if it changed, dropping expired entries. A failed write stays dirty.
func (c *Client) Flush() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.dirty || c.cache == nil {
		return
	}
	for k, e := range c.cache {
		if !c.fresh(e) {
			delete(c.cache, k)
		}
	}
	if err := home.WriteJSON(c.cachePath(), c.cache); err != nil {
		c.logf("jev cache: flush failed")
		return
	}
	c.dirty = false
}

// Start turns on the cache (server mode) and flushes it every 60 s until ctx ends. It returns at once.
func (c *Client) Start(ctx context.Context) {
	c.mu.Lock()
	c.server = true
	c.mu.Unlock()
	go func() {
		t := time.NewTicker(FlushEvery)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				c.Flush()
				return
			case <-t.C:
				func() {
					defer func() {
						if r := recover(); r != nil {
							c.logf("jev cache flush: %v", r)
						}
					}()
					c.Flush()
				}()
			}
		}
	}()
}
