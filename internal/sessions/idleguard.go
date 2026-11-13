package sessions

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/home"
)

// The idle guard is the Stop hook of headless skill sessions (PRD headless-idle-guard FR-2..FR-4).
const (
	idleReason    = "Do not stop idle. Either continue the flow to its end, ask the user with `setu ask` and end your turn, or, when done, end with a very short table with check-mark emojis. Never call Monitor or ScheduleWakeup."
	stalledReason = "ended without finishing or asking"
	maxIdleBlocks = 2
	tailChunk     = 64 << 10
)

var (
	idleTaskIDRe = regexp.MustCompile(`(?:\btask |\bID: |\bagentId: |\bid: |\brun )([A-Za-z0-9_-]{6,})`)
	idleNoteIDRe = regexp.MustCompile(`<task-id>([^<]+)</task-id>`)
	idleEndedRe  = regexp.MustCompile(`(?i)<status>(completed|failed|killed|stopped|cancelled|expired)</status>`)
	idleDoneRe   = regexp.MustCompile(`(?m)^\s*\|.*(✅|✔)`)

	errNoChange = errors.New("idle guard: nothing to write")
)

// idleVerdict is decideIdle's answer. idleSkip is a stop the guard does not judge (an API error,
// such as a usage limit): it ends allowed and leaves the block count as it was.
type idleVerdict int

const (
	idleAllow idleVerdict = iota
	idleBlock
	idleSkip
)

type hookInput struct {
	SessionID            string `json:"session_id"`
	TranscriptPath       string `json:"transcript_path"`
	LastAssistantMessage string `json:"last_assistant_message"`
}

type transcriptEntry struct {
	Type          string `json:"type"`
	IsSidechain   bool   `json:"isSidechain"`
	IsMeta        bool   `json:"isMeta"`
	IsAPIErrorMsg bool   `json:"isApiErrorMessage"`
	Message       struct {
		Content json.RawMessage `json:"content"`
	} `json:"message"`
}

type contentBlock struct {
	Type      string          `json:"type"`
	Text      string          `json:"text"`
	ID        string          `json:"id"`
	Name      string          `json:"name"`
	Input     json.RawMessage `json:"input"`
	ToolUseID string          `json:"tool_use_id"`
	Content   json.RawMessage `json:"content"`
}

type toolUse struct {
	id, name string
	input    map[string]any
}

// runHook dispatches `setu hook <name>`. Only `idle` exists.
func runHook(ctx context.Context, env cli.Env, args []string) int {
	if len(args) == 0 || args[0] != "idle" {
		fmt.Fprintln(env.Stderr, "usage: setu hook idle  (Stop hook input JSON on stdin)")
		return cli.ExitUsage
	}
	runHookIdle(env)
	return 0
}

// runHookIdle prints the block JSON or nothing. It never fails the hook: every error allows the stop.
func runHookIdle(env cli.Env) {
	defer func() { _ = recover() }()
	getenv := env.Getenv
	if getenv == nil {
		getenv = os.Getenv
	}
	sid := getenv("SETU_SESSION")
	if sid == "" {
		sid = getenv("AIW_UI_SESSION")
	}
	h := env.Home
	if h == nil {
		var err error
		if h, err = home.Open(); err != nil {
			return
		}
	}
	if env.Stdin == nil {
		return
	}
	raw, err := io.ReadAll(io.LimitReader(env.Stdin, 1<<20))
	if err != nil {
		return
	}
	rec, err := readRecord(h, sid)
	if err != nil {
		return
	}
	verdict := idleAllow
	if !questionPending(rec) {
		var in hookInput
		if err := json.Unmarshal(raw, &in); err != nil {
			return
		}
		entries, err := readTurn(expandHome(in.TranscriptPath))
		if err != nil {
			return
		}
		if verdict = decideIdle(in, entries); verdict == idleSkip {
			return
		}
	}
	block := false
	_, _, _, err = updateRecord(h, sid, func(r *Record, _ statKey) error {
		switch {
		case questionPending(*r) || verdict == idleAllow:
			if r.IdleBlocks == 0 {
				return errNoChange
			}
			r.IdleBlocks = 0
		case r.IdleBlocks < maxIdleBlocks:
			r.IdleBlocks++
			block = true
		default:
			r.Stalled, r.IdleBlocks = stalledReason, 0
		}
		return nil
	}, nil)
	if err == nil && block {
		out, _ := json.Marshal(map[string]string{"decision": "block", "reason": idleReason})
		fmt.Fprintln(env.Stdout, string(out))
	}
}

