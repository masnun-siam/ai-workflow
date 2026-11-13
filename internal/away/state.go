// Package away is Away mode: a timed autopilot that answers question rounds sessions asked via
// `setu ask`, retries failures and sums up at the end (W§3). State lives in afk.json.
package away

import (
	"encoding/json"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Limits of the window and of the answerer (W§3).
const (
	MaxSeconds     = 86400
	MaxLog         = 500
	TickSeconds    = 5
	RiskP          = 0.5
	WindowCostCap  = 10.0
	RoundCostCap   = 2.0
	MaxAttempts    = 2
	AnswerSeconds  = 600
	MaxWhy         = 300
	MaxChanges     = 50
	RiskQuestion   = "Is any recommended option irreversible or outward-facing: pushing, merging, publishing, deleting, posting, or spending money?"
	answererStep   = "away-answerer"
	answererRole   = "away-answerer"
	changeTextCap  = 60000
	maxRetryRounds = 4
)

// RetryDelays is the retry ladder in seconds.
var RetryDelays = [...]int64{120, 600, 1800, 3600}

// holdWords make a round wait for the human.
var holdWords = []string{"push", "merge", "delete", "force", "publish", "deploy", "release", "drop", "rm -rf", "post a comment"}

// EntryQuestion is a logged question with the chosen labels and the reason.
type EntryQuestion struct {
	Header        string            `json:"header"`
	Question      string            `json:"question"`
	MultiSelect   bool              `json:"multiSelect"`
	AllowFreeText bool              `json:"allowFreeText"`
	Options       []sessions.Option `json:"options"`
	Picked        []string          `json:"picked"`
	Why           string            `json:"why"`
	Other         *string           `json:"other,omitempty"`
}

// Entry is one log row (API AwayLog).
type Entry struct {
	At        float64         `json:"at"`
	Kind      string          `json:"kind"` // answer | held | retry
	Sid       string          `json:"sid"`
	Link      *sessions.Link  `json:"link"`
	Repo      *string         `json:"repo"`
	Command   string          `json:"command"`
	Question  string          `json:"question"`
	Picked    string          `json:"picked"`
	ID        string          `json:"id,omitempty"`
	Risk      *float64        `json:"risk,omitempty"`
	By        string          `json:"by,omitempty"`
	Questions []EntryQuestion `json:"questions,omitempty"`
	Answerer  string          `json:"answerer,omitempty"`
	Cost      *float64        `json:"cost,omitempty"`
	Changed   bool            `json:"changed,omitempty"`
	Reason    string          `json:"reason,omitempty"`
}

type laneRetry struct {
	Why     string  `json:"why"`
	N       int     `json:"n"`
	At      float64 `json:"at"`
	Stalled bool    `json:"stalled,omitempty"` // kept while the continued lane runs, so a lane that stalls again climbs the ladder
}

// state is afk.json.
type state struct {
	Started   float64              `json:"started"`
	Until     float64              `json:"until"`
	Log       []Entry              `json:"log"`
	Ended     bool                 `json:"ended"`
	HeldAtEnd int                  `json:"held_at_end"`
	Dismissed bool                 `json:"dismissed"`
	Lanes     map[string]laneRetry `json:"lane_retries,omitempty"`
}

func (st state) active(now float64) bool { return st.Until > now }

func (st state) summaryVisible() bool { return st.Ended && !st.Dismissed && st.Started > 0 }

// Away is the public state (API §4).
type Away struct {
	Active    bool     `json:"active"`
	Until     *float64 `json:"until"`
	Started   *float64 `json:"started"`
	Decisions int      `json:"decisions"`
	Held      int      `json:"held"`
	Summary   *Summary `json:"summary"`
}

// Summary is the end-of-window report.
type Summary struct {
	Started float64 `json:"started"`
	Ended   float64 `json:"ended"`
	Held    int     `json:"held"`
	Log     []Entry `json:"log"`
}

func (s *Service) path() string { return s.h.Path("afk.json") }

func (s *Service) load() state {
	var st state
	_ = home.ReadJSON(s.path(), &st)
	return st
}

func (s *Service) update(fn func(*state) error) (state, error) {
	return home.UpdateJSON(s.path(), fn)
}

func nowF(t time.Time) float64 { return float64(t.UnixNano()) / 1e9 }

func (s *Service) nowF() float64 { return nowF(s.now()) }

func (s *Service) now() time.Time {
	if s.d.Now != nil {
		return s.d.Now()
	}
	return time.Now()
}

func cut(v string, n int) string {
	if utf8.RuneCountInString(v) <= n {
		return v
	}
	return string([]rune(v)[:n])
}

func parseISO(v string) (time.Time, bool) {
	if v == "" {
		return time.Time{}, false
	}
	t, err := time.Parse(time.RFC3339, v)
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

func extraString(r sessions.Record, key string) string {
	raw, ok := r.Extra[key]
	if !ok {
		return ""
	}
	var s string
	if json.Unmarshal(raw, &s) != nil {
		return ""
	}
	return s
}

func extraInt(r sessions.Record, key string) int {
	raw, ok := r.Extra[key]
	if !ok {
		return 0
	}
	var f float64
	if json.Unmarshal(raw, &f) != nil {
		return 0
	}
	return int(f)
}

func extraHas(r sessions.Record, key string) bool {
	raw, ok := r.Extra[key]
	return ok && strings.TrimSpace(string(raw)) != "null"
}
