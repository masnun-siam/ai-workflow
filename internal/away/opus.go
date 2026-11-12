package away

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/sessions"
)

// reply is a parsed answerer reply: a hold reason, or labels and reasons per question.
type reply struct {
	hold   string
	labels [][]string
	whys   []string
}

// parseReply reads the last AWAY-ANSWER line (W§3.3). The returned labels are validated against rd
// with the same rules as a human answer.
func parseReply(text string, rd sessions.Round) (reply, error) {
	var last string
	for _, ln := range strings.Split(text, "\n") {
		if t := strings.TrimSpace(ln); t != "" {
			last = t
		}
	}
	const tag = "AWAY-ANSWER:"
	if !strings.HasPrefix(last, tag) {
		return reply{}, fmt.Errorf("the last line is not an AWAY-ANSWER line")
	}
	var top map[string]json.RawMessage
	dec := json.NewDecoder(strings.NewReader(strings.TrimSpace(strings.TrimPrefix(last, tag))))
	if err := dec.Decode(&top); err != nil || top == nil {
		return reply{}, fmt.Errorf("AWAY-ANSWER is not a JSON object")
	}
	if len(top) != 1 {
		return reply{}, fmt.Errorf("AWAY-ANSWER must have exactly one key, answers or hold")
	}
	if raw, ok := top["hold"]; ok {
		var h string
		if json.Unmarshal(raw, &h) != nil || strings.TrimSpace(h) == "" {
			return reply{}, fmt.Errorf("hold must be a non-empty string")
		}
		return reply{hold: cut(strings.TrimSpace(h), 300)}, nil
	}
	raw, ok := top["answers"]
	if !ok {
		return reply{}, fmt.Errorf("AWAY-ANSWER must have exactly one key, answers or hold")
	}
	var ans map[string]json.RawMessage
	if json.Unmarshal(raw, &ans) != nil || ans == nil {
		return reply{}, fmt.Errorf("answers must be an object")
	}
	out := reply{labels: make([][]string, len(rd.Questions)), whys: make([]string, len(rd.Questions))}
	check := map[string]sessions.Answer{}
	for k, v := range ans {
		var fields map[string]json.RawMessage
		if json.Unmarshal(v, &fields) != nil || fields == nil {
			return reply{}, fmt.Errorf("answer %s must be an object", k)
		}
		if _, other := fields["other"]; other {
			return reply{}, fmt.Errorf("answer %s: free text is not allowed", k)
		}
		if _, none := fields["none"]; none || len(fields) != 2 {
			return reply{}, fmt.Errorf("answer %s must have exactly labels and why", k)
		}
		var labels []string
		if lr, ok := fields["labels"]; !ok || json.Unmarshal(lr, &labels) != nil {
			return reply{}, fmt.Errorf("answer %s: labels must be a list of strings", k)
		}
		if labels == nil {
			labels = []string{}
		}
		var why string
		if wr, ok := fields["why"]; !ok || json.Unmarshal(wr, &why) != nil || strings.TrimSpace(why) == "" {
			return reply{}, fmt.Errorf("answer %s: why must be a non-empty string", k)
		}
		check[k] = sessions.Answer{Labels: labels}
	}
	if _, err := sessions.AnswerText(rd, check); err != nil {
		return reply{}, err
	}
	for k, v := range ans {
		var i int
		fmt.Sscan(k, &i)
		var f struct {
			Labels []string `json:"labels"`
			Why    string   `json:"why"`
		}
		_ = json.Unmarshal(v, &f)
		out.labels[i], out.whys[i] = f.Labels, cut(strings.TrimSpace(f.Why), MaxWhy)
	}
	return out, nil
}

// answererPrompt is the prompt of an answerer session (W§3.3).
func answererPrompt(cmd, repo, transcript, checkout string, qs []sessions.Question) string {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", " ")
	_ = enc.Encode(qs)
	return fmt.Sprintf("Answer the question round below for the session that asked it (command: %s, repo: %s). "+
		"Its transcript is at %s and its checkout is at %s; read them, read-only, to decide. "+
		"Pick option labels for every question, each with a one-line reason, or hold the whole round with a reason when you cannot decide safely. "+
		"Questions, with every option:\n%s"+
		"End your final message with one line `AWAY-ANSWER: <json>`, where json is "+
		`{"answers": {"0": {"labels": ["<offered label>"], "why": "<reason>"}, ...}} `+
		"with one entry per question index (one label for a single-select question, one or more for a multi-select one, only labels the question offers, no free text), "+
		`or {"hold": "<reason>"}.`, cmd, repo, transcript, checkout, buf.String())
}

// answererStats reports the cost of the window's answerers and of one round's, and how many
// answerers the round has had.
func (s *Service) answererStats(st state, answerers []sessions.Record, sid, rid string) (window, round float64, attempts int) {
	for _, a := range answerers {
		if t, ok := parseISO(a.StartedAt); ok && float64(t.Unix()) >= st.Started-1 && a.Cost != nil {
			window += *a.Cost
		}
		if extraString(a, "answers_for") == sid && extraString(a, "answers_round") == rid {
			attempts++
			if a.Cost != nil {
				round += *a.Cost
			}
		}
	}
	return
}

