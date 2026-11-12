package away

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/masnun-siam/setu/internal/sessions"
)

type riskInfo struct {
	P       *float64 `json:"p"`
	Unknown bool     `json:"unknown,omitempty"`
}

func (r riskInfo) risky() bool { return r.Unknown || (r.P != nil && *r.P >= RiskP) }

func parseRisk(raw json.RawMessage) (riskInfo, bool) {
	if len(raw) == 0 || string(raw) == "null" {
		return riskInfo{}, false
	}
	var r riskInfo
	if json.Unmarshal(raw, &r) != nil {
		return riskInfo{Unknown: true}, true
	}
	return r, true
}

func roundKey(sid, rid string) string { return sid + ":" + rid }

func (s *Service) rs(key string) *roundState {
	s.mu.Lock()
	defer s.mu.Unlock()
	r := s.rounds[key]
	if r == nil {
		r = &roundState{}
		s.rounds[key] = r
	}
	return r
}

// holdWord returns the first hold word any question or option mentions.
func holdWord(qs []sessions.Question) string {
	var b strings.Builder
	for _, q := range qs {
		b.WriteString(q.Header + "\n" + q.Question + "\n")
		for _, o := range q.Options {
			b.WriteString(o.Label + "\n" + o.Description + "\n")
		}
	}
	text := strings.ToLower(b.String())
	for _, w := range holdWords {
		if strings.Contains(text, w) {
			return w
		}
	}
	return ""
}

func allRecommended(qs []sessions.Question) bool {
	for _, q := range qs {
		if q.Recommended == nil || *q.Recommended == "" {
			return false
		}
	}
	return len(qs) > 0
}

func (s *Service) repoOf(r sessions.Record) *string {
	return s.d.Sessions.Public(r).Repo
}

func (s *Service) base(kind string, r sessions.Record, rd *sessions.Round) Entry {
	e := Entry{At: s.nowF(), Kind: kind, Sid: r.ID, Link: r.Link, Repo: s.repoOf(r), Command: cut(r.Command, 200)}
	if rd != nil {
		e.ID = roundKey(r.ID, rd.ID)
		var qs []string
		for _, q := range rd.Questions {
			t := q.Question
			if t == "" {
				t = q.Header
			}
			qs = append(qs, t)
		}
		e.Question = cut(strings.Join(qs, " / "), 500)
	}
	return e
}

func (s *Service) heldRow(r sessions.Record, rd sessions.Round, reason string) Entry {
	_ = s.d.Sessions.UpdatePending(r.ID, rd.ID, func(x *sessions.Round) { x.Held, x.Answerer = true, nil })
	e := s.base("held", r, &rd)
	e.Picked = cut("Held: "+reason, 500)
	e.Reason = cut(reason, 300)
	return e
}

// round decides what one session's pending round gets (W§3.2).
func (s *Service) round(ctx context.Context, st state, r sessions.Record, answerers []sessions.Record) []Entry {
	rd := r.PendingQuestion
	if r.Status != sessions.StWaiting || rd == nil || rd.Status != "pending" || len(rd.Questions) == 0 ||
		r.Hold || rd.Held || r.SessionID == "" || s.d.Sessions.Alive(r.ID) {
		return nil
	}
	rnd := *rd
	if w := holdWord(rnd.Questions); w != "" {
		return []Entry{s.heldRow(r, rnd, "an option mentions '"+w+"'")}
	}
	var risk riskInfo
	haveRisk := false
	if allRecommended(rnd.Questions) {
		risk, haveRisk = parseRisk(rnd.Risk)
		if !haveRisk {
			if s.d.Risk == nil || s.d.Risk.Status() != "ok" {
				risk, haveRisk = riskInfo{}, true
				raw, _ := json.Marshal(risk)
				_ = s.d.Sessions.UpdatePending(r.ID, rnd.ID, func(x *sessions.Round) { x.Risk = raw })
			} else {
				s.queueRisk(r.ID, rnd)
				return nil
			}
		}
		if !risk.risky() {
			labels := make([][]string, len(rnd.Questions))
			whys := make([]string, len(rnd.Questions))
			for i, q := range rnd.Questions {
				labels[i] = []string{*q.Recommended}
				whys[i] = "marked (Recommended)"
			}
			return s.deliver(ctx, r, rnd, labels, whys, "recommended", nil)
		}
	}
	var rp *float64
	if haveRisk && risk.P != nil {
		rp = risk.P
	}
	return s.opus(ctx, st, r, rnd, rp, answerers)
}

// deliver answers the round with labels (claim, then resume) and returns its log row.
func (s *Service) deliver(ctx context.Context, r sessions.Record, rd sessions.Round, labels [][]string, whys []string, by string, fn func(*Entry)) []Entry {
	answers := map[string]sessions.Answer{}
	for i, l := range labels {
		answers[fmt.Sprint(i)] = sessions.Answer{Labels: l}
	}
	text, err := sessions.AnswerText(rd, answers)
	if err != nil {
		return []Entry{s.heldRow(r, rd, "invalid answer: "+err.Error())}
	}
	claimed, ok := s.d.Sessions.ClaimAnswer(r.ID, rd.ID)
	if !ok {
		return nil
	}
	if err := s.d.Sessions.Resume(ctx, r.ID, text); err != nil {
		_ = s.d.Sessions.RestoreRound(r.ID, *claimed)
		e := s.base("held", r, &rd)
		e.Reason = cut("resume failed: "+err.Error(), 300)
		e.Picked = cut("Held: "+e.Reason, 500)
		return []Entry{e}
	}
	e := s.base("answer", r, &rd)
	e.By = by
	var picked []string
	for i, q := range rd.Questions {
		eq := EntryQuestion{Header: q.Header, Question: q.Question, MultiSelect: q.MultiSelect,
			AllowFreeText: q.AllowFreeText, Options: q.Options, Picked: labels[i], Why: whys[i]}
		e.Questions = append(e.Questions, eq)
		var ls []string
		for _, l := range labels[i] {
			ls = append(ls, strings.TrimSpace(strings.TrimSuffix(l, "(Recommended)")))
		}
		picked = append(picked, strings.Join(ls, ", "))
	}
	e.Picked = cut(strings.Join(picked, " / "), 500)
	if fn != nil {
		fn(&e)
	}
	return []Entry{e}
}

func (s *Service) queueRisk(sid string, rd sessions.Round) {
	key := roundKey(sid, rd.ID)
	s.mu.Lock()
	if s.flight[key] {
		s.mu.Unlock()
		return
	}
	s.flight[key] = true
	ctx := s.ctx
	s.mu.Unlock()
	var b strings.Builder
	for _, q := range rd.Questions {
		b.WriteString(q.Question + "\n")
		for _, o := range q.Options {
			b.WriteString(o.Label + ": " + o.Description + "\n")
		}
	}
	text := b.String()
	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		s.sem <- struct{}{}
		defer func() { <-s.sem }()
		info := riskInfo{Unknown: true}
		func() {
			defer func() { _ = recover() }()
			a := s.d.Risk.Ask(ctx, "risk", "noul", RiskQuestion, text, nil, nil)
			if a.Status == "ok" {
				p := a.P
				info = riskInfo{P: &p}
			}
		}()
		raw, _ := json.Marshal(info)
		_ = s.d.Sessions.UpdatePending(sid, rd.ID, func(x *sessions.Round) { x.Risk = raw })
		s.mu.Lock()
		delete(s.flight, key)
		s.mu.Unlock()
	}()
}
