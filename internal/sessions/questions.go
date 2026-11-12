package sessions

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// buildRound validates the AskUserQuestion-style questions and shapes the stored round (S§1.9).
func buildRound(id string, questions any, held bool) (Round, error) {
	if id == "" {
		return Round{}, errs.Invalid("round id must be a non-empty string")
	}
	qs, ok := questions.([]any)
	if !ok || len(qs) == 0 {
		return Round{}, errs.Invalid("questions must be a non-empty list")
	}
	round := Round{ID: id, Status: "pending", AllowFreeText: true, Held: held}
	for _, qv := range qs {
		q, ok := qv.(map[string]any)
		if !ok {
			return Round{}, errs.Invalid("question must be an object")
		}
		multi, free := false, true
		if v, present := q["multiSelect"]; present {
			if multi, ok = v.(bool); !ok {
				return Round{}, errs.Invalid("multiSelect and allowFreeText must be bool")
			}
		}
		if v, present := q["allowFreeText"]; present {
			if free, ok = v.(bool); !ok {
				return Round{}, errs.Invalid("multiSelect and allowFreeText must be bool")
			}
		}
		opts, ok := q["options"].([]any)
		if !ok || len(opts) == 0 {
			return Round{}, errs.Invalid("question needs options")
		}
		out := Question{MultiSelect: multi, AllowFreeText: free}
		out.Header, _ = q["header"].(string)
		out.Question, _ = q["question"].(string)
		seen := map[string]bool{}
		for _, ov := range opts {
			o, _ := ov.(map[string]any)
			label, _ := o["label"].(string)
			if label == "" {
				return Round{}, errs.Invalid("option label must be a non-empty string")
			}
			if seen[label] {
				return Round{}, errs.Invalid("duplicate option label: %q", label)
			}
			seen[label] = true
			opt := Option{Label: label}
			opt.Description, _ = o["description"].(string)
			if p, ok := o["preview"].(string); ok {
				opt.Preview = p
			}
			out.Options = append(out.Options, opt)
			if out.Recommended == nil && strings.HasSuffix(label, "(Recommended)") {
				l := label
				out.Recommended = &l
			}
		}
		round.Questions = append(round.Questions, out)
	}
	return round, nil
}

// signature is what makes two asks the same round: question texts and option labels.
func signature(qs []Question) string {
	var b strings.Builder
	for _, q := range qs {
		b.WriteString(q.Question)
		b.WriteByte(0)
		for _, o := range q.Options {
			b.WriteString(o.Label)
			b.WriteByte(1)
		}
		b.WriteByte(2)
	}
	return b.String()
}

func newRoundID() string {
	var b [4]byte
	_, _ = rand.Read(b[:])
	return "q-" + hex.EncodeToString(b[:])
}

// SetPending records a question round and marks the session waiting, under the session flock.
// It is the on-disk half of `setu ask` (a child process calls it). The same signature while a
// round is waiting returns that round's id; a different one is an errs.Conflict.
func SetPending(h *home.Home, id string, payload json.RawMessage) (string, error) {
	var p map[string]any
	dec := json.NewDecoder(bytes.NewReader(payload))
	if err := dec.Decode(&p); err != nil || p == nil {
		return "", errs.Invalid("payload must be an object with a 'questions' list")
	}
	var rid string
	_, _, _, err := updateRecord(h, id, func(r *Record, _ statKey) error {
		cand, err := buildRound("q-x", p["questions"], false)
		if err != nil {
			return err
		}
		if r.Status == StWaiting && r.PendingQuestion != nil && r.PendingQuestion.Status == "pending" {
			rid = r.PendingQuestion.ID
			if signature(cand.Questions) != signature(r.PendingQuestion.Questions) {
				return errs.Conflict(fmt.Sprintf("a question round (%s) is already waiting for the human; end your turn and wait for its answer instead of asking again", rid), nil)
			}
			return errReuse // identical: reuse the round, write nothing
		}
		cand.ID = newRoundID()
		rid = cand.ID
		r.PendingQuestion = &cand
		r.Status = StWaiting
		return nil
	}, nil)
	if err == errReuse {
		return rid, nil
	}
	return rid, err
}

var errReuse = fmt.Errorf("reuse")

// setPending is the server-side use (guard relay): a prebuilt round, extra fields in one update.
func (m *Manager) setPending(id string, round Round, extra func(*Record)) (Record, error) {
	return m.Update(id, func(r *Record) error {
		r.PendingQuestion = &round
		r.Status = StWaiting
		if extra != nil {
			extra(r)
		}
		return nil
	})
}

const (
	maxFreeText = 4000
	noneLabel   = "None of these"
)

