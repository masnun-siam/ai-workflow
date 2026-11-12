package away

import (
	"context"
	"encoding/json"
	"fmt"
	"log"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/sessions"
)

func setExtra(r *sessions.Record, key string, v any) {
	if v == nil {
		delete(r.Extra, key)
		return
	}
	if r.Extra == nil {
		r.Extra = map[string]json.RawMessage{}
	}
	b, _ := json.Marshal(v)
	r.Extra[key] = b
}

// retry resumes failed sessions on the ladder 120/600/1800/3600 s (W§3.4). Answerers and held
// sessions are never retried.
func (s *Service) retry(st state, r sessions.Record) []Entry {
	if r.Role == answererRole || r.Hold {
		return nil
	}
	now := s.nowF()
	sm := s.d.Sessions
	switch r.Status {
	case sessions.StDone, sessions.StWaiting:
		if extraHas(r, "afk_retries") || extraHas(r, "afk_retry_at") || extraHas(r, "afk_retry_for") {
			_, _ = sm.Update(r.ID, func(x *sessions.Record) error {
				setExtra(x, "afk_retries", nil)
				setExtra(x, "afk_retry_at", nil)
				setExtra(x, "afk_retry_for", nil)
				return nil
			})
		}
		return nil
	case sessions.StFailed:
	default:
		return nil
	}
	ended, ok := parseISO(r.EndedAt)
	if r.SessionID == "" || !ok || float64(ended.Unix()) < st.Started-1 {
		return nil
	}
	n := extraInt(r, "afk_retries")
	if n >= maxRetryRounds {
		return nil
	}
	if extraString(r, "afk_retry_for") != r.EndedAt {
		at := now + float64(RetryDelays[n])
		_, _ = sm.Update(r.ID, func(x *sessions.Record) error {
			setExtra(x, "afk_retry_at", at)
			setExtra(x, "afk_retry_for", x.EndedAt)
			return nil
		})
		return nil
	}
	var at float64
	if raw, ok := r.Extra["afk_retry_at"]; ok {
		_ = json.Unmarshal(raw, &at)
	}
	if at > now {
		return nil
	}
	_, _ = sm.Update(r.ID, func(x *sessions.Record) error { setExtra(x, "afk_retries", n+1); return nil })
	ctx := context.Background()
	if _, err := sm.ResumeStopped(ctx, r.ID, ""); err != nil {
		if errs.KindOf(err) == errs.KConflict {
			_, _ = sm.Update(r.ID, func(x *sessions.Record) error { setExtra(x, "afk_retries", maxRetryRounds); return nil })
		}
		log.Printf("away: retry %s: %v", r.ID, err)
		return nil
	}
	e := s.base("retry", r, nil)
	e.Question = cut(r.Error, 500)
	e.Picked = fmt.Sprintf("retry %d of %d", n+1, maxRetryRounds)
	return []Entry{e}
}

// retryLanes walks stuck dispatch lanes up the same ladder; the counters live in afk.json.
func (s *Service) retryLanes(ctx context.Context) []Entry {
	if s.d.Lanes == nil {
		return nil
	}
	now := s.nowF()
	stuck := s.d.Lanes.Stuck()
	type due struct {
		l StuckLane
		n int
	}
	var run []due
	_, _ = s.update(func(st *state) error {
		keep := map[string]laneRetry{}
		for _, l := range stuck {
			k := l.Dispatch + "|" + l.Lane
			c, have := st.Lanes[k]
			if !have || c.Why != l.Why {
				keep[k] = laneRetry{Why: l.Why, N: 0, At: now + float64(RetryDelays[0])}
				continue
			}
			if c.N >= maxRetryRounds {
				keep[k] = c
				continue
			}
			if c.At > now {
				keep[k] = c
				continue
			}
			c.N++
			if c.N < maxRetryRounds {
				c.At = now + float64(RetryDelays[c.N])
			}
			keep[k] = c
			run = append(run, due{l, c.N})
		}
		st.Lanes = keep
		return nil
	})
	var rows []Entry
	for _, d := range run {
		if err := s.d.Lanes.Retry(d.l.Dispatch, d.l.Lane); err != nil {
			log.Printf("away: lane retry %s %s: %v", d.l.Dispatch, d.l.Lane, err)
			continue
		}
		e := Entry{At: now, Kind: "retry", Sid: d.l.Dispatch, Command: fmt.Sprintf("dispatch lane #%d", d.l.Issue),
			Question: cut(d.l.Why, 500), Picked: fmt.Sprintf("retry %d of %d", d.n, maxRetryRounds)}
		if d.l.Repo != "" {
			repo := d.l.Repo
			e.Repo = &repo
		}
		rows = append(rows, e)
	}
	return rows
}