func (s *Service) opus(ctx context.Context, st state, r sessions.Record, rd sessions.Round, risk *float64, answerers []sessions.Record) []Entry {
	key := roundKey(r.ID, rd.ID)
	rs := s.rs(key)
	decorate := func(e *Entry) {
		if risk != nil {
			e.Risk = risk
		}
	}
	held := func(reason string) []Entry {
		e := s.heldRow(r, rd, reason)
		decorate(&e)
		if rs.answerer != "" {
			e.Answerer = rs.answerer
			if a, err := s.d.Sessions.Get(rs.answerer); err == nil {
				e.Cost = a.Cost
			}
		}
		return []Entry{e}
	}
	if rd.Answerer != nil && *rd.Answerer != "" {
		return s.judge(ctx, st, r, rd, rs, held, decorate, answerers)
	}
	return s.startAnswerer(ctx, st, r, rd, rs, held, answerers)
}

func (s *Service) startAnswerer(ctx context.Context, st state, r sessions.Record, rd sessions.Round, rs *roundState, held func(string) []Entry, answerers []sessions.Record) []Entry {
	window, round, n := s.answererStats(st, answerers, r.ID, rd.ID)
	if rs.attempts > n {
		n = rs.attempts
	}
	if n >= MaxAttempts {
		switch {
		case rs.err != "":
			return held("answerer could not start: " + rs.err)
		case rs.fail != "":
			return held("answerer failed (" + rs.fail + ")")
		}
		return held("answerer failed")
	}
	if window >= WindowCostCap {
		return held(fmt.Sprintf("Away window answerer cost $%.2f reached the $%.2f cap", window, WindowCostCap))
	}
	if round >= RoundCostCap {
		return held(fmt.Sprintf("answerer cost $%.2f for this round reached the $%.2f cap", round, RoundCostCap))
	}
	if s.d.Agents == nil {
		return held("answerer could not start: no agent source")
	}
	_, tools, err := s.d.Agents.Agent(answererStep)
	if err != nil {
		return held(err.Error())
	}
	rs.attempts = n + 1
	cwd := r.CwdPath
	if cwd == "" {
		cwd = r.Repo
	}
	transcript := s.h.Path("sessions", r.ID, "stream.jsonl")
	prompt := answererPrompt(r.Command, r.Repo, transcript, cwd, rd.Questions)
	rec, err := s.d.Sessions.Launch(ctx, sessions.Spec{
		Prompt:       sessions.Prompt{Step: answererStep, Display: cut("away answer: "+r.Command, 200), Text: prompt},
		Cwd:          cwd,
		Link:         r.Link,
		Cmd:          r.ClaudeCmd,
		Agent:        answererStep,
		AllowedTools: tools,
		Model:        "opus",
		Effort:       "medium",
		Kind:         "away",
		Fields:       map[string]any{"role": answererRole, "answers_for": r.ID, "answers_round": rd.ID},
	})
	if rec.ID != "" {
		rs.answerer = rec.ID
	}
	if err != nil {
		rs.err = err.Error()
		if rs.attempts >= MaxAttempts {
			return held("answerer could not start: " + rs.err)
		}
		return nil
	}
	rs.err = ""
	if err := s.d.Sessions.UpdatePending(r.ID, rd.ID, func(x *sessions.Round) { id := rec.ID; x.Answerer = &id }); err != nil {
		_, _ = s.d.Sessions.Stop(ctx, rec.ID)
	}
	return nil
}

func (s *Service) judge(ctx context.Context, st state, r sessions.Record, rd sessions.Round, rs *roundState, held func(string) []Entry, decorate func(*Entry), answerers []sessions.Record) []Entry {
	id := *rd.Answerer
	rs.answerer = id
	failed := func(reason string) []Entry {
		rs.fail = reason
		_ = s.d.Sessions.UpdatePending(r.ID, rd.ID, func(x *sessions.Round) { x.Answerer = nil })
		_, _, n := s.answererStats(st, answerers, r.ID, rd.ID)
		if rs.attempts > n {
			n = rs.attempts
		}
		if n >= MaxAttempts {
			return held("answerer failed (" + reason + ")")
		}
		rd.Answerer = nil
		return s.startAnswerer(ctx, st, r, rd, rs, held, answerers)
	}
	a, err := s.d.Sessions.Get(id)
	if err != nil {
		return failed("answerer session is missing")
	}
	switch a.Status {
	case sessions.StStarting, sessions.StRunning:
		t, ok := parseISO(a.StartedAt)
		if !ok || s.now().Sub(t) <= AnswerSeconds*time.Second {
			return nil
		}
		_, _ = s.d.Sessions.Stop(ctx, id)
		return failed("timed out after 10 minutes")
	case sessions.StLimited:
		_, _ = s.d.Sessions.Stop(ctx, id)
		return failed("hit a usage limit")
	case sessions.StDone:
	default:
		return failed("answerer " + string(a.Status))
	}
	rp, err := parseReply(s.d.Sessions.FinalText(id), rd)
	if err != nil {
		return failed("invalid reply: " + err.Error())
	}
	if rp.hold != "" {
		return held(rp.hold)
	}
	return s.deliver(ctx, r, rd, rp.labels, rp.whys, "opus", func(e *Entry) {
		decorate(e)
		e.Answerer = id
		e.Cost = a.Cost
	})
}
