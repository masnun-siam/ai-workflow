package sessions

import (
	"bytes"
	"encoding/json"
	"math"
	"path/filepath"
	"strings"
	"unicode/utf8"
)

// event is one parsed stream-json fact (S§1.7). Only the fields of its Kind are set.
type event struct {
	Kind string // text tool result session_id limit guard_ask prompt_blocked hook

	Text  string          // text, hook output
	Name  string          // tool name, hook name
	Input json.RawMessage // tool input

	Cost       *float64
	IsError    bool
	Err        string  // first of result.errors
	ResultText *string // result.result
	Tokens     *Tokens

	ID    string // session_id
	Model string

	ResetsAt  *int64 // limit
	LimitType string
	Info      map[string]any

	Edits  []map[string]any // guard_ask: denied protected edits
	Reason string           // prompt_blocked

	HookEvent string
	Blocked   bool
}

const promptBlockedPrefix = "UserPromptSubmit operation blocked by hook:"

// parseLine turns one stream.jsonl line into events. Invalid JSON and non-objects give none.
func parseLine(line []byte) []event {
	line = bytes.TrimSpace(line)
	if len(line) == 0 || line[0] != '{' {
		return nil
	}
	var ev map[string]any
	if err := json.Unmarshal(line, &ev); err != nil {
		return nil
	}
	typ, _ := ev["type"].(string)
	switch typ {
	case "assistant":
		return parseAssistant(line)
	case "user":
		if reason, ok := stopFeedback(line); ok {
			return []event{{Kind: "hook", Name: "Stop", HookEvent: "Stop", Text: clip(reason, 500), Blocked: true}}
		}
	case "rate_limit_event":
		info, ok := ev["rate_limit_info"].(map[string]any)
		if !ok {
			return nil
		}
		e := event{Kind: "limit", Info: info}
		if n, ok := info["resetsAt"].(float64); ok {
			v := int64(n)
			e.ResetsAt = &v
		}
		e.LimitType, _ = info["rateLimitType"].(string)
		return []event{e}
	case "result":
		return parseResult(ev)
	case "system":
		sub, _ := ev["subtype"].(string)
		if sub == "init" {
			e := event{Kind: "session_id"}
			e.ID, _ = ev["session_id"].(string)
			if m, ok := ev["model"].(string); ok && m != "" {
				e.Model = m
			}
			return []event{e}
		}
		if strings.HasPrefix(sub, "hook") && sub != "hook_started" {
			if h, ok := hookEvent(ev); ok {
				return []event{h}
			}
		}
	}
	return nil
}

func parseAssistant(line []byte) []event {
	var v struct {
		Message struct {
			Content []json.RawMessage `json:"content"`
		} `json:"message"`
	}
	if json.Unmarshal(line, &v) != nil {
		return nil
	}
	var out []event
	for _, raw := range v.Message.Content {
		var b struct {
			Type  string          `json:"type"`
			Text  any             `json:"text"`
			Name  any             `json:"name"`
			Input json.RawMessage `json:"input"`
		}
		if json.Unmarshal(raw, &b) != nil {
			continue
		}
		switch b.Type {
		case "text":
			if s, ok := b.Text.(string); ok {
				out = append(out, event{Kind: "text", Text: s})
			}
		case "tool_use":
			if s, ok := b.Name.(string); ok {
				out = append(out, event{Kind: "tool", Name: s, Input: b.Input})
			}
		}
	}
	return out
}

func parseResult(ev map[string]any) []event {
	r := event{Kind: "result"}
	if c, ok := ev["total_cost_usd"].(float64); ok {
		r.Cost = &c
	}
	r.IsError, _ = ev["is_error"].(bool)
	if s, ok := ev["result"].(string); ok {
		r.ResultText = &s
		r.Text = s
	}
	r.Tokens = tokensOf(ev["usage"])
	if errs, ok := ev["errors"].([]any); ok && r.IsError && len(errs) > 0 {
		r.Err = anyString(errs[0])
	}
	var extra []event
	if dens, ok := ev["permission_denials"].([]any); ok {
		var edits []map[string]any
		for _, d := range dens {
			if m, ok := d.(map[string]any); ok && guardedEdit(m) {
				edits = append(edits, m)
			}
		}
		if len(edits) > 0 {
			extra = append(extra, event{Kind: "guard_ask", Edits: edits})
		}
	}
	if r.ResultText != nil && strings.HasPrefix(*r.ResultText, promptBlockedPrefix) {
		reason := (*r.ResultText)[len(promptBlockedPrefix):]
		if i := strings.Index(reason, "\n\nOriginal prompt:"); i >= 0 {
			reason = reason[:i]
		}
		reason = strings.TrimSpace(reason)
		if reason == "" {
			reason = "the prompt holds a secret"
		}
		extra = append(extra, event{Kind: "prompt_blocked", Reason: reason})
	}
	return append(extra, r)
}

func anyString(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case nil:
		return "None"
	}
	b, _ := json.Marshal(v)
	return string(b)
}

// tokensOf is S§1.7 tokens_of: nil unless the usage object has input or output tokens.
func tokensOf(v any) *Tokens {
	u, ok := v.(map[string]any)
	if !ok {
		return nil
	}
	n := func(k string) int64 {
		f, ok := u[k].(float64)
		if !ok || f < 0 || f != math.Trunc(f) {
			return 0
		}
		return int64(f)
	}
	t := Tokens{
		Input:  n("input_tokens") + n("cache_creation_input_tokens") + n("cache_read_input_tokens"),
		Cached: n("cache_read_input_tokens"),
		Output: n("output_tokens"),
	}
	if t.Input == 0 && t.Output == 0 {
		return nil
	}
	return &t
}

