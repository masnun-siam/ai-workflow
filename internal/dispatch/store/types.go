// Package store holds the dispatch record on disk (dispatches/<id>.json), its locks and the lane
// ownership queries. It is a leaf (imports home and errs only) so grind can ask who owns a PR
// without importing the dispatch engine (W§2.1).
package store

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strconv"
	"strings"
)

// Lane stages (W§2.2).
const (
	StQueued        = "queued"
	StImplementing  = "implementing"
	StGrinding      = "grinding"
	StMergeGate     = "merge_gate"
	StConflictFix   = "conflict_fix"
	StAwaitingMerge = "awaiting_merge"
	StFollowups     = "followups"
	StClosed        = "closed"
	StSkipped       = "skipped"
)

// Dispatch states.
const (
	Running   = "running"
	Paused    = "paused"
	Done      = "done"
	Cancelled = "cancelled"
)

// MaxEvents is the cap of Dispatch.Events (oldest dropped).
const MaxEvents = 500

// Active reports whether a stage has a live lane session (or is waiting on the merge).
func Active(stage string) bool {
	switch stage {
	case StImplementing, StGrinding, StMergeGate, StConflictFix, StAwaitingMerge, StFollowups:
		return true
	}
	return false
}

// Live reports a dispatch state that still ticks lanes.
func Live(state string) bool { return state == Running || state == Paused }

// Settings are the per-dispatch knobs (W§2.1). Nullable ones are pointers.
type Settings struct {
	Max           int      `json:"max"`
	Grind         string   `json:"grind"` // off | simple | full
	CI            string   `json:"ci"`    // wait | defer | ignore
	AutoMerge     bool     `json:"auto_merge"`
	SkipApproval  bool     `json:"skip_approval"`
	FeatureBranch *string  `json:"feature_branch"`
	BaseBranch    *string  `json:"base_branch"`
	Model         *string  `json:"model"`
	Effort        *string  `json:"effort"`
	Account       *string  `json:"account"`
	MaxCost       *float64 `json:"max_cost"`
}

// Defaults are the settings of a new dispatch.
func Defaults() Settings { return Settings{Max: 2, Grind: "full", CI: "wait"} }

// Str dereferences a nullable setting.
func Str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// Ptr returns a pointer to s, nil when s is empty.
func Ptr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// Handle names a lane session.
type Handle struct {
	Session string `json:"session"`
}

// OutboxItem is a session effect queued for the next tick: ["send", text] or ["close", null].
type OutboxItem struct {
	Kind string
	Text string
}

func (o OutboxItem) MarshalJSON() ([]byte, error) {
	if o.Kind == "close" {
		return []byte(`["close",null]`), nil
	}
	t, _ := json.Marshal(o.Text)
	k, _ := json.Marshal(o.Kind)
	return []byte("[" + string(k) + "," + string(t) + "]"), nil
}

func (o *OutboxItem) UnmarshalJSON(b []byte) error {
	var a []any
	if err := json.Unmarshal(b, &a); err != nil || len(a) == 0 {
		return fmt.Errorf("bad outbox item")
	}
	o.Kind, _ = a[0].(string)
	if len(a) > 1 {
		o.Text, _ = a[1].(string)
	}
	return nil
}

// Lane is one issue's progress. Zero values mean "none"; times are epoch seconds.
type Lane struct {
	Repo       string   `json:"repo"`
	N          int      `json:"n"`
	Title      string   `json:"title"`
	Deps       []string `json:"deps"`
	Base       string   `json:"base"`
	Stage      string   `json:"stage"`
	SkipReason string   `json:"skip_reason"`
	Handle     *Handle  `json:"handle"`
	Handles    []Handle `json:"handles,omitempty"`
	PR         int      `json:"pr"`
	StartedAt  float64  `json:"started_at,omitempty"`
	EndedAt    float64  `json:"ended_at,omitempty"`

	Paused       bool         `json:"paused,omitempty"`
	PausedBy     string       `json:"paused_by,omitempty"`
	Held         string       `json:"held,omitempty"`
	NeedsYou     string       `json:"needs_you,omitempty"`
	Gate         string       `json:"gate,omitempty"`
	MergeError   string       `json:"merge_error,omitempty"`
	MergeFails   int          `json:"merge_fails,omitempty"`
	MergeAt      float64      `json:"merge_at,omitempty"`
	HoldMerge    bool         `json:"hold_merge,omitempty"`
	ForceMerge   bool         `json:"force_merge,omitempty"`
	LimitedUntil float64      `json:"limited_until,omitempty"`
	IdleSince    float64      `json:"idle_since,omitempty"`
	Nudged       string       `json:"nudged,omitempty"`
	CIFixed      string       `json:"ci_fixed,omitempty"`
	NoneSHA      string       `json:"none_sha,omitempty"`
	NoneSince    float64      `json:"none_since,omitempty"`
	Channel      string       `json:"channel,omitempty"`
	Reviewer     string       `json:"reviewer,omitempty"`
	Outbox       []OutboxItem `json:"outbox,omitempty"`
	Restart      bool         `json:"restart,omitempty"`
	AfkRetries   int          `json:"afk_retries,omitempty"`
	AfkRetryAt   float64      `json:"afk_retry_at,omitempty"`
	AfkRetryFor  string       `json:"afk_retry_for,omitempty"`

	Extra map[string]json.RawMessage `json:"-"`
}

// Key is the IssueKey "owner/name#n".
func Key(repo string, n int) string { return repo + "#" + strconv.Itoa(n) }

