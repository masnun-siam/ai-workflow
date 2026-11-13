package claude

import (
	"encoding/json"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

// Event is one parsed stream-json event. Kinds: text, tool, result, session_id, limit,
// guard_ask, prompt_blocked, hook.
type Event struct {
	Kind      string
	Text      string
	Name      string // tool name, or hook name
	Error     string // first error of an erroring result
	Reason    string // prompt_blocked
	SessionID string
	Model     string
	LimitType string
	HookEvent string
	Input     json.RawMessage // tool input
	Info      json.RawMessage // limit: the whole rate_limit_info object
	Cost      *float64
	IsError   bool
	Tokens    *Tokens
	ResetsAt  *int64
	Edits     []json.RawMessage // guard_ask: the denied edits
	Blocked   bool
}

type Tokens struct{ Input, Cached, Output int64 }

const (
	promptBlocked = "UserPromptSubmit operation blocked by hook:"
	hookTextMax   = 500
)

var guardTools = map[string]bool{"Edit": true, "Write": true, "MultiEdit": true, "NotebookEdit": true}

func rawStr(r json.RawMessage) (string, bool) {
	var s string
	if len(r) == 0 || r[0] != '"' || json.Unmarshal(r, &s) != nil {
		return "", false
	}
	return s, true
}

var intRE = regexp.MustCompile(`^-?[0-9]+$`)

// count is Python's _n: a non-negative JSON integer, else 0 (floats, bools, strings count 0).
func count(r json.RawMessage) int64 {
	s := strings.TrimSpace(string(r))
	if !intRE.MatchString(s) {
		return 0
	}
	var n int64
	if json.Unmarshal(r, &n) != nil || n < 0 {
		return 0
	}
	return n
}

// TokensOf maps a result event's usage object to Tokens, nil when it is not an object or
// both input and output are zero. Input counts every prompt token (fresh + cache writes + cache reads).
func TokensOf(usage json.RawMessage) *Tokens {
	var u map[string]json.RawMessage
	if json.Unmarshal(usage, &u) != nil || u == nil {
		return nil
	}
	cached := count(u["cache_read_input_tokens"])
	in := count(u["input_tokens"]) + count(u["cache_creation_input_tokens"]) + cached
	out := count(u["output_tokens"])
	if in == 0 && out == 0 {
		return nil
	}
	return &Tokens{Input: in, Cached: cached, Output: out}
}

func truthy(r json.RawMessage) bool {
	var v any
	if json.Unmarshal(r, &v) != nil {
		return false
	}
	switch x := v.(type) {
	case bool:
		return x
	case float64:
		return x != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return false
}

// ParseLine turns one stream.jsonl line into events (S§1.7). Invalid or non-object lines give none.
func ParseLine(line []byte) []Event {
	var ev map[string]json.RawMessage
	if json.Unmarshal(line, &ev) != nil || ev == nil {
		return nil
	}
	typ, _ := rawStr(ev["type"])
	switch typ {
	case "assistant":
		return parseAssistant(ev)
	case "result":
		return parseResult(ev)
	case "user":
		if e, ok := parseStopFeedback(ev); ok {
			return []Event{e}
		}
	case "system":
		sub, _ := rawStr(ev["subtype"])
		switch {
		case sub == "init":
			id, _ := rawStr(ev["session_id"])
			model, _ := rawStr(ev["model"])
			return []Event{{Kind: "session_id", SessionID: id, Model: model}}
		case strings.HasPrefix(sub, "hook") && sub != "hook_started":
			return []Event{parseHook(ev)}
		}
	case "rate_limit_event":
		var info map[string]json.RawMessage
		if json.Unmarshal(ev["rate_limit_info"], &info) != nil || info == nil {
			return nil
		}
		e := Event{Kind: "limit", Info: ev["rate_limit_info"]}
		e.LimitType, _ = rawStr(info["rateLimitType"])
		var f float64
		if r := info["resetsAt"]; len(r) > 0 && r[0] != '"' && json.Unmarshal(r, &f) == nil {
			n := int64(f)
			e.ResetsAt = &n
		}
		return []Event{e}
	}
	return nil
}

func parseAssistant(ev map[string]json.RawMessage) []Event {
	var msg struct {
		Content []json.RawMessage `json:"content"`
	}
	if json.Unmarshal(ev["message"], &msg) != nil {
		return nil
	}
	var out []Event
	for _, raw := range msg.Content {
		var b map[string]json.RawMessage
		if json.Unmarshal(raw, &b) != nil {
			continue
		}
		bt, _ := rawStr(b["type"])
		switch bt {
		case "text":
			if t, ok := rawStr(b["text"]); ok {
				out = append(out, Event{Kind: "text", Text: t})
			}
		case "tool_use":
			if n, ok := rawStr(b["name"]); ok {
				out = append(out, Event{Kind: "tool", Name: n, Input: b["input"]})
			}
		}
	}
	return out
}

func parseResult(ev map[string]json.RawMessage) []Event {
	r := Event{Kind: "result", IsError: truthy(ev["is_error"]), Tokens: TokensOf(ev["usage"])}
	if c := ev["total_cost_usd"]; len(c) > 0 && c[0] != 't' && c[0] != 'f' {
		var f float64
		if json.Unmarshal(c, &f) == nil {
			r.Cost = &f
		}
	}
	text, hasText := rawStr(ev["result"])
	if hasText {
		r.Text = text
	}
	if r.IsError {
		var errList []json.RawMessage
		if json.Unmarshal(ev["errors"], &errList) == nil && len(errList) > 0 {
			if s, ok := rawStr(errList[0]); ok {
				r.Error = s
			} else {
				r.Error = strings.TrimSpace(string(errList[0]))
			}
		}
	}
	var extra []Event
	var denials []json.RawMessage
	_ = json.Unmarshal(ev["permission_denials"], &denials)
	var edits []json.RawMessage
	for _, d := range denials {
		if guardedEdit(d) {
			edits = append(edits, d)
		}
	}
	if len(edits) > 0 {
		extra = append(extra, Event{Kind: "guard_ask", Edits: edits})
	}
	if hasText && strings.HasPrefix(text, promptBlocked) {
		reason := strings.TrimPrefix(text, promptBlocked)
		reason, _, _ = strings.Cut(reason, "\n\nOriginal prompt:")
		reason = strings.TrimSpace(reason)
		if reason == "" {
			reason = "the prompt holds a secret"
		}
		extra = append(extra, Event{Kind: "prompt_blocked", Reason: reason})
	}
	return append(extra, r)
}

// guardedEdit: a denied edit of a CLAUDE.md / AGENTS.md (blubird's guard hook asks, headless it is denied).
func guardedEdit(d json.RawMessage) bool {
	var den struct {
		ToolName  string                     `json:"tool_name"`
		ToolInput map[string]json.RawMessage `json:"tool_input"`
	}
	if json.Unmarshal(d, &den) != nil || !guardTools[den.ToolName] || den.ToolInput == nil {
		return false
	}
	p, _ := rawStr(den.ToolInput["file_path"])
	if p == "" {
		p, _ = rawStr(den.ToolInput["notebook_path"])
	}
	switch strings.ToLower(filepath.Base(p)) {
	case "claude.md", "agents.md":
		return p != ""
	}
	return false
}

// stopFeedbackPrefix starts the user turn claude -p injects when a Stop hook blocks; stream-json
// has no hook_response line for Stop hooks.
const stopFeedbackPrefix = "Stop hook feedback:\n"

func parseStopFeedback(ev map[string]json.RawMessage) (Event, bool) {
	var msg struct {
		Content json.RawMessage `json:"content"`
	}
	if json.Unmarshal(ev["message"], &msg) != nil {
		return Event{}, false
	}
	var texts []string
	if s, ok := rawStr(msg.Content); ok {
		texts = []string{s}
	} else {
		var blocks []struct{ Type, Text string }
		_ = json.Unmarshal(msg.Content, &blocks)
		for _, b := range blocks {
			if b.Type == "text" {
				texts = append(texts, b.Text)
			}
		}
	}
	for _, t := range texts {
		if r, ok := strings.CutPrefix(t, stopFeedbackPrefix); ok {
			e := Event{Kind: "hook", Name: "Stop", HookEvent: "Stop", Text: strings.TrimSpace(r), Blocked: true}
			if utf8.RuneCountInString(e.Text) > hookTextMax {
				e.Text = string([]rune(e.Text)[:hookTextMax])
			}
			return e, true
		}
	}
	return Event{}, false
}

func parseHook(ev map[string]json.RawMessage) Event {
	e := Event{Kind: "hook"}
	e.Name, _ = rawStr(ev["hook_name"])
	e.HookEvent, _ = rawStr(ev["hook_event"])
	for _, k := range []string{"output", "stdout"} {
		if s, ok := rawStr(ev[k]); ok && s != "" {
			e.Text = s
			break
		}
	}
	var d struct{ Decision, Reason string }
	if strings.HasPrefix(strings.TrimSpace(e.Text), "{") && json.Unmarshal([]byte(e.Text), &d) == nil && d.Decision == "block" {
		// a JSON decision on stdout (exit 0), as `setu hook idle` prints it
		e.Text, e.Blocked = strings.TrimSpace(d.Reason), true
	}
	if utf8.RuneCountInString(e.Text) > hookTextMax {
		e.Text = string([]rune(e.Text)[:hookTextMax])
	}
	return e
}