var guardTools = map[string]bool{"Edit": true, "Write": true, "MultiEdit": true, "NotebookEdit": true}

func guardedEdit(d map[string]any) bool {
	name, _ := d["tool_name"].(string)
	if !guardTools[name] {
		return false
	}
	in, ok := d["tool_input"].(map[string]any)
	if !ok {
		return false
	}
	p, _ := in["file_path"].(string)
	if p == "" {
		p, _ = in["notebook_path"].(string)
	}
	if p == "" {
		return false
	}
	b := strings.ToLower(filepath.Base(p))
	return b == "claude.md" || b == "agents.md"
}

// hookEvent reads a system hook line. Silent successful hooks are not events.
func hookEvent(ev map[string]any) (event, bool) {
	name, _ := ev["hook_name"].(string)
	he, _ := ev["hook_event"].(string)
	if name == "" {
		name = he
	}
	text, _ := ev["output"].(string)
	if strings.TrimSpace(text) == "" {
		text, _ = ev["stdout"].(string)
	}
	if strings.TrimSpace(text) == "" {
		text, _ = ev["stderr"].(string)
	}
	text = strings.TrimSpace(text)
	code, hasCode := ev["exit_code"].(float64)
	blocked := hasCode && code == 2
	if reason, ok := blockReason(text); ok {
		// a JSON decision on stdout (exit 0), as `setu hook idle` prints it (FR-9)
		text, blocked = reason, true
	}
	if text == "" && !blocked && (!hasCode || code == 0) {
		return event{}, false
	}
	return event{Kind: "hook", Name: name, HookEvent: he, Text: clip(text, 500), Blocked: blocked}, true
}

// stopFeedbackPrefix starts the user turn claude -p injects when a Stop hook blocks; stream-json
// has no hook_response line for Stop hooks.
const stopFeedbackPrefix = "Stop hook feedback:\n"

// stopFeedback reads a Stop hook block from a user line: the reason after stopFeedbackPrefix.
func stopFeedback(line []byte) (string, bool) {
	var v struct {
		Message struct {
			Content json.RawMessage `json:"content"`
		} `json:"message"`
	}
	if json.Unmarshal(line, &v) != nil {
		return "", false
	}
	var texts []string
	var s string
	if json.Unmarshal(v.Message.Content, &s) == nil {
		texts = []string{s}
	} else {
		var blocks []struct{ Type, Text string }
		_ = json.Unmarshal(v.Message.Content, &blocks)
		for _, b := range blocks {
			if b.Type == "text" {
				texts = append(texts, b.Text)
			}
		}
	}
	for _, t := range texts {
		if r, ok := strings.CutPrefix(t, stopFeedbackPrefix); ok {
			return strings.TrimSpace(r), true
		}
	}
	return "", false
}

// blockReason reads a hook's {"decision":"block","reason":…} stdout.
func blockReason(text string) (string, bool) {
	if !strings.HasPrefix(text, "{") {
		return "", false
	}
	var d struct{ Decision, Reason string }
	if json.Unmarshal([]byte(text), &d) != nil || d.Decision != "block" {
		return "", false
	}
	return strings.TrimSpace(d.Reason), true
}

func clip(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[:n])
}

// transcript maps an event to its transcript form (text, tool, result, hook); ok is false for
// events that are only state (session_id, limit).
func (e event) transcript() (TranscriptEvent, bool) {
	switch e.Kind {
	case "text":
		t := e.Text
		return TranscriptEvent{Kind: "text", Text: &t}, true
	case "tool":
		return TranscriptEvent{Kind: "tool", Name: e.Name, Input: e.Input}, true
	case "result":
		iserr := e.IsError
		return TranscriptEvent{Kind: "result", Cost: e.Cost, IsError: &iserr, Text: e.ResultText, Tokens: e.Tokens}, true
	case "hook":
		t, b := e.Text, e.Blocked
		return TranscriptEvent{Kind: "hook", Name: e.Name, Event: e.HookEvent, Text: &t, Blocked: &b}, true
	case "guard_ask":
		t := "file"
		if len(e.Edits) > 0 {
			name, _ := e.Edits[0]["tool_name"].(string)
			t = name + " " + editPath(e.Edits[0]) + " denied"
		}
		b := true
		return TranscriptEvent{Kind: "hook", Name: "claude-md-guard", Event: "PreToolUse", Text: &t, Blocked: &b}, true
	case "prompt_blocked":
		t, b := e.Reason, true
		return TranscriptEvent{Kind: "hook", Name: "mask-secrets", Event: "UserPromptSubmit", Text: &t, Blocked: &b}, true
	}
	return TranscriptEvent{}, false
}

func editPath(d map[string]any) string {
	in, _ := d["tool_input"].(map[string]any)
	p, _ := in["file_path"].(string)
	if p == "" {
		p, _ = in["notebook_path"].(string)
	}
	return p
}

// isHook reports whether the event is a hook fact (counted in Session.hooks).
func (e event) isHook() bool {
	return e.Kind == "hook" || e.Kind == "guard_ask" || e.Kind == "prompt_blocked"
}