// Key of the lane.
func (l *Lane) Key() string { return Key(l.Repo, l.N) }

// Event is one line of the dispatch log.
type Event struct {
	At   float64 `json:"at"`
	Lane *string `json:"lane"`
	Kind string  `json:"kind"`
	Text string  `json:"text"`
}

// Dispatch is dispatches/<id>.json.
type Dispatch struct {
	ID        string            `json:"id"`
	Epic      *string           `json:"epic"`
	Title     string            `json:"title"`
	Runner    string            `json:"runner"`
	Settings  Settings          `json:"settings"`
	State     string            `json:"state"`
	Lanes     map[string]*Lane  `json:"lanes"`
	Events    []Event           `json:"events"`
	CreatedAt float64           `json:"created_at"`
	EndedAt   float64           `json:"ended_at,omitempty"`
	Issues    []string          `json:"issues,omitempty"`
	Added     []string          `json:"added,omitempty"` // issues added to an epic dispatch by hand
	SyncedAt  float64           `json:"synced_at,omitempty"`
	SeenDone  bool              `json:"seen_done,omitempty"`
	EndReqs   []string          `json:"end_requests,omitempty"`
	FinalPRs  map[string]string `json:"final_prs,omitempty"`
	FinalGr   map[string]Handle `json:"final_grinds,omitempty"`
	QA        *Handle           `json:"qa,omitempty"`

	Extra map[string]json.RawMessage `json:"-"`
}

// Repo is the dispatch's repo: the epic's, else the repo of its listed issues.
func (d *Dispatch) Repo() string {
	switch {
	case d.Epic != nil:
		r, _, _ := strings.Cut(*d.Epic, "#")
		return r
	case len(d.Issues) > 0:
		r, _, _ := strings.Cut(d.Issues[0], "#")
		return r
	}
	for _, l := range d.Lanes {
		return l.Repo
	}
	return ""
}

// SortedKeys lists the lane keys by (n, key).
func (d *Dispatch) SortedKeys() []string {
	keys := make([]string, 0, len(d.Lanes))
	for k := range d.Lanes {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		a, b := d.Lanes[keys[i]], d.Lanes[keys[j]]
		if a.N != b.N {
			return a.N < b.N
		}
		return keys[i] < keys[j]
	})
	return keys
}

// AddEvent appends to the log (cap MaxEvents) and returns the event.
func (d *Dispatch) AddEvent(lane, kind, text string, now float64) Event {
	e := Event{At: now, Lane: Ptr(lane), Kind: kind, Text: text}
	if len(d.Events) >= MaxEvents {
		d.Events = append([]Event(nil), d.Events[len(d.Events)-(MaxEvents-1):]...)
	}
	d.Events = append(d.Events, e)
	return e
}

// NewID makes a dispatch id: 12 lowercase hex.
func NewID() string {
	var b [6]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

// ---- JSON with unknown-key preservation ----

func keysOf(t reflect.Type) map[string]bool {
	m := map[string]bool{}
	for i := 0; i < t.NumField(); i++ {
		name, _, _ := strings.Cut(t.Field(i).Tag.Get("json"), ",")
		if name != "" && name != "-" {
			m[name] = true
		}
	}
	return m
}

var (
	laneKeys     = keysOf(reflect.TypeOf(Lane{}))
	dispatchKeys = keysOf(reflect.TypeOf(Dispatch{}))
)

func extraOf(b []byte, known map[string]bool) map[string]json.RawMessage {
	var all map[string]json.RawMessage
	if json.Unmarshal(b, &all) != nil {
		return nil
	}
	var out map[string]json.RawMessage
	for k, v := range all {
		if !known[k] {
			if out == nil {
				out = map[string]json.RawMessage{}
			}
			out[k] = v
		}
	}
	return out
}

func mergeExtra(b []byte, extra map[string]json.RawMessage, known map[string]bool) ([]byte, error) {
	if len(extra) == 0 {
		return b, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, err
	}
	for k, v := range extra {
		if _, ok := m[k]; !ok && !known[k] {
			m[k] = v
		}
	}
	return json.Marshal(m)
}

type laneAlias Lane

func (l *Lane) UnmarshalJSON(b []byte) error {
	var a laneAlias
	if err := json.Unmarshal(b, &a); err != nil {
		return err
	}
	a.Extra = extraOf(b, laneKeys)
	if a.Deps == nil {
		a.Deps = []string{}
	}
	*l = Lane(a)
	return nil
}

func (l Lane) MarshalJSON() ([]byte, error) {
	if l.Deps == nil {
		l.Deps = []string{}
	}
	b, err := json.Marshal(laneAlias(l))
	if err != nil {
		return nil, err
	}
	return mergeExtra(b, l.Extra, laneKeys)
}

type dispatchAlias Dispatch

func (d *Dispatch) UnmarshalJSON(b []byte) error {
	a := dispatchAlias{Settings: Defaults()} // records saved before a key existed read its default
	if err := json.Unmarshal(b, &a); err != nil {
		return err
	}
	a.Extra = extraOf(b, dispatchKeys)
	if a.Lanes == nil {
		a.Lanes = map[string]*Lane{}
	}
	*d = Dispatch(a)
	return nil
}

func (d Dispatch) MarshalJSON() ([]byte, error) {
	if d.Lanes == nil {
		d.Lanes = map[string]*Lane{}
	}
	if d.Events == nil {
		d.Events = []Event{}
	}
	b, err := json.Marshal(dispatchAlias(d))
	if err != nil {
		return nil, err
	}
	return mergeExtra(b, d.Extra, dispatchKeys)
}
