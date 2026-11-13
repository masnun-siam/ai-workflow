package views

import (
	"context"
	"time"

	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/sessions"
)

// DayEnd is the personal end-of-day card.
type DayEnd struct {
	Date        string `json:"date"`
	Reconciled  bool   `json:"reconciled"`
	MissingDays int    `json:"missing_days"`
	// MissingDates lists those days (YYYY-MM-DD, oldest first), so the UI can show which.
	MissingDates []string      `json:"missing_dates"`
	Last         *SessionBrief `json:"last"`
}

// Weekly is the weekly-review card.
type Weekly struct {
	Week    int           `json:"week"`
	Drafted bool          `json:"drafted"`
	Last    *SessionBrief `json:"last"`
}

// Me is GET /api/me.
type Me struct {
	DayEnd  DayEnd                `json:"day_end"`
	Weekly  Weekly                `json:"weekly"`
	Usage   []claude.AccountUsage `json:"usage"`
	Cost    sessions.SessionStats `json:"cost"`
	Actions []inbox.Action        `json:"actions"`
}

func sameDay(a, b time.Time) bool {
	ay, am, ad := a.Date()
	by, bm, bd := b.Date()
	return ay == by && am == bm && ad == bd
}

// Me builds the personal screen. A day counts as reconciled when a day-end-reconcile session that
// started that (local) day finished done; missing_days counts the weekdays of this month before today
// without one. The week is drafted when a weekly-review session started this ISO week and did not
// fail or stop.
func (s *Service) Me(ctx context.Context) Me {
	now := s.now()
	loc := now.Location()
	m := Me{Usage: s.usage(), Actions: []inbox.Action{
		inbox.Start("d", "Run day-end", "Started day-end-reconcile", map[string]any{"step": "day-end-reconcile"}).WithPrimary(),
		inbox.Start("w", "Draft weekly review", "Started weekly-review", map[string]any{"step": "weekly-review"}),
	}}
	m.DayEnd.Date = now.Format("2006-01-02")
	m.DayEnd.MissingDates = []string{}
	_, m.Weekly.Week = now.ISOWeek()
	if s.d.Sessions == nil {
		return m
	}
	m.Cost = s.d.Sessions.Stats()
	doneDays := map[string]bool{}
	recs := s.d.Sessions.List(sessions.Filter{Step: "day-end-reconcile"})
	for _, r := range recs {
		if t, ok := parseTime(r.StartedAt); ok && r.Status == sessions.StDone {
			doneDays[t.In(loc).Format("2006-01-02")] = true
		}
	}
	m.DayEnd.Reconciled = doneDays[m.DayEnd.Date]
	for d := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, loc); d.Before(time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, loc)); d = d.AddDate(0, 0, 1) {
		if wd := d.Weekday(); wd == time.Saturday || wd == time.Sunday {
			continue
		}
		if !doneDays[d.Format("2006-01-02")] {
			m.DayEnd.MissingDays++
			m.DayEnd.MissingDates = append(m.DayEnd.MissingDates, d.Format("2006-01-02"))
		}
	}
	if r, ok := newest(recs); ok {
		m.DayEnd.Last = brief(s.d.Sessions.Public(r))
	}
	wrecs := s.d.Sessions.List(sessions.Filter{Step: "weekly-review"})
	cy, cw := now.ISOWeek()
	for _, r := range wrecs {
		if t, ok := parseTime(r.StartedAt); ok {
			if y, w := t.In(loc).ISOWeek(); y == cy && w == cw && r.Status != sessions.StFailed && r.Status != sessions.StStopped {
				m.Weekly.Drafted = true
			}
		}
	}
	if r, ok := newest(wrecs); ok {
		m.Weekly.Last = brief(s.d.Sessions.Public(r))
	}
	return m
}
