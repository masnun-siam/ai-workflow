// Package sessions owns sessions/<id>/ on disk: the headless `claude` runner, the stream follower,
// questions and answers, limits, restart recovery, transcripts and the `setu ask` verb.
//
// The on-disk contract (meta.json, stream.jsonl, stderr.log, .lock) is the one the Python engine
// wrote, so migrated sessions load unchanged and a child's `setu ask` can edit meta.json under the
// same flock as the server.
package sessions

import (
	"bytes"
	"context"
	"encoding/json"
	"encoding/json/jsontext"
	"fmt"
	"os"
	"reflect"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
)

// Status is a session's lifecycle state.
type Status string

const (
	StStarting Status = "starting"
	StRunning  Status = "running"
	StWaiting  Status = "waiting"
	StLimited  Status = "limited"
	StQueued   Status = "queued"
	StDone     Status = "done"
	StFailed   Status = "failed"
	StStopped  Status = "stopped"
)

// Live reports starting, running, waiting, limited or queued.
func (s Status) Live() bool {
	switch s {
	case StStarting, StRunning, StWaiting, StLimited, StQueued:
		return true
	}
	return false
}

// Terminal reports done, failed or stopped.
func (s Status) Terminal() bool { return s == StDone || s == StFailed || s == StStopped }

// Link is the issue or PR a session is about.
type Link struct {
	Owner string `json:"owner"`
	Repo  string `json:"repo"`
	Issue int    `json:"issue"`
}

// Tokens is a token tally.
type Tokens struct {
	Input  int64 `json:"input"`
	Cached int64 `json:"cached"`
	Output int64 `json:"output"`
}

func (t Tokens) add(o Tokens) Tokens {
	return Tokens{t.Input + o.Input, t.Cached + o.Cached, t.Output + o.Output}
}

// Option, Question, Round: the pending question shape (API §4).
type Option struct {
	Label       string `json:"label"`
	Description string `json:"description"`
	Preview     string `json:"preview,omitempty"`
}

type Question struct {
	Header        string   `json:"header"`
	Question      string   `json:"question"`
	MultiSelect   bool     `json:"multiSelect"`
	AllowFreeText bool     `json:"allowFreeText"`
	Recommended   *string  `json:"recommended"`
	Options       []Option `json:"options"`
}

type Round struct {
	ID            string          `json:"id"`
	Status        string          `json:"status"`
	AllowFreeText bool            `json:"allowFreeText"`
	Held          bool            `json:"held,omitempty"`
	Answerer      *string         `json:"answerer,omitempty"`
	Risk          json.RawMessage `json:"risk,omitempty"`
	Questions     []Question      `json:"questions"`
}

// Answer is one question's answer: exactly one of the three is set.
type Answer struct {
	Labels []string `json:"labels,omitempty"`
	Other  *string  `json:"other,omitempty"`
	None   bool     `json:"none,omitempty"`
}

// GuardEdit is a denied CLAUDE.md/AGENTS.md edit waiting for a human decision.
type GuardEdit struct {
	ToolName  string          `json:"tool_name"`
	ToolInput json.RawMessage `json:"tool_input"`
	ToolUseID string          `json:"tool_use_id,omitempty"`
}

