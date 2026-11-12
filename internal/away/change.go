package away

import (
	"context"
	"fmt"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/sessions"
)

// AwayChange is one changed answer: id is the log row's "<sid>:<round id>".
type AwayChange struct {
	ID      string                     `json:"id"`
	Answers map[string]sessions.Answer `json:"answers"`
}

// ChangeError reports a session that refused the new turn.
type ChangeError struct {
	Sid   string   `json:"sid"`
	IDs   []string `json:"ids"`
	Error string   `json:"error"`
}

// AwayChangeResult is the response of Change.
type AwayChangeResult struct {
	Sent   []string      `json:"sent"`
	Queued []string      `json:"queued"`
	Errors []ChangeError `json:"errors"`
}

func answerWords(a sessions.Answer) string {
	switch {
	case a.Other != nil:
		return fmt.Sprintf("%q", *a.Other)
	case a.None:
		return "None of these"
	}
	return strings.Join(a.Labels, ", ")
}

func sameLabels(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

type changed struct {
	id, sid string
	lines   []string
}

// Change sends the owner's new answers to the sessions Away mode answered for (W§3.4).
func (s *Service) Change(ch []AwayChange) (AwayChangeResult, error) {
	res := AwayChangeResult{Sent: []string{}, Queued: []string{}, Errors: []ChangeError{}}
	if len(ch) < 1 || len(ch) > MaxChanges {
		return res, errs.Invalid("changes must list 1 to %d answers", MaxChanges)
	}
	var plan []changed
	_, err := s.update(func(st *state) error {
		if !st.summaryVisible() {
			return errs.Conflict("there is no Away summary to change", nil)
		}
		rows := map[string]int{}
		for i, e := range st.Log {
			if e.Kind == "answer" && e.ID != "" {
				rows[e.ID] = i
			}
		}
		seen := map[string]bool{}
		plan = nil
		var idx []int
		for _, c := range ch {
			if c.ID == "" || seen[c.ID] {
				return errs.Invalid("each change needs its own id")
			}
			seen[c.ID] = true
			i, ok := rows[c.ID]
			if !ok {
				return errs.Invalid("%s is not an answered round", c.ID)
			}
			e := st.Log[i]
			if e.Changed {
				return errs.Conflict(c.ID+" was already changed", map[string]any{"id": c.ID})
			}
			rd := sessions.Round{ID: strings.TrimPrefix(c.ID, e.Sid+":")}
			for _, q := range e.Questions {
				rd.Questions = append(rd.Questions, sessions.Question{Header: q.Header, Question: q.Question,
					MultiSelect: q.MultiSelect, AllowFreeText: q.AllowFreeText, Options: q.Options})
			}
			if _, err := sessions.AnswerText(rd, c.Answers); err != nil {
				return err
			}
			p := changed{id: c.ID, sid: e.Sid}
			for qi, q := range e.Questions {
				a := c.Answers[fmt.Sprint(qi)]
				if a.Other == nil && !a.None && sameLabels(a.Labels, q.Picked) {
					continue
				}
				p.lines = append(p.lines, fmt.Sprintf("Question: %s\nOld answer: %s\nNew answer: %s",
					q.Question, strings.Join(q.Picked, ", "), answerWords(a)))
			}
			if len(p.lines) == 0 {
				return errs.Invalid("%s: nothing changed", c.ID)
			}
			plan = append(plan, p)
			idx = append(idx, i)
		}
		for _, i := range idx {
			st.Log[i].Changed = true
		}
		return nil
	})
	if err != nil {
		return res, err
	}
	order := []string{}
	groups := map[string][]changed{}
	for _, p := range plan {
		if _, ok := groups[p.sid]; !ok {
			order = append(order, p.sid)
		}
		groups[p.sid] = append(groups[p.sid], p)
	}
	for _, sid := range order {
		g := groups[sid]
		var ids, lines []string
		for _, p := range g {
			ids = append(ids, p.id)
			lines = append(lines, p.lines...)
		}
		text := "While I was away, Away mode answered these for me. I am changing them:\n\n" +
			strings.Join(lines, "\n\n") + "\n\nRedo whatever depended on the old answers; keep everything else."
		state, err := s.send(context.Background(), sid, text)
		if err != nil {
			s.revert(ids)
			res.Errors = append(res.Errors, ChangeError{Sid: sid, IDs: ids, Error: err.Error()})
			continue
		}
		if state == "queued" {
			res.Queued = append(res.Queued, sid)
		} else {
			res.Sent = append(res.Sent, sid)
		}
	}
	s.publish()
	return res, nil
}

func (s *Service) send(ctx context.Context, sid, text string) (string, error) {
	rec, err := s.d.Sessions.Get(sid)
	if err != nil {
		return "", fmt.Errorf("Session not found")
	}
	if rec.QueuedPrompt != "" {
		return "", fmt.Errorf("It already has a queued prompt")
	}
	if rec.Status == sessions.StWaiting {
		return "", fmt.Errorf("Answer its pending question first")
	}
	state, err := s.d.Sessions.SendPrompt(ctx, sid, text, changeTextCap)
	if err != nil {
		if errs.KindOf(err) == errs.KNotFound {
			return "", fmt.Errorf("Session not found")
		}
		return "", err
	}
	return state, nil
}

func (s *Service) revert(ids []string) {
	set := map[string]bool{}
	for _, id := range ids {
		set[id] = true
	}
	_, _ = s.update(func(st *state) error {
		for i := range st.Log {
			if set[st.Log[i].ID] {
				st.Log[i].Changed = false
			}
		}
		return nil
	})
}
