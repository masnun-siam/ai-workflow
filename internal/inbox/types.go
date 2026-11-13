// Package inbox derives "what needs you" from sessions, GitHub snapshots, grinds, releases,
// dispatches and the machine's setup state (G§4.2, API §4 InboxItem). Items are never stored: they
// disappear when their cause does. The Builder also ranks them (group, urgency, newest) and
// publishes an `inbox` event when the set changes.
package inbox

import (
	"encoding/json"
	"sort"
	"time"

	"github.com/masnun-siam/setu/internal/sessions"
)

// Group is an item's priority class, in rank order.
const (
	GBlock  = "block"
	GAnswer = "answer"
	GDecide = "decide"
	GFix    = "fix"
	GSetup  = "setup"
	GWait   = "wait"
)

var groupOrder = map[string]int{GBlock: 0, GAnswer: 1, GDecide: 2, GFix: 3, GSetup: 4, GWait: 5}

// Item types (API §4 InboxType).
const (
	TGHAuth          = "gh_auth"
	TBlubirdMissing  = "blubird_missing"
	TQuestion        = "question"
	TPRDApproval     = "prd_approval"
	TSessionFailed   = "session_failed"
	TLimited         = "limited"
	TQueued          = "queued"
	TReviewCap       = "review_cap"
	TReviewApproved  = "review_approved"
	TGrindPaused     = "grind_paused"
	TNeedsCleanup    = "needs_cleanup"
	TPRConflict      = "pr_conflict"
	TPRReady         = "pr_ready"
	TReleaseNote     = "release_note"
	TDispatchNeeds   = "dispatch_needs"
	TDispatchHeld    = "dispatch_held"
	TDispatchStalled = "dispatch_stalled"
	TDispatchMerge   = "dispatch_merge"
	TDispatchLimited = "dispatch_limited"
	TDispatchDone    = "dispatch_done"
	TAwaySummary     = "away_summary"
	TRepoUnpublished = "repo_unpublished"
)

// Action is a server-built button (API §4). An action with Open set navigates instead of fetching.
type Action struct {
	Key     string `json:"key"`
	Label   string `json:"label"`
	Method  string `json:"method"`
	Path    string `json:"path"`
	Body    any    `json:"body,omitempty"`
	Toast   string `json:"toast"`
	Primary bool   `json:"primary,omitempty"`
	Clears  bool   `json:"clears,omitempty"`
	Confirm string `json:"confirm,omitempty"`
	Open    string `json:"open,omitempty"`
}

// Links are the places an item or card points at.
type Links struct {
	Issue   string `json:"issue,omitempty"`
	PR      string `json:"pr,omitempty"`
	Session string `json:"session,omitempty"`
	PRD     string `json:"prd,omitempty"`
}

// Item is one inbox row.
type Item struct {
	Key       string          `json:"key"`
	Group     string          `json:"group"`
	Type      string          `json:"type"`
	Kind      string          `json:"kind"`
	Title     string          `json:"title"`
	Repo      *string         `json:"repo"`
	At        *string         `json:"at"`
	Urgency   *int            `json:"urgency"`
	SessionID string          `json:"session_id,omitempty"`
	Round     *sessions.Round `json:"round,omitempty"`
	Note      string          `json:"note,omitempty"`
	Detail    []string        `json:"detail,omitempty"`
	Links     Links           `json:"links"`
	Actions   []Action        `json:"actions"`

	// Anchors tie the item to River cards ("session:<id>", "issue:o/r#n", "pr:o/r#n",
	// "prd:o/r:path", "release:<id>", "dispatch:<id>"). Not serialised.
	Anchors []string `json:"-"`

	text string // what the urgency scorer reads ("" = unscorable)
}

// List is GET /api/inbox.
type List struct {
	Items []Item   `json:"items"`
	Stale []string `json:"stale"`
	Count int      `json:"count"` // items not in group "wait"
}

func sp(s string) *string { return &s }

// parseTime reads an RFC 3339 stamp, with or without sub-seconds.
func parseTime(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		t, err = time.Parse("2006-01-02T15:04:05.999999999-07:00", s)
	}
	return t, err == nil
}

func (it Item) atTime() time.Time {
	if it.At == nil {
		return time.Time{}
	}
	t, _ := parseTime(*it.At)
	return t
}

// Rank sorts by group order, then urgency (nil = 0) high first, then newest first (nil = oldest),
// then key for a stable order.
func Rank(items []Item) {
	sort.SliceStable(items, func(i, j int) bool {
		a, b := items[i], items[j]
		if ga, gb := groupOrder[a.Group], groupOrder[b.Group]; ga != gb {
			return ga < gb
		}
		ua, ub := 0, 0
		if a.Urgency != nil {
			ua = *a.Urgency
		}
		if b.Urgency != nil {
			ub = *b.Urgency
		}
		if ua != ub {
			return ua > ub
		}
		if ta, tb := a.atTime(), b.atTime(); !ta.Equal(tb) {
			return ta.After(tb)
		}
		return a.Key < b.Key
	})
}