// Record is meta.json. Fields it does not model are kept in Extra and written back unchanged,
// so records of other packages (panels, away, dispatch) and of the old engine survive a round trip.
type Record struct {
	ID              string          `json:"id"`
	Command         string          `json:"command"`
	Repo            string          `json:"repo"`
	Link            *Link           `json:"link"`
	SessionID       string          `json:"session_id,omitempty"`
	PID             int             `json:"pid,omitempty"`
	PidStarted      string          `json:"pid_started,omitempty"`
	Status          Status          `json:"status"`
	Cost            *float64        `json:"cost"`
	Tokens          *Tokens         `json:"tokens"`
	StartedAt       string          `json:"started_at"`
	EndedAt         string          `json:"ended_at,omitempty"`
	PendingQuestion *Round          `json:"pending_question"`
	ClaudeCmd       string          `json:"claude_cmd"`
	Model           string          `json:"model,omitempty"`
	CwdPath         string          `json:"cwd_path,omitempty"`
	Error           string          `json:"error,omitempty"`
	Note            string          `json:"note,omitempty"`
	PendingAnswer   string          `json:"pending_answer,omitempty"`
	QueuedPrompt    string          `json:"queued_prompt,omitempty"`
	ResumedFresh    json.RawMessage `json:"resumed_fresh,omitempty"`
	TerminalHandoff json.RawMessage `json:"terminal_handoff,omitempty"`
	Hold            bool            `json:"hold,omitempty"`
	RunModel        string          `json:"run_model,omitempty"`
	RunEffort       string          `json:"run_effort,omitempty"`
	DirectModel     string          `json:"direct_model,omitempty"`
	DirectEffort    string          `json:"direct_effort,omitempty"`
	AllowedTools    []string        `json:"allowed_tools,omitempty"`
	Batch           string          `json:"batch,omitempty"`
	BatchMax        int             `json:"batch_max,omitempty"`
	LimitResetsAt   int64           `json:"limit_resets_at,omitempty"`
	LimitType       string          `json:"limit_type,omitempty"`
	AutoResume      *bool           `json:"auto_resume,omitempty"`
	Request         json.RawMessage `json:"request,omitempty"`
	NoRepo          bool            `json:"no_repo,omitempty"`
	VaultFolder     string          `json:"vault_folder,omitempty"`
	PinAccount      bool            `json:"pin_account,omitempty"`
	Dismissed       bool            `json:"dismissed,omitempty"`
	GuardEdit       *GuardEdit      `json:"guard_edit,omitempty"`
	Notified        []string        `json:"notified,omitempty"`
	Role            string          `json:"role,omitempty"`
	Panel           string          `json:"panel,omitempty"`
	PanelRole       string          `json:"panel_role,omitempty"`
	PanelLens       string          `json:"panel_lens,omitempty"`
	Dispatch        string          `json:"dispatch,omitempty"`
	Lane            string          `json:"lane,omitempty"`
	Step            string          `json:"step,omitempty"`
	Args            string          `json:"args,omitempty"`
	Kind            string          `json:"kind,omitempty"`
	Agent           string          `json:"agent,omitempty"`
	Gate            bool            `json:"gate,omitempty"`
	Instructions    []string        `json:"instructions,omitempty"`
	Stalled         string          `json:"stalled,omitempty"`     // why the idle guard let it stop unfinished; cleared on resume
	IdleBlocks      int             `json:"idle_blocks,omitempty"` // the idle guard's consecutive blocks; cleared on resume
	// accumulation bases: the totals when the current claude process started (see follower)
	CostBase     float64 `json:"cost_base,omitempty"`
	TokenBase    *Tokens `json:"token_base,omitempty"`
	StreamOffset int64   `json:"stream_offset,omitempty"` // stream.jsonl size when the current process was spawned
	Hooks        int     `json:"hooks,omitempty"`
	HooksBase    int     `json:"hooks_base,omitempty"`

	Extra map[string]json.RawMessage `json:"-"`
}

type recAlias Record

var recordKeys = func() map[string]bool {
	m := map[string]bool{}
	t := reflect.TypeOf(Record{})
	for i := 0; i < t.NumField(); i++ {
		tag := t.Field(i).Tag.Get("json")
		name, _, _ := strings.Cut(tag, ",")
		if name != "" && name != "-" {
			m[name] = true
		}
	}
	return m
}()

// UnmarshalJSON is lenient: a field of the wrong type is skipped, unknown fields go to Extra.
func (r *Record) UnmarshalJSON(b []byte) error {
	var a recAlias
	if err := json.Unmarshal(b, &a); err != nil {
		if _, ok := err.(*json.UnmarshalTypeError); !ok {
			return err
		}
	}
	// the keys this struct does not model are kept in Extra: walk the top level once and copy only
	// those values (a whole-object map would copy every value of every record)
	a.Extra = nil
	dec := jsontext.NewDecoder(bytes.NewReader(b))
	if t, err := dec.ReadToken(); err != nil {
		return err
	} else if t.Kind() != '{' {
		return fmt.Errorf("session record is not a JSON object")
	}
	for dec.PeekKind() != '}' {
		kt, err := dec.ReadToken()
		if err != nil {
			return err
		}
		k := kt.String()
		if recordKeys[k] {
			if err := dec.SkipValue(); err != nil {
				return err
			}
			continue
		}
		v, err := dec.ReadValue()
		if err != nil {
			return err
		}
		if a.Extra == nil {
			a.Extra = map[string]json.RawMessage{}
		}
		a.Extra[k] = json.RawMessage(bytes.Clone(v))
	}
	*r = Record(a)
	return nil
}

// MarshalJSON writes the modelled fields and then Extra.
func (r Record) MarshalJSON() ([]byte, error) {
	b, err := json.Marshal(recAlias(r))
	if err != nil {
		return nil, err
	}
	if len(r.Extra) == 0 {
		return b, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, err
	}
	for k, v := range r.Extra {
		if _, ok := m[k]; !ok && !recordKeys[k] {
			m[k] = v
		}
	}
	return json.Marshal(m)
}