// AnswerText validates answers against the round and returns the text fed back to claude (S§1.9).
func AnswerText(r Round, answers map[string]Answer) (string, error) {
	n := len(r.Questions)
	if len(answers) != n {
		return "", errs.Invalid("answers must be an object with exactly one entry per question index")
	}
	var b strings.Builder
	b.WriteString("Answer to " + r.ID + ": {")
	for i, q := range r.Questions {
		key := strconv.Itoa(i)
		a, ok := answers[key]
		if !ok {
			return "", errs.Invalid("answers must be an object with exactly one entry per question index")
		}
		set := 0
		if a.Labels != nil {
			set++
		}
		if a.Other != nil {
			set++
		}
		if a.None {
			set++
		}
		if set != 1 {
			return "", errs.Invalid("answer %d must be exactly one of labels, other or none", i)
		}
		var val any
		switch {
		case a.Labels != nil:
			if len(a.Labels) == 0 {
				return "", errs.Invalid("answer %d: labels must be a non-empty list", i)
			}
			if !q.MultiSelect && len(a.Labels) != 1 {
				return "", errs.Invalid("answer %d: pick exactly one option", i)
			}
			valid := map[string]bool{}
			for _, o := range q.Options {
				valid[o.Label] = true
			}
			seen := map[string]bool{}
			for _, l := range a.Labels {
				if l == "" || strings.ContainsRune(l, 0) || !valid[l] {
					return "", errs.Invalid("answer %d: %q is not an option", i, l)
				}
				if seen[l] {
					return "", errs.Invalid("answer %d: duplicate label %q", i, l)
				}
				seen[l] = true
			}
			val = map[string]any{"labels": a.Labels}
		case a.Other != nil:
			t := *a.Other
			switch {
			case !q.AllowFreeText:
				return "", errs.Invalid("answer %d: free text is not allowed", i)
			case strings.TrimSpace(t) == "":
				return "", errs.Invalid("answer %d: free text must not be empty", i)
			case strings.ContainsRune(t, 0):
				return "", errs.Invalid("answer %d: free text must not contain NUL", i)
			case utf8.RuneCountInString(t) > maxFreeText:
				return "", errs.Invalid("answer %d: free text is longer than %d characters", i, maxFreeText)
			case !utf8.ValidString(t):
				return "", errs.Invalid("answer %d: free text must be valid UTF-8", i)
			}
			val = map[string]any{"other": t}
		default:
			if !q.MultiSelect {
				return "", errs.Invalid("answer %d: none is only for multi-select questions", i)
			}
			val = map[string]any{"other": noneLabel}
		}
		if i > 0 {
			b.WriteByte(',')
		}
		kb, _ := marshalNoEscape(key)
		vb, _ := marshalNoEscape(val)
		b.Write(kb)
		b.WriteByte(':')
		b.Write(vb)
	}
	b.WriteByte('}')
	return b.String(), nil
}

// marshalNoEscape is json.Marshal without HTML escaping (python ensure_ascii=False).
func marshalNoEscape(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// ClaimAnswer atomically takes the pending round: it needs status waiting and a pending round
// with this id. It sets pending_question=nil and status=starting; false when the claim lost.
func (m *Manager) ClaimAnswer(id, roundID string) (*Round, bool) {
	var claimed *Round
	_, err := m.Update(id, func(r *Record) error {
		q := r.PendingQuestion
		if r.Status != StWaiting || q == nil || q.Status != "pending" || q.ID != roundID {
			return errNoClaim
		}
		c := *q
		claimed = &c
		r.PendingQuestion = nil
		r.Status = StStarting
		r.PID, r.PidStarted = 0, "" // so a stop during preflight cannot kill the old group
		return nil
	})
	if err != nil {
		return nil, false
	}
	return claimed, true
}

var errNoClaim = fmt.Errorf("no claim")

// RestoreRound re-pends a claimed round as held, only while the session is still starting or
// failed with no pending round. It clears the error.
func (m *Manager) RestoreRound(id string, rd Round) error {
	_, err := m.Update(id, func(r *Record) error {
		if (r.Status != StStarting && r.Status != StFailed) || r.PendingQuestion != nil {
			return errNoClaim
		}
		rd.Held = true
		rd.Status = "pending"
		r.PendingQuestion = &rd
		r.Status = StWaiting
		r.Error = ""
		return nil
	})
	if err == errNoClaim {
		return nil
	}
	return err
}

// UpdatePending changes fields of the pending round, only while it is still that waiting round.
func (m *Manager) UpdatePending(id, roundID string, fn func(*Round)) error {
	_, err := m.Update(id, func(r *Record) error {
		if r.Status != StWaiting || r.PendingQuestion == nil || r.PendingQuestion.ID != roundID {
			return errNoClaim
		}
		fn(r.PendingQuestion)
		return nil
	})
	if err == errNoClaim {
		return errs.Conflict("round is no longer pending", nil)
	}
	return err
}