// Convert re-encodes v as T through JSON. The mirror types below carry the API JSON names, so a
// sibling package's own type converts with it when the wiring needs an adapter.
func Convert[T any](v any) T {
	var out T
	b, err := json.Marshal(v)
	if err != nil {
		return out
	}
	_ = json.Unmarshal(b, &out)
	return out
}

// ---- mirrors of sibling packages' public shapes (API §4) ----

// GrindStatus mirrors grind.Status.
type GrindStatus struct {
	Repo     string  `json:"repo"`
	PR       int     `json:"pr"`
	State    string  `json:"state"` // none | idle | running | paused | approved | done
	Mode     *string `json:"mode"`
	Rounds   int     `json:"rounds"`
	Reason   *string `json:"reason"`
	Thread   *string `json:"thread"`
	Updated  *string `json:"updated"`
	NextPoll *string `json:"next_poll"`
	Session  *string `json:"session"`
}

// Lane mirrors a dispatch lane.
type Lane struct {
	Key          string  `json:"key"`
	Repo         string  `json:"repo"`
	N            int     `json:"n"`
	Title        string  `json:"title"`
	Stage        string  `json:"stage"`
	PR           *int    `json:"pr"`
	NeedsYou     *string `json:"needs_you"`
	Stalled      *string `json:"stalled"`
	Held         *string `json:"held"`
	Gate         *string `json:"gate"`
	Paused       bool    `json:"paused"`
	LimitedUntil *int64  `json:"limited_until"`
	Session      *string `json:"session"`
}

// Dispatch mirrors a dispatch's public view.
type Dispatch struct {
	ID       string  `json:"id"`
	Epic     *string `json:"epic"`
	Title    string  `json:"title"`
	State    string  `json:"state"` // running | paused | done | cancelled
	Lanes    []Lane  `json:"lanes"`
	EndedAt  *int64  `json:"ended_at"`
	SeenDone bool    `json:"seen_done,omitempty"`
	Settings struct {
		FeatureBranch *string `json:"feature_branch"`
	} `json:"settings"`
}

// Release mirrors release.Release.
type Release struct {
	ID          string  `json:"id"`
	Repo        string  `json:"repo"`
	Head        string  `json:"head"`
	Base        string  `json:"base"`
	Stage       string  `json:"stage"` // cut | grind | merge | notify | done | skipped | failed | dry_run
	DryRun      bool    `json:"dry_run"`
	PR          *int    `json:"pr"`
	PRURL       *string `json:"pr_url"`
	Thread      *string `json:"thread"`
	CutSession  *string `json:"cut_session"`
	NoteSession *string `json:"note_session"`
	Note        *string `json:"note"`
	NotePosted  *string `json:"note_posted_at"`
	Error       *string `json:"error"`
	UpdatedAt   string  `json:"updated_at"`
}

// ReleaseRepo mirrors release.ReleaseRepo.
type ReleaseRepo struct {
	Repo       string  `json:"repo"`
	Name       string  `json:"name"`
	Head       string  `json:"head"`
	Base       string  `json:"base"`
	Ahead      *int    `json:"ahead"`
	PRsWaiting *int    `json:"prs_waiting"`
	Open       *string `json:"open"`
}

// Panel mirrors review.Panel as the inbox needs it.
type Panel struct {
	ID        string `json:"id"`
	Repo      string `json:"repo"`
	Artifact  string `json:"artifact"`
	State     string `json:"state"` // running | approved | cap reached | failed
	Round     int    `json:"round"`
	MaxRounds int    `json:"max_rounds"`
	// RootSession is the session that owns the artifact (the PRD interview), if any.
	RootSession *string `json:"root_session"`
	Status      struct {
		Approved int `json:"approved"`
		Total    int `json:"total"`
	} `json:"status"`
}

// Coordinator mirrors dispatch.Coordinator.
type Coordinator struct {
	Run         string  `json:"run"`
	Repo        string  `json:"repo"`
	Source      string  `json:"source"`
	Destination string  `json:"destination"`
	Session     *string `json:"session"`
	Live        bool    `json:"live"`
	Queue       []struct {
		Issue int    `json:"issue"`
		State string `json:"state"`
		Title string `json:"title"`
	} `json:"queue"`
	Events []string `json:"events"`
}

// AwayLog is passed through untouched.
type Away struct {
	Active    bool   `json:"active"`
	Until     *int64 `json:"until"`
	Started   *int64 `json:"started"`
	Decisions int    `json:"decisions"`
	Held      int    `json:"held"`
	Summary   *struct {
		Started int64             `json:"started"`
		Ended   int64             `json:"ended"`
		Held    int               `json:"held"`
		Log     []json.RawMessage `json:"log"`
	} `json:"summary"`
}
