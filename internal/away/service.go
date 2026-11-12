package away

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Sessions is what away needs from sessions.Manager (which satisfies it).
type Sessions interface {
	List(f sessions.Filter) []sessions.Record
	Get(id string) (sessions.Record, error)
	Update(id string, fn func(*sessions.Record) error) (sessions.Record, error)
	Public(r sessions.Record) sessions.Session
	Alive(id string) bool
	Launch(ctx context.Context, s sessions.Spec) (sessions.Record, error)
	Stop(ctx context.Context, id string) (sessions.Record, error)
	Resume(ctx context.Context, id, text string) error
	ResumeStopped(ctx context.Context, id, accountLabel string) (sessions.Record, error)
	SendPrompt(ctx context.Context, id, text string, limit int) (string, error)
	ClaimAnswer(id, roundID string) (*sessions.Round, bool)
	RestoreRound(id string, r sessions.Round) error
	UpdatePending(id, roundID string, fn func(*sessions.Round)) error
	FinalText(id string) string
}

// Risk is the jev client (jev.Client satisfies it).
type Risk interface {
	Status() string
	Ask(ctx context.Context, point, kind, question, text string, options map[string]string, levels []string) jev.Answer
}

// Agents gives the answerer's body check and its tools line (prompts.Registry satisfies it).
type Agents interface {
	Agent(name string) (body string, tools []string, err error)
}

// Notifier is notify.Service.
type Notifier interface {
	Notify(event string, n notify.Note)
}

// StuckLane is a dispatch lane that holds or needs the owner for a reason other than a question.
// The dispatch package lists only lanes of running or paused dispatches, never user-paused ones
// and never "waiting on you".
type StuckLane struct {
	Dispatch string
	Lane     string // lane key
	Issue    int
	Repo     string
	Why      string
}

// Lanes is the optional dispatch hook for the lane retry ladder.
type Lanes interface {
	Stuck() []StuckLane
	Retry(dispatch, lane string) error
}

// Deps wires a Service. Lanes, Risk, Notify and Bus may be nil.
type Deps struct {
	Home     *home.Home
	Bus      *events.Bus
	Sessions Sessions
	Risk     Risk
	Agents   Agents
	Notify   Notifier
	Lanes    Lanes
	Now      func() time.Time
}

type roundState struct {
	attempts int
	err      string // last start failure
	fail     string // last answerer failure
	answerer string // last answerer id (for the held row)
}

// Service is Away mode.
type Service struct {
	d Deps
	h *home.Home

	tickMu sync.Mutex
	mu     sync.Mutex
	ctx    context.Context
	rounds map[string]*roundState
	flight map[string]bool
	sem    chan struct{}
	wg     sync.WaitGroup
}

// New builds the service.
func New(d Deps) *Service {
	return &Service{d: d, h: d.Home, ctx: context.Background(), rounds: map[string]*roundState{},
		flight: map[string]bool{}, sem: make(chan struct{}, 2)}
}

// Wait blocks until the risk workers in flight are done (tests).
func (s *Service) Wait() { s.wg.Wait() }

func (s *Service) publish() {
	if s.d.Bus != nil {
		s.d.Bus.Publish(events.TUsage, map[string]any{"kind": "away"})
	}
}

// Active reports whether the window is open.
func (s *Service) Active() bool {
	st := s.load()
	return st.Started > 0 && st.active(s.nowF())
}

// Start runs the 5 s tick until ctx ends; a panic in a tick is logged.
func (s *Service) Start(ctx context.Context) {
	s.mu.Lock()
	s.ctx = ctx
	s.mu.Unlock()
	go func() {
		t := time.NewTicker(TickSeconds * time.Second)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				s.safeTick(ctx)
			}
		}
	}()
}

func (s *Service) safeTick(ctx context.Context) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("away: tick panic: %v", r)
		}
	}()
	s.Tick(ctx)
}

// Public is the header state.
func (s *Service) Public() Away {
	st := s.load()
	now := s.nowF()
	a := Away{Active: st.Started > 0 && st.active(now), Decisions: len(st.Log)}
	if st.Started > 0 {
		v := st.Started
		a.Started = &v
		u := st.Until
		a.Until = &u
	}
	if a.Active {
		a.Held = s.heldNow(st)
	}
	if st.summaryVisible() {
		log := st.Log
		if log == nil {
			log = []Entry{}
		}
		a.Summary = &Summary{Started: st.Started, Ended: st.Until, Held: st.HeldAtEnd, Log: log}
	}
	return a
}

// heldNow counts sessions waiting on the owner, plus failed ones this window that cannot be
// resumed further.
func (s *Service) heldNow(st state) int {
	if s.d.Sessions == nil {
		return 0
	}
	started := time.Unix(int64(st.Started), 0)
	n := 0
	for _, r := range s.d.Sessions.List(sessions.Filter{}) {
		switch r.Status {
		case sessions.StWaiting:
			n++
		case sessions.StFailed:
			if t, ok := parseISO(r.EndedAt); ok && !t.Before(started.Truncate(time.Second)) &&
				(r.SessionID == "" || extraInt(r, "afk_retries") >= maxRetryRounds) {
				n++
			}
		}
	}
	return n
}

