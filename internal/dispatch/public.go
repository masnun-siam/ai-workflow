package dispatch

import (
	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/sessions"
)

// LaneUsage is a lane's cost, tokens and elapsed seconds.
type LaneUsage struct {
	Cost    float64          `json:"cost"`
	Tokens  *sessions.Tokens `json:"tokens"`
	Seconds int64            `json:"seconds"`
}

// PublicLane is the API shape of a lane (§4 Lane).
type PublicLane struct {
	Key          string    `json:"key"`
	Repo         string    `json:"repo"`
	N            int       `json:"n"`
	Title        string    `json:"title"`
	Deps         []string  `json:"deps"`
	Stage        string    `json:"stage"`
	PR           *int      `json:"pr"`
	NeedsYou     *string   `json:"needs_you"`
	Stalled      *string   `json:"stalled"` // idle guard: stopped before a ready PR; needs_you is then null
	Held         *string   `json:"held"`
	Gate         *string   `json:"gate"`
	SkipReason   *string   `json:"skip_reason"`
	Paused       bool      `json:"paused"`
	PausedBy     *string   `json:"paused_by"`
	HoldMerge    bool      `json:"hold_merge"`
	LimitedUntil *float64  `json:"limited_until"`
	StartedAt    *float64  `json:"started_at"`
	EndedAt      *float64  `json:"ended_at"`
	Session      *string   `json:"session"`
	Usage        LaneUsage `json:"usage"`
	// Stranded says why a queued lane can never start as things stand ("blocked by skipped #N",
	// "dependency cycle"); SkippedDeps are its blockers that were skipped (lane action unblock drops them).
	Stranded    *string  `json:"stranded"`
	SkippedDeps []string `json:"skipped_deps"`
	Unblocked   []string `json:"unblocked"`
}

// Totals of a dispatch.
type Totals struct {
	Lanes  int     `json:"lanes"`
	Closed int     `json:"closed"`
	Cost   float64 `json:"cost"`
}

// PublicDispatch is the API shape of a dispatch (§4 Dispatch).
type PublicDispatch struct {
	ID        string            `json:"id"`
	Epic      *string           `json:"epic"`
	Issues    []string          `json:"issues,omitempty"`
	Title     string            `json:"title"`
	State     string            `json:"state"`
	Settings  store.Settings    `json:"settings"`
	Lanes     []PublicLane      `json:"lanes"`
	Totals    Totals            `json:"totals"`
	CreatedAt float64           `json:"created_at"`
	EndedAt   *float64          `json:"ended_at"`
	FinalPRs  map[string]string `json:"final_prs,omitempty"`
	SeenDone  bool              `json:"seen_done"`
	Events    []store.Event     `json:"events,omitempty"`
}

func fptr(v float64) *float64 {
	if v == 0 {
		return nil
	}
	return &v
}

// Public converts a dispatch to its API shape; full adds the event log.
func (s *Service) Public(d store.Dispatch, full bool) PublicDispatch {
	p := PublicDispatch{ID: d.ID, Epic: d.Epic, Issues: d.Issues, Title: d.Title, State: d.State, Settings: d.Settings,
		Lanes: []PublicLane{}, CreatedAt: d.CreatedAt, EndedAt: fptr(d.EndedAt), FinalPRs: d.FinalPRs, SeenDone: d.SeenDone}
	now := s.now()
	strands := Stranded(&d)
	lastAt := map[string]float64{}
	for _, e := range d.Events {
		if e.Lane != nil && e.At > lastAt[*e.Lane] {
			lastAt[*e.Lane] = e.At
		}
	}
	for _, k := range d.SortedKeys() {
		x := d.Lanes[k]
		cost, tok, hasTok := s.laneCost(x)
		l := PublicLane{Key: k, Repo: x.Repo, N: x.N, Title: x.Title, Deps: x.Deps, Stage: x.Stage,
			NeedsYou: store.Ptr(x.NeedsYou), Held: store.Ptr(x.Held), Gate: store.Ptr(x.Gate),
			SkipReason: store.Ptr(x.SkipReason), Paused: x.Paused, PausedBy: store.Ptr(x.PausedBy), HoldMerge: x.HoldMerge,
			LimitedUntil: fptr(x.LimitedUntil), StartedAt: fptr(x.StartedAt), EndedAt: fptr(x.EndedAt)}
		if l.Stalled = store.Ptr(x.Stalled); l.Stalled != nil {
			l.NeedsYou = nil
		}
		if l.Deps == nil {
			l.Deps = []string{}
		}
		l.SkippedDeps, l.Unblocked = SkippedDeps(&d, x), x.Unblocked
		if l.SkippedDeps == nil {
			l.SkippedDeps = []string{}
		}
		if l.Unblocked == nil {
			l.Unblocked = []string{}
		}
		if why, ok := strands[k]; ok {
			l.Stranded = &why
		}
		if Settled(x) { // nothing about a closed or skipped lane waits on you (older records kept the text)
			l.NeedsYou, l.Stalled, l.Held, l.Gate = nil, nil, nil, nil
			if x.EndedAt == 0 && lastAt[k] > 0 {
				l.EndedAt = fptr(lastAt[k])
			}
		}
		if x.PR != 0 {
			pr := x.PR
			l.PR = &pr
		}
		if x.Handle != nil {
			sid := x.Handle.Session
			l.Session = &sid
		}
		l.Usage.Cost = float64(int64(cost*10000+0.5)) / 10000
		if hasTok {
			t := tok
			l.Usage.Tokens = &t
		}
		if x.StartedAt != 0 {
			end := x.EndedAt
			if end == 0 && Settled(x) {
				end = lastAt[k]
			}
			if end == 0 {
				end = now
			}
			l.Usage.Seconds = int64(end - x.StartedAt)
		}
		p.Totals.Cost += l.Usage.Cost
		if x.Stage == store.StClosed {
			p.Totals.Closed++
		}
		p.Lanes = append(p.Lanes, l)
	}
	p.Totals.Lanes = len(p.Lanes)
	if full {
		p.Events = d.Events
		if p.Events == nil {
			p.Events = []store.Event{}
		}
	}
	return p
}
