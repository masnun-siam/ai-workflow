// Package views builds the aggregate screens: River (the pipeline), Ops, Me, and GET /api/status.
// Everything is derived on request from the snapshots, sessions, grinds, releases and the inbox; the
// UI renders the server-built cards and runs their actions as given.
package views

import (
	"context"
	"encoding/json"
	"strings"
	"sync/atomic"
	"time"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

// SessionsAPI is satisfied by *sessions.Manager.
type SessionsAPI interface {
	inbox.Sessions
	Stats() sessions.SessionStats
	Limits() map[string]sessions.Limit
}

// Steps is satisfied by *prompts.Registry.
type Steps interface {
	Steps() []prompts.Step
	Step(id string) (prompts.Step, bool)
}

// DispatchAPI is dispatch.Service, adapted.
type DispatchAPI interface {
	inbox.Dispatches
	Coordinators() []inbox.Coordinator
}

// UsageAPI is satisfied by *claude.Usage.
type UsageAPI interface {
	Snapshot() map[string]claude.AccountUsage
}

// Accounts is satisfied by *settings.Store.
type Accounts interface {
	Accounts() []settings.Account
}

// Budget is satisfied by *poller.Poller.
type Budget interface {
	Budget() gh.RateLimit
}

// Deps wires a Service. Every field except Inbox-less River is optional.
type Deps struct {
	Inbox     *inbox.Builder
	Sessions  SessionsAPI
	Snapshots inbox.Snapshots
	Products  inbox.Products
	Prompts   Steps
	Grinds    inbox.Grinds
	Dispatch  DispatchAPI
	Releases  inbox.Releases
	Accounts  Accounts
	Usage     UsageAPI
	Blubird   inbox.BlubirdStatus
	GH        inbox.GHAuth
	Away      inbox.AwayState
	Poller    Budget
	Home      *home.Home

	Version string
	BootID  func() string
	// NoteChannel names the Slack channel release notes go to ("" = "Slack").
	NoteChannel func() string
	// Log returns up to a few recent lines of a live session for its card ("" lines are dropped).
	Log func(sessionID string) []string
	Now func() time.Time
}

// Service builds the views.
type Service struct {
	d       Deps
	present atomic.Int64 // unix nanos of the last /api/status call
}

// New returns a Service.
func New(d Deps) *Service { return &Service{d: d} }

func (s *Service) now() time.Time {
	if s.d.Now != nil {
		return s.d.Now()
	}
	return time.Now()
}

const presentWindow = 120 * time.Second

// UIPresent reports a UI that called /api/status within 120 s (the wiring ORs it with the SSE
// subscriber count for usage polling).
func (s *Service) UIPresent() bool {
	t := s.present.Load()
	return t != 0 && s.now().Sub(time.Unix(0, t)) < presentWindow
}

// ---- shared shapes ----

// SessionBrief is a short session reference (API §4).
type SessionBrief struct {
	ID        string          `json:"id"`
	Status    sessions.Status `json:"status"`
	StartedAt string          `json:"started_at"`
	EndedAt   *string         `json:"ended_at"`
	Cost      *float64        `json:"cost"`
}

func brief(s sessions.Session) *SessionBrief {
	return &SessionBrief{ID: s.ID, Status: s.Status, StartedAt: s.StartedAt, EndedAt: s.EndedAt, Cost: s.Cost}
}

func parseTime(t string) (time.Time, bool) {
	if t == "" {
		return time.Time{}, false
	}
	v, err := time.Parse(time.RFC3339Nano, t)
	if err != nil {
		v, err = time.Parse("2006-01-02T15:04:05.999999999-07:00", t)
	}
	return v, err == nil
}

// newest returns the record that started last.
func newest(recs []sessions.Record) (sessions.Record, bool) {
	var best sessions.Record
	ok := false
	for _, r := range recs {
		if !ok || r.StartedAt > best.StartedAt {
			best, ok = r, true
		}
	}
	return best, ok
}

// AccountUsage is claude.AccountUsage with the live limit filled in.
func (s *Service) usage() []claude.AccountUsage {
	out := []claude.AccountUsage{}
	if s.d.Usage == nil {
		return out
	}
	snap := s.d.Usage.Snapshot()
	var limits map[string]sessions.Limit
	if s.d.Sessions != nil {
		limits = s.d.Sessions.Limits()
	}
	fill := func(u claude.AccountUsage) claude.AccountUsage {
		if l, ok := limits[u.Cmd]; ok {
			u.Limit = claude.Limit{LimitedUntil: l.LimitedUntil}
			if l.Warning != nil {
				w := &claude.LimitWarning{Type: l.Warning.Type}
				if l.Warning.Utilization != nil {
					w.Utilization = *l.Warning.Utilization
				}
				u.Limit.Warning = w
			}
		}
		return u
	}
	seen := map[string]bool{}
	if s.d.Accounts != nil {
		for _, a := range s.d.Accounts.Accounts() {
			u, ok := snap[a.Cmd]
			if !ok {
				u = claude.AccountUsage{Label: a.Label, Cmd: a.Cmd}
			}
			seen[a.Cmd] = true
			out = append(out, fill(u))
		}
	}
	var rest []string
	for cmd := range snap {
		if !seen[cmd] {
			rest = append(rest, cmd)
		}
	}
	sortStrings(rest)
	for _, cmd := range rest {
		out = append(out, fill(snap[cmd]))
	}
	return out
}

func sortStrings(s []string) {
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}

// ---- status ----

// Status is GET /api/status.
type Status struct {
	Version  string                `json:"version"`
	BootID   string                `json:"boot_id"`
	Blubird  blubird.Status        `json:"blubird"`
	GH       gh.Auth               `json:"gh"`
	Usage    []claude.AccountUsage `json:"usage"`
	Away     inbox.Away            `json:"away"`
	Migrated bool                  `json:"migrated"`
	Poller   PollerBudget          `json:"poller"`
}

// PollerBudget is the GraphQL budget; both are null while unknown.
type PollerBudget struct {
	Remaining *int    `json:"remaining"`
	ResetAt   *string `json:"reset_at"`
}

// Status builds the status document and records that a UI is present.
func (s *Service) Status(ctx context.Context) Status {
	s.present.Store(s.now().UnixNano())
	st := Status{Version: s.d.Version, Usage: s.usage(), GH: gh.Auth{OK: true}}
	if s.d.BootID != nil {
		st.BootID = s.d.BootID()
	}
	if s.d.Blubird != nil {
		st.Blubird = s.d.Blubird.Status()
	}
	if st.Blubird.Skills == nil {
		st.Blubird.Skills = []string{}
	}
	if st.Blubird.Hooks == nil {
		st.Blubird.Hooks = []string{}
	}
	if s.d.GH != nil {
		st.GH = s.d.GH.Get(ctx)
	}
	if s.d.Away != nil {
		st.Away = s.d.Away.Public()
	}
	if st.Away.Summary != nil && st.Away.Summary.Log == nil {
		st.Away.Summary.Log = []json.RawMessage{}
	}
	if s.d.Home != nil {
		st.Migrated = fileExists(s.d.Home.Path(".migrated"))
	}
	if s.d.Poller != nil {
		b := s.d.Poller.Budget()
		if b.Remaining >= 0 {
			r := b.Remaining
			st.Poller.Remaining = &r
		}
		if !b.ResetAt.IsZero() {
			t := b.ResetAt.UTC().Format(time.RFC3339)
			st.Poller.ResetAt = &t
		}
	}
	return st
}

func repoName(slug string) string {
	if i := strings.LastIndexByte(slug, '/'); i >= 0 {
		return slug[i+1:]
	}
	return slug
}