// Begin opens or extends the window: now < until <= now+24h.
func (s *Service) Begin(until int64) (Away, error) {
	now := s.nowF()
	u := float64(until)
	if until <= 0 || u <= now || u > now+MaxSeconds {
		return Away{}, errs.Invalid("until must be a time within the next 24 hours")
	}
	_, err := s.update(func(st *state) error {
		if st.Started > 0 && st.active(now) {
			st.Until = u
			return nil
		}
		*st = state{Started: now, Until: u, Log: []Entry{}, Lanes: st.Lanes}
		return nil
	})
	if err != nil {
		return Away{}, err
	}
	s.mu.Lock()
	s.rounds = map[string]*roundState{}
	s.mu.Unlock()
	s.publish()
	return s.Public(), nil
}

// End closes the window now and sends the summary push at once.
func (s *Service) End() (Away, error) {
	now := s.nowF()
	changed := false
	_, err := s.update(func(st *state) error {
		if st.Started > 0 && st.active(now) {
			st.Until = now
			changed = true
		}
		return nil
	})
	if err != nil {
		return Away{}, err
	}
	if changed {
		s.safeTick(context.Background())
	}
	s.publish()
	return s.Public(), nil
}

// Dismiss hides the summary.
func (s *Service) Dismiss() (Away, error) {
	_, err := s.update(func(st *state) error { st.Dismissed = true; return nil })
	if err != nil {
		return Away{}, err
	}
	s.publish()
	return s.Public(), nil
}

// Tick runs one pass. Exposed for tests.
func (s *Service) Tick(ctx context.Context) {
	s.tickMu.Lock()
	defer s.tickMu.Unlock()
	st := s.load()
	if st.Started == 0 || s.d.Sessions == nil {
		return
	}
	now := s.nowF()
	if !st.active(now) {
		if !st.Ended {
			s.finish(ctx, st)
		}
		return
	}
	all := s.d.Sessions.List(sessions.Filter{Answerers: true})
	var answerers, others []sessions.Record
	byID := map[string]sessions.Record{}
	for _, r := range all {
		byID[r.ID] = r
		if r.Role == answererRole {
			answerers = append(answerers, r)
		} else {
			others = append(others, r)
		}
	}
	s.sweep(ctx, answerers, byID)
	var rows []Entry
	for _, r := range others {
		rows = append(rows, s.safeRound(ctx, st, r, answerers)...)
	}
	for _, r := range others {
		rows = append(rows, s.retry(st, r)...)
	}
	rows = append(rows, s.retryLanes(ctx)...)
	if len(rows) == 0 {
		return
	}
	_, _ = s.update(func(cur *state) error {
		if cur.Started != st.Started {
			return nil
		}
		cur.Log = append(cur.Log, rows...)
		if n := len(cur.Log) - MaxLog; n > 0 {
			cur.Log = append([]Entry(nil), cur.Log[n:]...)
		}
		return nil
	})
	s.publish()
}

func (s *Service) safeRound(ctx context.Context, st state, r sessions.Record, answerers []sessions.Record) (rows []Entry) {
	defer func() {
		if p := recover(); p != nil {
			log.Printf("away: round %s: %v", r.ID, p)
		}
	}()
	return s.round(ctx, st, r, answerers)
}

// finish ends the window once: stop answerers, freeze the held count, push the summary.
func (s *Service) finish(ctx context.Context, st state) {
	for _, a := range s.d.Sessions.List(sessions.Filter{Answerers: true}) {
		if a.Role != answererRole || !a.Status.Live() {
			continue
		}
		_, _ = s.d.Sessions.Stop(ctx, a.ID)
		if pid, rid := extraString(a, "answers_for"), extraString(a, "answers_round"); pid != "" {
			_ = s.d.Sessions.UpdatePending(pid, rid, func(rd *sessions.Round) { rd.Answerer = nil })
		}
	}
	held := s.heldNow(st)
	done := false
	cur, _ := s.update(func(c *state) error {
		if c.Ended || c.Started != st.Started {
			return nil
		}
		c.Ended, c.HeldAtEnd, c.Lanes = true, held, nil
		done = true
		return nil
	})
	if !done {
		return
	}
	s.publish()
	if s.d.Notify != nil {
		s.d.Notify.Notify("afk", notify.Note{
			ID:   "afk-" + strconv.FormatInt(int64(st.Started), 10),
			Text: fmt.Sprintf("%d decision(s) made, %d waiting on you", len(cur.Log), held),
		})
	}
}

// sweep stops answerers whose parent no longer waits on their round.
func (s *Service) sweep(ctx context.Context, answerers []sessions.Record, byID map[string]sessions.Record) {
	for _, a := range answerers {
		if !a.Status.Live() {
			continue
		}
		p, ok := byID[extraString(a, "answers_for")]
		rd := p.PendingQuestion
		if ok && p.Status == sessions.StWaiting && rd != nil && rd.Status == "pending" &&
			rd.ID == extraString(a, "answers_round") {
			continue
		}
		_, _ = s.d.Sessions.Stop(ctx, a.ID)
	}
}