func questionPending(r Record) bool {
	return r.PendingQuestion != nil && r.PendingQuestion.Status == "pending"
}

// readTurn returns the transcript's entries from the last turn-starting prompt to the end. It reads
// the file backwards in chunks, so a long transcript costs only its last turn. Unparsable lines are
// dropped.
func readTurn(path string) ([]json.RawMessage, error) {
	if path == "" {
		return nil, errors.New("no transcript path")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	var rev []json.RawMessage
	var partial []byte // the start of a line whose beginning is still unread
	for pos := st.Size(); ; {
		n := min(int64(tailChunk), pos)
		pos -= n
		buf := make([]byte, n, n+int64(len(partial)))
		if _, err := f.ReadAt(buf, pos); err != nil && !errors.Is(err, io.EOF) {
			return nil, err
		}
		buf = append(buf, partial...)
		lines := buf
		partial = nil
		if pos > 0 {
			i := bytes.IndexByte(buf, '\n')
			if i < 0 {
				partial = buf
				continue
			}
			partial, lines = buf[:i], buf[i+1:]
		}
		parts := bytes.Split(lines, []byte{'\n'})
		for j := len(parts) - 1; j >= 0; j-- {
			line := bytes.TrimSpace(parts[j])
			var e transcriptEntry
			if len(line) == 0 || json.Unmarshal(line, &e) != nil {
				continue
			}
			rev = append(rev, json.RawMessage(line))
			if isTurnStart(e) {
				return reversed(rev), nil
			}
		}
		if pos == 0 {
			return reversed(rev), nil
		}
	}
}

func reversed(s []json.RawMessage) []json.RawMessage {
	out := make([]json.RawMessage, len(s))
	for i, v := range s {
		out[len(s)-1-i] = v
	}
	return out
}

// isTurnStart: a main-thread user entry that is typed text or a notification, not a tool result.
// isMeta entries are text Claude Code injects mid-turn, such as a skill's body after a Skill call.
func isTurnStart(e transcriptEntry) bool {
	if e.Type != "user" || e.IsSidechain || e.IsMeta {
		return false
	}
	var s string
	if json.Unmarshal(e.Message.Content, &s) == nil {
		return true
	}
	var blocks []contentBlock
	if json.Unmarshal(e.Message.Content, &blocks) != nil {
		return false
	}
	text := false
	for _, b := range blocks {
		switch b.Type {
		case "tool_result":
			return false
		case "text":
			text = true
		}
	}
	return text
}

// textOf flattens message content: a string, or text and tool_result blocks.
func textOf(content json.RawMessage) string {
	var s string
	if json.Unmarshal(content, &s) == nil {
		return s
	}
	var blocks []contentBlock
	if json.Unmarshal(content, &blocks) != nil {
		return ""
	}
	var out []string
	for _, b := range blocks {
		switch b.Type {
		case "text":
			out = append(out, b.Text)
		case "tool_result":
			out = append(out, textOf(b.Content))
		}
	}
	return strings.Join(out, "\n")
}

// decideIdle judges one stop from the transcript entries (it uses only the last turn in them). It
// allows when background work started this turn is still live or the final message has a ✅/✔ table
// row; it skips an API-error stop. The pending `setu ask` question is the caller's check.
func decideIdle(in hookInput, entries []json.RawMessage) idleVerdict {
	var parsed []transcriptEntry
	var raws []json.RawMessage
	start := 0
	for _, raw := range entries {
		var e transcriptEntry
		if json.Unmarshal(raw, &e) != nil || e.IsSidechain {
			continue
		}
		if isTurnStart(e) {
			start = len(parsed)
		}
		parsed, raws = append(parsed, e), append(raws, raw)
	}
	parsed, raws = parsed[start:], raws[start:]
	if len(parsed) > 0 && parsed[len(parsed)-1].IsAPIErrorMsg {
		return idleSkip
	}
	var uses []toolUse
	results := map[string]string{}
	ended := map[string]bool{}
	final := ""
	for i, e := range parsed {
		for _, id := range endedTaskIDs(raws[i]) {
			ended[id] = true
		}
		var blocks []contentBlock
		_ = json.Unmarshal(e.Message.Content, &blocks)
		for _, b := range blocks {
			switch {
			case e.Type == "user" && b.Type == "tool_result":
				results[b.ToolUseID] = textOf(b.Content)
			case e.Type == "assistant" && b.Type == "tool_use":
				var inp map[string]any
				_ = json.Unmarshal(b.Input, &inp)
				uses = append(uses, toolUse{b.ID, b.Name, inp})
				if b.Name == "TaskStop" {
					ended[stopTarget(inp)] = true
				}
			case e.Type == "assistant" && b.Type == "text" && strings.TrimSpace(b.Text) != "":
				final = b.Text
			}
		}
	}
	for _, u := range uses {
		if isBackground(u) && liveTask(results[u.id], ended) {
			return idleAllow
		}
	}
	if in.LastAssistantMessage != "" {
		final = in.LastAssistantMessage
	}
	if idleDoneRe.MatchString(final) {
		return idleAllow
	}
	return idleBlock
}

// isBackground: work that ends this turn and starts a new one when it finishes. Monitor and
// ScheduleWakeup are waits the headless prompt forbids, so they do not count.
func isBackground(u toolUse) bool {
	switch u.name {
	case "Agent", "Task", "Workflow":
		return true
	case "Bash":
		bg, _ := u.input["run_in_background"].(bool)
		return bg
	}
	return false
}

// liveTask: none of the ids in the tool result has ended. An unknown id counts as live.
func liveTask(result string, ended map[string]bool) bool {
	for _, m := range idleTaskIDRe.FindAllStringSubmatch(result, -1) {
		if ended[m[1]] {
			return false
		}
	}
	return true
}

func stopTarget(inp map[string]any) string {
	for _, k := range []string{"task_id", "shell_id"} {
		if s, ok := inp[k].(string); ok && s != "" {
			return strings.TrimSpace(s)
		}
	}
	return ""
}

// endedTaskIDs finds <task-notification>s with an ended status anywhere in one raw entry.
func endedTaskIDs(raw json.RawMessage) []string {
	if !bytes.Contains(raw, []byte("<task-id>")) {
		return nil
	}
	text := strings.ReplaceAll(string(raw), `\n`, "\n")
	var ids []string
	for _, note := range strings.Split(text, "<task-notification>")[1:] {
		note, _, _ = strings.Cut(note, "</task-notification>")
		if m := idleNoteIDRe.FindStringSubmatch(note); m != nil && idleEndedRe.MatchString(note) {
			ids = append(ids, strings.TrimSpace(m[1]))
		}
	}
	return ids
}

// idleGuarded reports whether a spawn of r carries the idle Stop hook (FR-1, FR-8): the setting
// is on, the session is a UI run or a dispatch lane, and its step is a blubird skill. Grind,
// panel, coordinator and setu-prompt runs never get it. Read per spawn, so a resume after a
// toggle follows the new value.
func (m *Manager) idleGuarded(r Record) bool {
	if m.d.Settings == nil || !m.d.Settings.IdleGuard() || (r.Kind != "" && r.Kind != "lane") || m.d.Prompts == nil {
		return false
	}
	st, ok := m.d.Prompts.Step(m.stepOf(r))
	return ok && st.Source == "blubird"
}

// idleHookSettings is the --settings value that runs `setu hook idle` as a Stop hook, by the
// absolute path of this setu binary rather than PATH.
func (m *Manager) idleHookSettings() string {
	type hook struct {
		Type    string `json:"type"`
		Command string `json:"command"`
		Timeout int    `json:"timeout"`
	}
	type matcher struct {
		Hooks []hook `json:"hooks"`
	}
	cmd := shellQuote(filepath.Join(m.d.BinDir, "setu")) + " hook idle"
	b, _ := json.Marshal(map[string]any{"hooks": map[string][]matcher{
		"Stop": {{Hooks: []hook{{Type: "command", Command: cmd, Timeout: 10}}}},
	}})
	return string(b)
}