// applyFields merges arbitrary JSON-able fields into the record (a nil value removes the key).
func (r *Record) applyFields(f map[string]any) error {
	if len(f) == 0 {
		return nil
	}
	b, err := json.Marshal(*r)
	if err != nil {
		return err
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		return err
	}
	for k, v := range f {
		if v == nil {
			delete(m, k)
		} else {
			m[k] = v
		}
	}
	b, err = json.Marshal(m)
	if err != nil {
		return err
	}
	var out Record
	if err := json.Unmarshal(b, &out); err != nil {
		return err
	}
	*r = out
	return nil
}

// ---- public shapes (API §4) ----

type Panel struct {
	ID    string  `json:"id"`
	Role  string  `json:"role"`
	Lens  *string `json:"lens"`
	State string  `json:"state"`
}

type DispatchRef struct {
	ID   string `json:"id"`
	Lane string `json:"lane"`
}

// Session is the API shape of a record.
type Session struct {
	ID              string       `json:"id"`
	Step            *string      `json:"step"`
	Skill           *string      `json:"skill"`
	Kind            *string      `json:"kind"`
	Title           string       `json:"title"`
	Command         string       `json:"command"`
	Repo            *string      `json:"repo"`
	RepoPath        *string      `json:"repo_path"`
	Link            *Link        `json:"link"`
	SessionID       *string      `json:"session_id"`
	Status          Status       `json:"status"`
	Model           *string      `json:"model"`
	Effort          *string      `json:"effort"`
	Cost            *float64     `json:"cost"`
	Tokens          *Tokens      `json:"tokens"`
	StartedAt       string       `json:"started_at"`
	EndedAt         *string      `json:"ended_at"`
	DurationS       *int64       `json:"duration_s"`
	Waiting         bool         `json:"waiting"`
	PendingQuestion *Round       `json:"pending_question"`
	Error           *string      `json:"error"`
	Note            *string      `json:"note"`
	PendingAnswer   *string      `json:"pending_answer"`
	QueuedPrompt    *string      `json:"queued_prompt"`
	Account         string       `json:"account"`
	LimitResetsAt   *int64       `json:"limit_resets_at"`
	LimitType       *string      `json:"limit_type"`
	AutoResume      *bool        `json:"auto_resume"`
	Hold            bool         `json:"hold"`
	NoRepo          bool         `json:"no_repo"`
	VaultFolder     *string      `json:"vault_folder"`
	Dismissed       bool         `json:"dismissed"`
	Panel           *Panel       `json:"panel"`
	Dispatch        *DispatchRef `json:"dispatch"`
	Hooks           int          `json:"hooks"`
	ResumeCommand   *string      `json:"resume_command"`
	Stalled         *string      `json:"stalled"`
}

// SessionStats is the cost and count tally in GET /api/sessions.
type SessionStats struct {
	TodayCount int     `json:"today_count"`
	TodayCost  float64 `json:"today_cost"`
	MonthCount int     `json:"month_count"`
	MonthCost  float64 `json:"month_cost"`
}

// Limit is one account's rate-limit state.
type Limit struct {
	LimitedUntil int64         `json:"limited_until,omitempty"`
	Warning      *LimitWarning `json:"warning,omitempty"`
}

type LimitWarning struct {
	Type        string   `json:"type"`
	Utilization *float64 `json:"utilization"`
}

// TranscriptEvent is one entry of GET /api/sessions/{id}/stream.
type TranscriptEvent struct {
	Kind string `json:"kind"`
	// text
	Text *string `json:"text,omitempty"`
	// tool
	Name  string          `json:"name,omitempty"`
	Input json.RawMessage `json:"input,omitempty"`
	// result
	Cost    *float64 `json:"cost,omitempty"`
	IsError *bool    `json:"is_error,omitempty"`
	Tokens  *Tokens  `json:"tokens,omitempty"`
	// hook
	Event   string `json:"event,omitempty"`
	Blocked *bool  `json:"blocked,omitempty"`
}

func (e TranscriptEvent) MarshalJSON() ([]byte, error) {
	m := map[string]any{"kind": e.Kind}
	switch e.Kind {
	case "text":
		m["text"] = deref(e.Text)
	case "tool":
		m["name"] = e.Name
		if e.Input == nil {
			m["input"] = nil
		} else {
			m["input"] = e.Input
		}
	case "result":
		m["cost"] = e.Cost
		m["is_error"] = e.IsError != nil && *e.IsError
		m["text"] = e.Text
		m["tokens"] = e.Tokens
	case "hook":
		m["name"] = e.Name
		m["event"] = e.Event
		m["text"] = deref(e.Text)
		m["blocked"] = e.Blocked != nil && *e.Blocked
	}
	return json.Marshal(m)
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// ---- requests ----

// StartRequest is the POST /api/sessions body.
type StartRequest struct {
	Step        string   `json:"step,omitempty"`
	Text        string   `json:"text,omitempty"`
	Args        string   `json:"args,omitempty"`
	Repo        string   `json:"repo,omitempty"`
	Product     string   `json:"product,omitempty"`
	Issue       int      `json:"issue,omitempty"`
	NoRepo      bool     `json:"no_repo,omitempty"`
	VaultFolder string   `json:"vault_folder,omitempty"`
	Account     string   `json:"account,omitempty"`
	PinAccount  bool     `json:"pin_account,omitempty"`
	Batch       string   `json:"batch,omitempty"`
	Model       string   `json:"model,omitempty"`
	Effort      string   `json:"effort,omitempty"`
	Lenses      []string `json:"lenses,omitempty"`
	Guard       bool     `json:"guard,omitempty"`
	Force       bool     `json:"force,omitempty"`
}

// Spec is an internal start (grind, dispatch, review, away, release).
type Spec struct {
	Prompt       Prompt
	Args         string // the step args, kept so a queued or limited start can be rebuilt
	Cwd          string // registered slug or absolute directory
	Link         *Link
	Cmd          string // account command; "" = default
	Gate         bool
	Agent        string
	Instructions []string
	Env          []string
	ExtraFiles   []*os.File
	AllowedTools []string
	Model        string // direct --model
	Effort       string // direct --effort
	RunModel     string
	RunEffort    string
	Batch        string
	BatchMax     int
	Kind         string
	Fields       map[string]any
	// Request is stored as the replayable start body.
	Request any
}

// Filter selects sessions for List.
type Filter struct {
	Limit     int
	Before    string
	Statuses  []Status
	Repo      string // slug
	Step      string
	Answerers bool // include role=away-answerer
}

// ---- interfaces to sibling packages (small, satisfied by thin adapters in the wiring) ----

// Step mirrors prompts.Step.
type Step struct {
	ID     string
	Source string // "blubird" | "setu"
	Skill  string
	RunsIn string // "docs" | "issue" | "repo" | "none"
}

// Prompt mirrors prompts.Prompt.
type Prompt struct{ Step, Display, Text string }

// Prompts is what sessions needs from prompts.Registry.
type Prompts interface {
	Step(id string) (Step, bool)
	Build(stepID, args string) (Prompt, error)
	Available(stepID string) error
	Agent(name string) (body string, tools []string, err error)
}

// Settings is what sessions needs from settings.Store.
type Settings interface {
	AccountCmd(label string) (cmd string, ok bool) // a saved account label
	DefaultCmd() string
	LabelFor(cmd string) string // account label, or "" when the command is not saved
	CheckRun(model, effort string) error
	RunDefaults() (model, effort string) // settings run_model / run_effort ("" = unset)
	VaultDir() string
}

// Claude is what sessions needs from the claude package.
type Claude interface {
	Argv(cmd string) ([]string, error)
	Preflight(ctx context.Context, cmd string, isDefault bool) error
	CopyTranscript(fromCmd, toCmd, cwd, sessionID string) error
}

// RepoResolver is satisfied by products.Registry.
type RepoResolver interface {
	Resolve(ctx context.Context, repo string) (path, slug string, err error)
	DocsRepo(ctx context.Context, cwd string) (path, slug string, err error)
	SlugOf(path string) string
}

// Note mirrors notify.Note.
type Note struct {
	ID, Repo, Command, Text, SessionID, Question, Recommended, Error, Step string
	Link                                                                   *Link
}

// Notifier is satisfied by notify.Service through an adapter.
type Notifier interface{ Notify(event string, n Note) }

// StartGuard lets dispatch and grind refuse a start (return errs.Conflict).
type StartGuard func(ctx context.Context, req StartRequest, step Step, slug string, issue int) error

// Deps wires a Manager.
type Deps struct {
	Home     *home.Home
	Bus      *events.Bus
	Settings Settings
	Claude   Claude
	Prompts  Prompts
	Repos    RepoResolver
	Notify   Notifier
	Guards   []StartGuard
	Now      func() time.Time
	BinDir   string // directory of the setu binary, prepended to the child's PATH ("" = this executable's)

	// Title returns the issue or PR title for a linked session ("" when unknown).
	Title func(slug string, issue int) string
	// PanelState returns a review panel's state for Session.panel.
	PanelState func(panelID string) string
	// AfterStart runs after a successful StartSession (peer-review panels for req.Lenses).
	// A failure stops the new session.
	AfterStart func(ctx context.Context, rec Record, req StartRequest) error
}

func (d Deps) now() time.Time {
	if d.Now != nil {
		return d.Now()
	}
	return time.Now()
}
