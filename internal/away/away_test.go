package away

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/sessions"
)

// ---- fakes ----

type fakeSessions struct {
	mu       sync.Mutex
	t        *testing.T
	now      func() time.Time
	recs     map[string]*sessions.Record
	seq      int
	alive    map[string]bool
	launched []sessions.Spec
	resumed  map[string]string
	sent     map[string]string
	stopped  []string
	final    map[string]string
	resumeEr error
	launchEr error
	sendEr   map[string]error
	resumeSt map[string]error
	retried  []string
}

func newFake(t *testing.T, now func() time.Time) *fakeSessions {
	return &fakeSessions{t: t, now: now, recs: map[string]*sessions.Record{}, alive: map[string]bool{},
		resumed: map[string]string{}, sent: map[string]string{}, final: map[string]string{},
		sendEr: map[string]error{}, resumeSt: map[string]error{}}
}

func (f *fakeSessions) add(r sessions.Record) {
	f.mu.Lock()
	defer f.mu.Unlock()
	c := r
	f.recs[r.ID] = &c
}

func (f *fakeSessions) List(fl sessions.Filter) []sessions.Record {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []sessions.Record
	for _, r := range f.recs {
		if r.Role == answererRole && !fl.Answerers {
			continue
		}
		out = append(out, *r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID > out[j].ID })
	return out
}
func (f *fakeSessions) Get(id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("no session")
	}
	return *r, nil
}
func (f *fakeSessions) Update(id string, fn func(*sessions.Record) error) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("no session")
	}
	c := *r
	c.Extra = map[string]json.RawMessage{}
	for k, v := range r.Extra {
		c.Extra[k] = v
	}
	if err := fn(&c); err != nil {
		return *r, err
	}
	*r = c
	return c, nil
}
func (f *fakeSessions) Public(r sessions.Record) sessions.Session {
	s := "o/r"
	return sessions.Session{ID: r.ID, Repo: &s}
}
func (f *fakeSessions) Alive(id string) bool { return f.alive[id] }
func (f *fakeSessions) Launch(_ context.Context, s sessions.Spec) (sessions.Record, error) {
	f.mu.Lock()
	f.launched = append(f.launched, s)
	if f.launchEr != nil {
		f.mu.Unlock()
		return sessions.Record{}, f.launchEr
	}
	f.seq++
	id := fmt.Sprintf("20260101T0000000000%02dZ-%08x", f.seq, f.seq)
	r := sessions.Record{ID: id, Status: sessions.StRunning, StartedAt: f.now().UTC().Format("2006-01-02T15:04:05Z"), Role: answererRole,
		Extra: map[string]json.RawMessage{}}
	for k, v := range s.Fields {
		b, _ := json.Marshal(v)
		r.Extra[k] = b
	}
	f.recs[id] = &r
	f.mu.Unlock()
	return r, nil
}
func (f *fakeSessions) Stop(_ context.Context, id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stopped = append(f.stopped, id)
	if r, ok := f.recs[id]; ok {
		r.Status = sessions.StStopped
		return *r, nil
	}
	return sessions.Record{}, nil
}
func (f *fakeSessions) Resume(_ context.Context, id, text string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.resumeEr != nil {
		return f.resumeEr
	}
	f.resumed[id] = text
	f.recs[id].Status = sessions.StRunning
	return nil
}
func (f *fakeSessions) ResumeStopped(_ context.Context, id, _ string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.resumeSt[id]; err != nil {
		return sessions.Record{}, err
	}
	f.retried = append(f.retried, id)
	f.recs[id].Status = sessions.StRunning
	return *f.recs[id], nil
}
func (f *fakeSessions) SendPrompt(_ context.Context, id, text string, limit int) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.sendEr[id]; err != nil {
		return "", err
	}
	f.sent[id] = text
	if f.recs[id].Status.Live() {
		return "queued", nil
	}
	return "sent", nil
}
func (f *fakeSessions) ClaimAnswer(id, rid string) (*sessions.Round, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.recs[id]
	if r == nil || r.Status != sessions.StWaiting || r.PendingQuestion == nil || r.PendingQuestion.ID != rid || r.PendingQuestion.Status != "pending" {
		return nil, false
	}
	c := *r.PendingQuestion
	r.PendingQuestion = nil
	r.Status = sessions.StStarting
	return &c, true
}
func (f *fakeSessions) RestoreRound(id string, rd sessions.Round) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.recs[id]
	rd.Held, rd.Status = true, "pending"
	r.PendingQuestion, r.Status = &rd, sessions.StWaiting
	return nil
}
func (f *fakeSessions) UpdatePending(id, rid string, fn func(*sessions.Round)) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.recs[id]
	if r == nil || r.Status != sessions.StWaiting || r.PendingQuestion == nil || r.PendingQuestion.ID != rid {
		return nil
	}
	c := *r.PendingQuestion
	fn(&c)
	r.PendingQuestion = &c
	return nil
}
func (f *fakeSessions) FinalText(id string) string { return f.final[id] }

type fakeRisk struct {
	status string
	p      float64
	fail   bool
	mu     sync.Mutex
	calls  []string
}

func (f *fakeRisk) Status() string { return f.status }
func (f *fakeRisk) Ask(_ context.Context, point, kind, q, text string, _ map[string]string, _ []string) jev.Answer {
	f.mu.Lock()
	f.calls = append(f.calls, point+"/"+kind+"|"+text)
	f.mu.Unlock()
	if f.fail {
		return jev.Answer{Status: "unreadable"}
	}
	return jev.Answer{Status: "ok", P: f.p}
}

type fakeAgents struct{ err error }

func (f fakeAgents) Agent(string) (string, []string, error) {
	return "body", []string{"Read", "Grep"}, f.err
}

type fakeNotify struct {
	mu    sync.Mutex
	calls []notify.Note
	evs   []string
}

func (f *fakeNotify) Notify(ev string, n notify.Note) {
	f.mu.Lock()
	f.calls, f.evs = append(f.calls, n), append(f.evs, ev)
	f.mu.Unlock()
}

type rig struct {
	t    *testing.T
	svc  *Service
	f    *fakeSessions
	risk *fakeRisk
	nt   *fakeNotify
	now  time.Time
	h    *home.Home
}

func (r *rig) clock() time.Time { return r.now }

func newRig(t *testing.T) *rig {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv("SETU_HOME", dir)
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	r := &rig{t: t, now: time.Unix(1_800_000_000, 0).UTC(), h: h, risk: &fakeRisk{status: "ok", p: 0.1}, nt: &fakeNotify{}}
	r.f = newFake(t, r.clock)
	r.svc = New(Deps{Home: h, Sessions: r.f, Risk: r.risk, Agents: fakeAgents{}, Notify: r.nt, Now: r.clock})
	return r
}

func (r *rig) begin() {
	r.t.Helper()
	if _, err := r.svc.Begin(r.now.Unix() + 86000); err != nil {
		r.t.Fatal(err)
	}
}

func (r *rig) tick() {
	r.svc.Tick(context.Background())
	r.svc.Wait()
}

func rec(id string, st sessions.Status) sessions.Record {
	return sessions.Record{ID: id, Command: "/blubird:implement-issue 5", Repo: "/tmp/x", Status: st, SessionID: "claude-" + id,
		Link: &sessions.Link{Owner: "o", Repo: "r", Issue: 5}}
}

func strp(s string) *string { return &s }

func waiting(id, rid string, qs ...sessions.Question) sessions.Record {
	r := rec(id, sessions.StWaiting)
	r.PendingQuestion = &sessions.Round{ID: rid, Status: "pending", Questions: qs}
	return r
}

func q(question string, rec string, labels ...string) sessions.Question {
	var opts []sessions.Option
	for _, l := range labels {
		opts = append(opts, sessions.Option{Label: l, Description: "d " + l})
	}
	x := sessions.Question{Header: "H", Question: question, Options: opts}
	if rec != "" {
		x.Recommended = strp(rec)
	}
	return x
}

const sid1 = "20260101T000000000001Z-aaaaaaaa"
const sid2 = "20260101T000000000002Z-bbbbbbbb"

func (r *rig) log() []Entry { return r.svc.load().Log }

// ---- tests ----

func TestBeginValidation(t *testing.T) {
	r := newRig(t)
	now := r.now.Unix()
	for _, tc := range []struct {
		name  string
		until int64
		ok    bool
	}{
		{"past", now - 1, false}, {"now", now, false}, {"zero", 0, false},
		{"soon", now + 1, true}, {"edge", now + 86400, true}, {"over", now + 86401, false},
	} {
		_, err := r.svc.Begin(tc.until)
		if (err == nil) != tc.ok {
			t.Errorf("%s: err=%v", tc.name, err)
		}
		if err != nil && errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%s: kind %v", tc.name, errs.KindOf(err))
		}
	}
}

func TestExtendKeepsStartedAndLog(t *testing.T) {
	r := newRig(t)
	r.begin()
	_, _ = r.svc.update(func(st *state) error { st.Log = []Entry{{Kind: "held"}}; return nil })
	started := r.svc.load().Started
	r.now = r.now.Add(10 * time.Second)
	a, err := r.svc.Begin(r.now.Unix() + 7200)
	if err != nil || !a.Active || *a.Started != started || a.Decisions != 1 {
		t.Fatalf("%+v %v", a, err)
	}
	// ended window: a new one resets
	r.now = r.now.Add(25 * time.Hour)
	r.tick()
	if !r.svc.load().Ended {
		t.Fatal("not ended")
	}
	a, _ = r.svc.Begin(r.now.Unix() + 60)
	st := r.svc.load()
	if a.Decisions != 0 || st.Ended || st.Dismissed || *a.Started != float64(r.now.Unix()) {
		t.Fatalf("%+v %+v", a, st)
	}
}

func TestHoldWords(t *testing.T) {
	for _, w := range holdWords {
		t.Run(w, func(t *testing.T) {
			r := newRig(t)
			r.begin()
			r.f.add(waiting(sid1, "r1", q("Go ahead and "+strings.ToUpper(w)+"?", "Yes", "Yes", "No")))
			r.tick()
			got := r.log()
			if len(got) != 1 || got[0].Kind != "held" || got[0].Reason != "an option mentions '"+w+"'" || got[0].Picked != "Held: "+got[0].Reason {
				t.Fatalf("%+v", got)
			}
			if got[0].ID != sid1+":r1" || got[0].Repo == nil || *got[0].Repo != "o/r" {
				t.Fatalf("%+v", got[0])
			}
			if !r.f.recs[sid1].PendingQuestion.Held || len(r.f.launched) != 0 || len(r.risk.calls) != 0 {
				t.Fatal("not held cleanly")
			}
			r.tick() // held rounds are skipped: no second row
			if len(r.log()) != 1 {
				t.Fatalf("%d rows", len(r.log()))
			}
		})
	}
}

func TestHoldWordInOptionDescription(t *testing.T) {
	r := newRig(t)
	r.begin()
	x := q("Which?", "A", "A", "B")
	x.Options[1].Description = "rm -rf the cache"
	r.f.add(waiting(sid1, "r1", x))
	r.tick()
	if got := r.log(); len(got) != 1 || got[0].Reason != "an option mentions 'rm -rf'" {
		t.Fatalf("%+v", got)
	}
}

func TestRecommendedRiskBoundaries(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status string
		p      float64
		fail   bool
		auto   bool
		riskP  bool
	}{
		{"p0.49", "ok", 0.49, false, true, false},
		{"p0.5", "ok", 0.5, false, false, true},
		{"p0.9", "ok", 0.9, false, false, true},
		{"p0", "ok", 0, false, true, false},
		{"unknown on failure", "ok", 0, true, false, false},
		{"jev off", "off", 0, false, true, false},
		{"jev missing", "missing", 0, false, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := newRig(t)
			r.risk.status, r.risk.p, r.risk.fail = tc.status, tc.p, tc.fail
			r.begin()
			r.f.add(waiting(sid1, "r1", q("Which plan?", "Plan A (Recommended)", "Plan A (Recommended)", "Plan B")))
			r.tick()
			if tc.status == "ok" && len(r.risk.calls) != 1 {
				t.Fatalf("jev calls %v", r.risk.calls)
			}
			if tc.status == "ok" {
				// the worker stored the verdict; the next tick acts on it
				r.tick()
			}
			if tc.auto {
				got := r.log()
				if len(got) != 1 || got[0].Kind != "answer" || got[0].By != "recommended" || got[0].Picked != "Plan A" {
					t.Fatalf("%+v", got)
				}
				if !strings.HasPrefix(r.f.resumed[sid1], "Answer to r1: ") || !strings.Contains(r.f.resumed[sid1], "Plan A (Recommended)") {
					t.Fatalf("resume %q", r.f.resumed[sid1])
				}
				if len(r.f.launched) != 0 {
					t.Fatal("answerer launched")
				}
				return
			}
			if len(r.f.launched) != 1 || len(r.f.resumed) != 0 {
				t.Fatalf("launched=%d resumed=%v", len(r.f.launched), r.f.resumed)
			}
			if r.f.recs[sid1].PendingQuestion.Answerer == nil {
				t.Fatal("answerer not recorded on the round")
			}
			// the jev call sees only the question and options
			if !strings.Contains(r.risk.calls[0], "Which plan?") || strings.Contains(r.risk.calls[0], sid1) {
				t.Fatalf("jev text %q", r.risk.calls[0])
			}
		})
	}
}

func TestRiskCheckedOnce(t *testing.T) {
	r := newRig(t)
	r.risk.p = 0.7
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "A", "A", "B")))
	for i := 0; i < 4; i++ {
		r.tick()
	}
	if len(r.risk.calls) != 1 || len(r.f.launched) != 1 {
		t.Fatalf("calls=%d launched=%d", len(r.risk.calls), len(r.f.launched))
	}
}

func TestNoRecommendedGoesToAnswerer(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	if len(r.risk.calls) != 0 || len(r.f.launched) != 1 {
		t.Fatalf("calls=%d launched=%d", len(r.risk.calls), len(r.f.launched))
	}
	sp := r.f.launched[0]
	f := sp.Fields
	if f["role"] != "away-answerer" || f["answers_for"] != sid1 || f["answers_round"] != "r1" || sp.Agent != "away-answerer" ||
		sp.Model != "opus" || sp.Effort != "medium" || strings.Join(sp.AllowedTools, ",") != "Read,Grep" || sp.Cmd != "" && sp.Cmd != r.f.recs[sid1].ClaudeCmd {
		t.Fatalf("spec %+v", sp)
	}
	if !strings.Contains(sp.Prompt.Text, "Its transcript is at "+r.h.Path("sessions", sid1, "stream.jsonl")) ||
		!strings.Contains(sp.Prompt.Text, "AWAY-ANSWER:") || !strings.Contains(sp.Prompt.Text, `"label": "A"`) {
		t.Fatalf("prompt %q", sp.Prompt.Text)
	}
	// answerer sessions stay out of the lists
	for _, x := range r.f.List(sessions.Filter{}) {
		if x.Role == answererRole {
			t.Fatal("answerer listed")
		}
	}
}

func finishAnswerer(r *rig, text string) string {
	for id, x := range r.f.recs {
		if x.Role == answererRole && x.Status == sessions.StRunning {
			x.Status = sessions.StDone
			c := 0.5
			x.Cost = &c
			r.f.final[id] = text
			return id
		}
	}
	r.t.Fatal("no running answerer")
	return ""
}

func TestAnswererAnswers(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B"), sessions.Question{Header: "M", Question: "Which many?", MultiSelect: true,
		Options: []sessions.Option{{Label: "X"}, {Label: "Y"}, {Label: "Z"}}}))
	r.tick()
	id := finishAnswerer(r, "reasons\nAWAY-ANSWER: "+`{"answers":{"0":{"labels":["B"],"why":"fits"},"1":{"labels":["X","Z"],"why":"both"}}}`)
	r.tick()
	got := r.log()
	if len(got) != 1 || got[0].By != "opus" || got[0].Answerer != id || got[0].Cost == nil || *got[0].Cost != 0.5 || got[0].Picked != "B / X, Z" {
		t.Fatalf("%+v", got)
	}
	if got[0].Questions[0].Why != "fits" || strings.Join(got[0].Questions[1].Picked, ",") != "X,Z" {
		t.Fatalf("%+v", got[0].Questions)
	}
	if want := `Answer to r1: {"0":{"labels":["B"]},"1":{"labels":["X","Z"]}}`; r.f.resumed[sid1] != want {
		t.Fatalf("resume %q", r.f.resumed[sid1])
	}
}

func TestAnswererHold(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	finishAnswerer(r, `AWAY-ANSWER: {"hold":"no basis to choose"}`)
	r.tick()
	got := r.log()
	if len(got) != 1 || got[0].Kind != "held" || got[0].Reason != "no basis to choose" || got[0].Answerer == "" {
		t.Fatalf("%+v", got)
	}
	if r.f.recs[sid1].PendingQuestion.Answerer != nil || !r.f.recs[sid1].PendingQuestion.Held {
		t.Fatal("round state")
	}
}

func TestParseReply(t *testing.T) {
	rd := sessions.Round{ID: "r", Questions: []sessions.Question{
		{Question: "one", Options: []sessions.Option{{Label: "A"}, {Label: "B"}}},
		{Question: "many", MultiSelect: true, AllowFreeText: true, Options: []sessions.Option{{Label: "X"}, {Label: "Y"}}},
	}}
	ok := `{"answers":{"0":{"labels":["A"],"why":" r "},"1":{"labels":["X","Y"],"why":"w"}}}`
	for _, tc := range []struct {
		name, text, err string
		hold            string
	}{
		{"ok", "line\nAWAY-ANSWER: " + ok + "\n\n", "", ""},
		{"indented last line", "  AWAY-ANSWER: " + ok, "", ""},
		{"hold", `AWAY-ANSWER: {"hold":"unsafe"}`, "", "unsafe"},
		{"hold cut", `AWAY-ANSWER: {"hold":"` + strings.Repeat("x", 400) + `"}`, "", strings.Repeat("x", 300)},
		{"not last line", "AWAY-ANSWER: " + ok + "\nthanks", "not an AWAY-ANSWER", ""},
		{"empty", "", "not an AWAY-ANSWER", ""},
		{"not json", "AWAY-ANSWER: nope", "not a JSON object", ""},
		{"two keys", `AWAY-ANSWER: {"hold":"x","answers":{}}`, "exactly one key", ""},
		{"unknown key", `AWAY-ANSWER: {"nope":1}`, "exactly one key", ""},
		{"empty hold", `AWAY-ANSWER: {"hold":"  "}`, "non-empty", ""},
		{"free text", `AWAY-ANSWER: {"answers":{"0":{"other":"zzz","why":"w"},"1":{"labels":["X"],"why":"w"}}}`, "free text is not allowed", ""},
		{"extra key", `AWAY-ANSWER: {"answers":{"0":{"labels":["A"],"why":"w","x":1},"1":{"labels":["X"],"why":"w"}}}`, "exactly labels and why", ""},
		{"no why", `AWAY-ANSWER: {"answers":{"0":{"labels":["A"],"why":""},"1":{"labels":["X"],"why":"w"}}}`, "why must be", ""},
		{"missing question", `AWAY-ANSWER: {"answers":{"0":{"labels":["A"],"why":"w"}}}`, "exactly one entry", ""},
		{"unoffered", `AWAY-ANSWER: {"answers":{"0":{"labels":["Q"],"why":"w"},"1":{"labels":["X"],"why":"w"}}}`, "not an option", ""},
		{"two for single", `AWAY-ANSWER: {"answers":{"0":{"labels":["A","B"],"why":"w"},"1":{"labels":["X"],"why":"w"}}}`, "pick exactly one", ""},
		{"duplicate", `AWAY-ANSWER: {"answers":{"0":{"labels":["A"],"why":"w"},"1":{"labels":["X","X"],"why":"w"}}}`, "duplicate", ""},
		{"empty labels", `AWAY-ANSWER: {"answers":{"0":{"labels":[],"why":"w"},"1":{"labels":["X"],"why":"w"}}}`, "non-empty", ""},
		{"labels not list", `AWAY-ANSWER: {"answers":{"0":{"labels":"A","why":"w"},"1":{"labels":["X"],"why":"w"}}}`, "list of strings", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := parseReply(tc.text, rd)
			if tc.err != "" {
				if err == nil || !strings.Contains(err.Error(), tc.err) {
					t.Fatalf("err = %v", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.hold != tc.hold {
				t.Fatalf("hold %q", got.hold)
			}
			if tc.hold == "" && (got.labels[0][0] != "A" || len(got.labels[1]) != 2 || got.whys[0] != "r") {
				t.Fatalf("%+v", got)
			}
		})
	}
	long := strings.Repeat("w", 400)
	got, _ := parseReply(`AWAY-ANSWER: {"answers":{"0":{"labels":["A"],"why":"`+long+`"},"1":{"labels":["X"],"why":"w"}}}`, rd)
	if len(got.whys[0]) != MaxWhy {
		t.Fatalf("why %d", len(got.whys[0]))
	}
}

func TestInvalidReplyCountsAsFailed(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	finishAnswerer(r, "I think A")
	r.tick() // fails, starts the second attempt
	if len(r.f.launched) != 2 {
		t.Fatalf("launched %d", len(r.f.launched))
	}
	finishAnswerer(r, `AWAY-ANSWER: {"answers":{"0":{"labels":["Z"],"why":"w"}}}`)
	r.tick()
	got := r.log()
	if len(got) != 1 || got[0].Kind != "held" || !strings.HasPrefix(got[0].Reason, "answerer failed (invalid reply:") || got[0].Answerer == "" {
		t.Fatalf("%+v", got)
	}
	r.tick()
	r.tick()
	if len(r.f.launched) != 2 || len(r.log()) != 1 {
		t.Fatalf("launched=%d rows=%d", len(r.f.launched), len(r.log()))
	}
}

func TestTwoAttemptRuleStoppedAnswerers(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	for _, x := range r.f.recs {
		if x.Role == answererRole {
			x.Status = sessions.StFailed
		}
	}
	r.tick()
	if len(r.f.launched) != 2 {
		t.Fatalf("launched %d", len(r.f.launched))
	}
	for _, x := range r.f.recs {
		if x.Role == answererRole {
			x.Status = sessions.StFailed
		}
	}
	r.tick()
	if len(r.f.launched) != 2 || len(r.log()) != 1 || !strings.HasPrefix(r.log()[0].Reason, "answerer failed (answerer failed)") {
		t.Fatalf("launched=%d %+v", len(r.f.launched), r.log())
	}
}

func TestAttemptsSurviveRestart(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	for _, x := range r.f.recs {
		if x.Role == answererRole {
			x.Status = sessions.StFailed
		}
	}
	r.tick()
	for _, x := range r.f.recs {
		if x.Role == answererRole {
			x.Status = sessions.StFailed
		}
	}
	r.svc = New(r.svc.d) // a fresh process: attempts come from the answerer records
	r.tick()
	if len(r.f.launched) != 2 || len(r.log()) != 1 {
		t.Fatalf("launched=%d rows=%d", len(r.f.launched), len(r.log()))
	}
}

func TestAnswererTimeout(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	r.now = r.now.Add(600 * time.Second) // exactly 10 minutes: still waiting
	r.tick()
	if len(r.f.launched) != 1 || len(r.f.stopped) != 0 {
		t.Fatalf("launched=%d stopped=%v", len(r.f.launched), r.f.stopped)
	}
	r.now = r.now.Add(2 * time.Second)
	r.tick()
	if len(r.f.stopped) != 1 || len(r.f.launched) != 2 {
		t.Fatalf("launched=%d stopped=%v", len(r.f.launched), r.f.stopped)
	}
}

func TestAnswererLimitedIsStopped(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	for _, x := range r.f.recs {
		if x.Role == answererRole {
			x.Status = sessions.StLimited
		}
	}
	r.tick()
	if len(r.f.stopped) == 0 || len(r.f.launched) != 2 {
		t.Fatalf("launched=%d stopped=%v", len(r.f.launched), r.f.stopped)
	}
}

func TestCostCaps(t *testing.T) {
	cost := func(c float64) *float64 { return &c }
	started := func(r *rig) string { return r.now.Add(time.Minute).UTC().Format("2006-01-02T15:04:05Z") }
	t.Run("window", func(t *testing.T) {
		r := newRig(t)
		r.begin()
		r.now = r.now.Add(time.Minute)
		r.f.add(sessions.Record{ID: sid2, Role: answererRole, Status: sessions.StDone, Cost: cost(10), StartedAt: started(r),
			Extra: map[string]json.RawMessage{"answers_for": json.RawMessage(`"other"`), "answers_round": json.RawMessage(`"zz"`)}})
		r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
		r.tick()
		got := r.log()
		if len(r.f.launched) != 0 || len(got) != 1 || got[0].Reason != "Away window answerer cost $10.00 reached the $10.00 cap" {
			t.Fatalf("%+v", got)
		}
	})
	t.Run("window under cap", func(t *testing.T) {
		r := newRig(t)
		r.begin()
		r.f.add(sessions.Record{ID: sid2, Role: answererRole, Status: sessions.StDone, Cost: cost(9.99), StartedAt: started(r)})
		r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
		r.tick()
		if len(r.f.launched) != 1 {
			t.Fatal("not started")
		}
	})
	t.Run("answerers before the window do not count", func(t *testing.T) {
		r := newRig(t)
		r.begin()
		r.f.add(sessions.Record{ID: sid2, Role: answererRole, Status: sessions.StDone, Cost: cost(50), StartedAt: "2020-01-01T00:00:00Z"})
		r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
		r.tick()
		if len(r.f.launched) != 1 {
			t.Fatal("not started")
		}
	})
	t.Run("round", func(t *testing.T) {
		r := newRig(t)
		r.begin()
		r.f.add(sessions.Record{ID: sid2, Role: answererRole, Status: sessions.StFailed, Cost: cost(2), StartedAt: started(r),
			Extra: map[string]json.RawMessage{"answers_for": json.RawMessage(`"` + sid1 + `"`), "answers_round": json.RawMessage(`"r1"`)}})
		r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
		r.tick()
		got := r.log()
		if len(r.f.launched) != 0 || len(got) != 1 || got[0].Reason != "answerer cost $2.00 for this round reached the $2.00 cap" {
			t.Fatalf("%+v", got)
		}
	})
}

func TestStartFailureRetriesThenHolds(t *testing.T) {
	r := newRig(t)
	r.f.launchEr = errs.Upstream("claude is not logged in")
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	if len(r.log()) != 0 || len(r.f.launched) != 1 {
		t.Fatalf("rows=%v", r.log())
	}
	r.tick()
	got := r.log()
	if len(r.f.launched) != 2 || len(got) != 1 || got[0].Reason != "answerer could not start: claude is not logged in" {
		t.Fatalf("launched=%d %+v", len(r.f.launched), got)
	}
}

func TestAgentRefusedHoldsAtOnce(t *testing.T) {
	r := newRig(t)
	r.svc.d.Agents = fakeAgents{err: errs.Invalid("agent away-answerer is not allowed")}
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	if got := r.log(); len(got) != 1 || got[0].Reason != "agent away-answerer is not allowed" || len(r.f.launched) != 0 {
		t.Fatalf("%+v", got)
	}
}

func TestResumeFailureRestoresRound(t *testing.T) {
	r := newRig(t)
	r.risk.status = "off"
	r.f.resumeEr = errs.Conflict("process is still running", nil)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "A", "A", "B")))
	r.tick()
	got := r.log()
	if len(got) != 1 || got[0].Kind != "held" || !strings.HasPrefix(got[0].Reason, "resume failed:") {
		t.Fatalf("%+v", got)
	}
	x := r.f.recs[sid1]
	if x.Status != sessions.StWaiting || x.PendingQuestion == nil || !x.PendingQuestion.Held {
		t.Fatalf("round not restored: %+v", x)
	}
}

func TestRoundQualification(t *testing.T) {
	for _, tc := range []struct {
		name string
		mut  func(*sessions.Record)
		live bool
	}{
		{"no claude session", func(r *sessions.Record) { r.SessionID = "" }, false},
		{"held session", func(r *sessions.Record) { r.Hold = true }, false},
		{"held round", func(r *sessions.Record) { r.PendingQuestion.Held = true }, false},
		{"alive process", nil, true},
		{"answered round", func(r *sessions.Record) { r.PendingQuestion.Status = "answered" }, false},
		{"running", func(r *sessions.Record) { r.Status = sessions.StRunning }, false},
		{"no questions", func(r *sessions.Record) { r.PendingQuestion.Questions = nil }, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := newRig(t)
			r.begin()
			x := waiting(sid1, "r1", q("Which?", "", "A", "B"))
			if tc.mut != nil {
				tc.mut(&x)
			}
			r.f.add(x)
			r.f.alive[sid1] = tc.live
			r.tick()
			if len(r.f.launched) != 0 || len(r.log()) != 0 {
				t.Fatalf("acted: launched=%d rows=%v", len(r.f.launched), r.log())
			}
		})
	}
}

func TestSweepStopsOrphanedAnswerers(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	r.tick()
	// the human answers: the parent runs again
	r.f.recs[sid1].Status, r.f.recs[sid1].PendingQuestion = sessions.StRunning, nil
	r.tick()
	if len(r.f.stopped) != 1 || len(r.log()) != 0 {
		t.Fatalf("stopped=%v rows=%v", r.f.stopped, r.log())
	}
}

func TestEndNotifiesOnce(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "A", "A", "B")))
	r.risk.status = "off"
	r.f.add(waiting(sid2, "r2", q("Which?", "", "A", "B"))) // goes to an answerer, stays waiting
	r.tick()
	if len(r.log()) != 1 {
		t.Fatalf("%v", r.log())
	}
	a, err := r.svc.End()
	if err != nil {
		t.Fatal(err)
	}
	if a.Active || a.Summary == nil || a.Summary.Held != 1 || len(a.Summary.Log) != 1 {
		t.Fatalf("%+v", a)
	}
	r.tick()
	r.tick()
	r.now = r.now.Add(25 * time.Hour)
	r.tick()
	if len(r.nt.evs) != 1 || r.nt.evs[0] != "afk" || r.nt.calls[0].Text != "1 decision(s) made, 1 waiting on you" ||
		r.nt.calls[0].ID != fmt.Sprintf("afk-%d", r.now.Add(-25*time.Hour).Unix()) {
		t.Fatalf("%v %+v", r.nt.evs, r.nt.calls)
	}
	// the running answerer was stopped and its round freed
	for _, x := range r.f.recs {
		if x.Role == answererRole && x.Status.Live() {
			t.Fatal("answerer left running")
		}
	}
	if r.f.recs[sid2].PendingQuestion.Answerer != nil {
		t.Fatal("answerer not cleared")
	}
	b, err := r.svc.Dismiss()
	if err != nil || b.Summary != nil {
		t.Fatalf("%+v %v", b, err)
	}
}

func TestNaturalEndNotifiesOnce(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.now = r.now.Add(25 * time.Hour)
	r.tick()
	r.tick()
	if len(r.nt.evs) != 1 || r.nt.calls[0].Text != "0 decision(s) made, 0 waiting on you" {
		t.Fatalf("%v", r.nt.calls)
	}
	if r.svc.Active() {
		t.Fatal("active")
	}
}

func TestPublicHeldCount(t *testing.T) {
	r := newRig(t)
	r.begin()
	r.f.add(waiting(sid1, "r1", q("Which?", "", "A", "B")))
	ended := r.now.Add(time.Minute).UTC().Format("2006-01-02T15:04:05Z")
	f1 := rec("20260101T000000000003Z-cccccccc", sessions.StFailed)
	f1.EndedAt = ended
	f1.SessionID = "" // cannot resume
	f2 := rec("20260101T000000000004Z-dddddddd", sessions.StFailed)
	f2.EndedAt = ended
	f2.Extra = map[string]json.RawMessage{"afk_retries": json.RawMessage("4")}
	f3 := rec("20260101T000000000005Z-eeeeeeee", sessions.StFailed) // resumable
	f3.EndedAt = ended
	f4 := rec("20260101T000000000006Z-ffffffff", sessions.StFailed) // before the window
	f4.EndedAt, f4.SessionID = "2020-01-01T00:00:00Z", ""
	for _, x := range []sessions.Record{f1, f2, f3, f4} {
		r.f.add(x)
	}
	if a := r.svc.Public(); a.Held != 3 || !a.Active || a.Summary != nil {
		t.Fatalf("%+v", a)
	}
}

func TestRetryLadder(t *testing.T) {
	r := newRig(t)
	r.begin()
	fid := sid1
	x := rec(fid, sessions.StFailed)
	x.Error = "boom"
	x.EndedAt = r.now.Add(time.Second).UTC().Format("2006-01-02T15:04:05Z")
	r.f.add(x)
	fail := func() {
		r.f.recs[fid].Status = sessions.StFailed
		r.f.recs[fid].EndedAt = r.now.UTC().Format("2006-01-02T15:04:05Z")
	}
	r.now = r.now.Add(time.Second)
	fail()
	for i, delay := range []int64{120, 600, 1800, 3600} {
		r.tick() // schedules
		if len(r.f.retried) != i {
			t.Fatalf("step %d retried early: %v", i, r.f.retried)
		}
		got := r.f.recs[fid]
		if int(extraInt(*got, "afk_retries")) != i {
			t.Fatalf("step %d retries %d", i, extraInt(*got, "afk_retries"))
		}
		r.now = r.now.Add(time.Duration(delay-1) * time.Second)
		r.tick()
		if len(r.f.retried) != i {
			t.Fatalf("step %d retried before delay %d", i, delay)
		}
		r.now = r.now.Add(time.Second)
		r.tick()
		if len(r.f.retried) != i+1 {
			t.Fatalf("step %d not retried after %d s", i, delay)
		}
		fail()
	}
	r.tick()
	r.tick()
	if len(r.f.retried) != 4 {
		t.Fatalf("gave up late: %d", len(r.f.retried))
	}
	rows := r.log()
	if len(rows) != 4 || rows[0].Kind != "retry" || rows[0].Picked != "retry 1 of 4" || rows[3].Picked != "retry 4 of 4" || rows[0].Question != "boom" {
		t.Fatalf("%+v", rows)
	}
}

func TestRetryConflictGivesUp(t *testing.T) {
	r := newRig(t)
	r.begin()
	x := rec(sid1, sessions.StFailed)
	x.EndedAt = r.now.Add(time.Second).UTC().Format("2006-01-02T15:04:05Z")
	r.f.add(x)
	r.f.resumeSt[sid1] = errs.Conflict("newer session owns the issue", nil)
	r.now = r.now.Add(time.Second)
	r.tick()
	r.now = r.now.Add(121 * time.Second)
	r.tick()
	if extraInt(*r.f.recs[sid1], "afk_retries") != 4 || len(r.log()) != 0 {
		t.Fatalf("%d %v", extraInt(*r.f.recs[sid1], "afk_retries"), r.log())
	}
	r.now = r.now.Add(5 * time.Hour)
	r.f.resumeSt[sid1] = nil
	r.tick()
	if len(r.f.retried) != 0 {
		t.Fatal("retried after giving up")
	}
}

func TestRetrySkips(t *testing.T) {
	r := newRig(t)
	r.begin()
	ended := r.now.Add(time.Second).UTC().Format("2006-01-02T15:04:05Z")
	ans := rec(sid1, sessions.StFailed)
	ans.Role, ans.EndedAt = answererRole, ended
	held := rec(sid2, sessions.StFailed)
	held.Hold, held.EndedAt = true, ended
	old := rec("20260101T000000000003Z-cccccccc", sessions.StFailed)
	old.EndedAt = "2020-01-01T00:00:00Z"
	nosid := rec("20260101T000000000004Z-dddddddd", sessions.StFailed)
	nosid.EndedAt, nosid.SessionID = ended, ""
	for _, x := range []sessions.Record{ans, held, old, nosid} {
		r.f.add(x)
	}
	r.now = r.now.Add(time.Second)
	r.tick()
	r.now = r.now.Add(time.Hour)
	r.tick()
	if len(r.f.retried) != 0 {
		t.Fatalf("retried %v", r.f.retried)
	}
	for _, x := range r.f.recs {
		if extraHas(*x, "afk_retry_at") {
			t.Fatalf("%s scheduled", x.ID)
		}
	}
}

func TestRetryCountersResetWhenHealthy(t *testing.T) {
	r := newRig(t)
	r.begin()
	x := rec(sid1, sessions.StDone)
	x.Extra = map[string]json.RawMessage{"afk_retries": json.RawMessage("2"), "afk_retry_at": json.RawMessage("5"), "afk_retry_for": json.RawMessage(`"x"`)}
	r.f.add(x)
	r.tick()
	if extraHas(*r.f.recs[sid1], "afk_retries") || extraHas(*r.f.recs[sid1], "afk_retry_for") {
		t.Fatal("not reset")
	}
}

type fakeLanes struct {
	stuck   []StuckLane
	retried []string
}

func (f *fakeLanes) Stuck() []StuckLane { return f.stuck }
func (f *fakeLanes) Retry(d, l string) error {
	f.retried = append(f.retried, d+"/"+l)
	return nil
}

func TestLaneRetryLadder(t *testing.T) {
	r := newRig(t)
	fl := &fakeLanes{stuck: []StuckLane{{Dispatch: "abc", Lane: "o/r#7", Issue: 7, Repo: "o/r", Why: "CI failed"}}}
	r.svc.d.Lanes = fl
	r.begin()
	r.tick()
	if len(fl.retried) != 0 {
		t.Fatal("early")
	}
	r.now = r.now.Add(120 * time.Second)
	r.tick()
	if len(fl.retried) != 1 {
		t.Fatalf("%v", fl.retried)
	}
	r.tick()
	if len(fl.retried) != 1 {
		t.Fatal("double retry")
	}
	rows := r.log()
	if len(rows) != 1 || rows[0].Command != "dispatch lane #7" || rows[0].Picked != "retry 1 of 4" || rows[0].Question != "CI failed" {
		t.Fatalf("%+v", rows)
	}
	// a new reason starts the ladder over
	fl.stuck[0].Why = "merge conflict"
	r.now = r.now.Add(time.Second)
	r.tick()
	r.now = r.now.Add(119 * time.Second)
	r.tick()
	if len(fl.retried) != 1 {
		t.Fatal("ladder not reset")
	}
	r.now = r.now.Add(time.Second)
	r.tick()
	if len(fl.retried) != 2 {
		t.Fatalf("%v", fl.retried)
	}
	// the lane recovers: counters are cleared
	fl.stuck = nil
	r.tick()
	if len(r.svc.load().Lanes) != 0 {
		t.Fatal("counters kept")
	}
}

// ---- change answers ----

func answeredLog(r *rig) {
	_, _ = r.svc.update(func(st *state) error {
		st.Log = []Entry{{At: 1, Kind: "answer", Sid: sid1, ID: sid1 + ":r1", By: "opus", Questions: []EntryQuestion{
			{Question: "Which?", Options: []sessions.Option{{Label: "A"}, {Label: "B"}}, Picked: []string{"A"}, Why: "w"},
			{Question: "Many?", MultiSelect: true, AllowFreeText: true, Options: []sessions.Option{{Label: "X"}, {Label: "Y"}}, Picked: []string{"X"}},
		}}, {At: 2, Kind: "held", Sid: sid1}}
		return nil
	})
}

func ended(r *rig) {
	r.begin()
	answeredLog(r)
	r.now = r.now.Add(25 * time.Hour)
	r.tick()
}

func labels(l ...string) sessions.Answer { return sessions.Answer{Labels: l} }

func TestChangeAnswers(t *testing.T) {
	r := newRig(t)
	r.f.add(rec(sid1, sessions.StDone))
	ended(r)
	other := "my own"
	res, err := r.svc.Change([]AwayChange{{ID: sid1 + ":r1", Answers: map[string]sessions.Answer{"0": labels("B"), "1": labels("X")}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Sent) != 1 || res.Sent[0] != sid1 || len(res.Errors) != 0 {
		t.Fatalf("%+v", res)
	}
	want := "While I was away, Away mode answered these for me. I am changing them:\n\nQuestion: Which?\nOld answer: A\nNew answer: B\n\nRedo whatever depended on the old answers; keep everything else."
	if r.f.sent[sid1] != want {
		t.Fatalf("%q", r.f.sent[sid1])
	}
	if !r.log()[0].Changed {
		t.Fatal("not marked")
	}
	// double submit
	_, err = r.svc.Change([]AwayChange{{ID: sid1 + ":r1", Answers: map[string]sessions.Answer{"0": labels("A"), "1": labels("Y")}}})
	if errs.KindOf(err) != errs.KConflict {
		t.Fatalf("%v", err)
	}
	_ = other
}

func TestChangeFreeTextAndQueued(t *testing.T) {
	r := newRig(t)
	x := rec(sid1, sessions.StRunning)
	r.f.add(x)
	ended(r)
	o := "my own"
	res, err := r.svc.Change([]AwayChange{{ID: sid1 + ":r1", Answers: map[string]sessions.Answer{"0": labels("A"), "1": {Other: &o}}}})
	if err != nil || len(res.Queued) != 1 || len(res.Sent) != 0 {
		t.Fatalf("%+v %v", res, err)
	}
	if !strings.Contains(r.f.sent[sid1], "Question: Many?\nOld answer: X\nNew answer: \"my own\"") || strings.Contains(r.f.sent[sid1], "Which?") {
		t.Fatalf("%q", r.f.sent[sid1])
	}
}

func TestChangeErrors(t *testing.T) {
	good := map[string]sessions.Answer{"0": labels("B"), "1": labels("X")}
	row := sid1 + ":r1"
	for _, tc := range []struct {
		name string
		ch   []AwayChange
		kind errs.Kind
	}{
		{"empty", nil, errs.KInvalid},
		{"unknown id", []AwayChange{{ID: "nope", Answers: good}}, errs.KInvalid},
		{"held row id", []AwayChange{{ID: "", Answers: good}}, errs.KInvalid},
		{"duplicate id", []AwayChange{{ID: row, Answers: good}, {ID: row, Answers: good}}, errs.KInvalid},
		{"nothing changed", []AwayChange{{ID: row, Answers: map[string]sessions.Answer{"0": labels("A"), "1": labels("X")}}}, errs.KInvalid},
		{"bad label", []AwayChange{{ID: row, Answers: map[string]sessions.Answer{"0": labels("Z"), "1": labels("X")}}}, errs.KInvalid},
		{"missing answer", []AwayChange{{ID: row, Answers: map[string]sessions.Answer{"0": labels("B")}}}, errs.KInvalid},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := newRig(t)
			r.f.add(rec(sid1, sessions.StDone))
			ended(r)
			_, err := r.svc.Change(tc.ch)
			if errs.KindOf(err) != tc.kind {
				t.Fatalf("%v", err)
			}
			if r.log()[0].Changed || len(r.f.sent) != 0 {
				t.Fatal("state changed on error")
			}
		})
	}
	t.Run("too many", func(t *testing.T) {
		r := newRig(t)
		ended(r)
		var ch []AwayChange
		for i := 0; i < 51; i++ {
			ch = append(ch, AwayChange{ID: fmt.Sprint(i), Answers: good})
		}
		if _, err := r.svc.Change(ch); errs.KindOf(err) != errs.KInvalid {
			t.Fatal(err)
		}
	})
	t.Run("no summary", func(t *testing.T) {
		r := newRig(t)
		r.begin()
		answeredLog(r)
		if _, err := r.svc.Change([]AwayChange{{ID: row, Answers: good}}); errs.KindOf(err) != errs.KConflict {
			t.Fatalf("active window: %v", err)
		}
	})
	t.Run("dismissed", func(t *testing.T) {
		r := newRig(t)
		ended(r)
		_, _ = r.svc.Dismiss()
		if _, err := r.svc.Change([]AwayChange{{ID: row, Answers: good}}); errs.KindOf(err) != errs.KConflict {
			t.Fatal(err)
		}
	})
}

func TestChangeRevertsOnRefusal(t *testing.T) {
	for _, tc := range []struct {
		name string
		mut  func(*rig)
		want string
	}{
		{"missing session", func(r *rig) { delete(r.f.recs, sid1) }, "Session not found"},
		{"queued prompt", func(r *rig) { r.f.recs[sid1].QueuedPrompt = "x" }, "It already has a queued prompt"},
		{"pending question", func(r *rig) { r.f.recs[sid1].Status = sessions.StWaiting }, "Answer its pending question first"},
		{"send refused", func(r *rig) { r.f.sendEr[sid1] = errs.Conflict("session abc is already live for this issue", nil) }, "already live"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := newRig(t)
			r.f.add(rec(sid1, sessions.StDone))
			ended(r)
			tc.mut(r)
			res, err := r.svc.Change([]AwayChange{{ID: sid1 + ":r1", Answers: map[string]sessions.Answer{"0": labels("B"), "1": labels("X")}}})
			if err != nil {
				t.Fatal(err)
			}
			if len(res.Errors) != 1 || res.Errors[0].Sid != sid1 || res.Errors[0].IDs[0] != sid1+":r1" || !strings.Contains(res.Errors[0].Error, tc.want) {
				t.Fatalf("%+v", res)
			}
			if r.log()[0].Changed {
				t.Fatal("not reverted")
			}
		})
	}
}

func TestChangeGroupsBySession(t *testing.T) {
	r := newRig(t)
	r.f.add(rec(sid1, sessions.StDone))
	r.begin()
	mk := func(id string) Entry {
		return Entry{Kind: "answer", Sid: sid1, ID: sid1 + ":" + id, Questions: []EntryQuestion{
			{Question: "Q" + id, Options: []sessions.Option{{Label: "A"}, {Label: "B"}}, Picked: []string{"A"}}}}
	}
	_, _ = r.svc.update(func(st *state) error { st.Log = []Entry{mk("r1"), mk("r2")}; return nil })
	r.now = r.now.Add(25 * time.Hour)
	r.tick()
	b := map[string]sessions.Answer{"0": labels("B")}
	res, err := r.svc.Change([]AwayChange{{ID: sid1 + ":r1", Answers: b}, {ID: sid1 + ":r2", Answers: b}})
	if err != nil || len(res.Sent) != 1 {
		t.Fatalf("%+v %v", res, err)
	}
	if strings.Count(r.f.sent[sid1], "Question:") != 2 {
		t.Fatalf("%q", r.f.sent[sid1])
	}
}

// ---- persistence, routes, misc ----

func TestMigratedAfkJSON(t *testing.T) {
	r := newRig(t)
	old := `{"started": 1799990000.5, "until": 1799993600, "ended": true, "held_at_end": 2, "dismissed": false,
	  "log": [{"at": 1799990100, "kind": "answer", "sid": "` + sid1 + `", "link": {"owner":"o","repo":"r","issue":3}, "repo": "o/r",
	    "command": "/x", "question": "Q", "picked": "A", "id": "` + sid1 + `:r1", "risk": 0.7, "by": "opus", "answerer": "a1", "cost": 0.4, "changed": false,
	    "questions": [{"header":"H","question":"Q","multiSelect":false,"allowFreeText":false,"options":[{"label":"A","description":"d"}],"picked":["A"],"why":"w"}]}]}`
	if err := os.WriteFile(r.h.Path("afk.json"), []byte(old), 0o644); err != nil {
		t.Fatal(err)
	}
	a := r.svc.Public()
	if a.Active || a.Summary == nil || a.Summary.Held != 2 || a.Decisions != 1 || a.Summary.Log[0].Risk == nil || *a.Summary.Log[0].Risk != 0.7 || *a.Started != 1799990000.5 {
		t.Fatalf("%+v", a)
	}
	if _, err := r.svc.Dismiss(); err != nil {
		t.Fatal(err)
	}
	var back map[string]any
	b, _ := os.ReadFile(r.h.Path("afk.json"))
	if err := json.Unmarshal(b, &back); err != nil || back["dismissed"] != true || back["held_at_end"] != float64(2) {
		t.Fatalf("%s %v", b, err)
	}
}

func TestPublicIdle(t *testing.T) {
	r := newRig(t)
	a := r.svc.Public()
	b, _ := json.Marshal(a)
	if a.Active || a.Until != nil || a.Started != nil || !bytes.Contains(b, []byte(`"summary":null`)) || !bytes.Contains(b, []byte(`"until":null`)) {
		t.Fatalf("%s", b)
	}
	r.svc.Tick(context.Background()) // never started: nothing happens
}

func TestRoutes(t *testing.T) {
	r := newRig(t)
	mux := http.NewServeMux()
	for _, rt := range Routes(RouteDeps{Service: r.svc}) {
		mux.Handle(rt.Pattern, rt.Handler)
	}
	do := func(path, body string) (int, map[string]any) {
		req := httptest.NewRequest("POST", path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		req.ContentLength = int64(len(body))
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		var m map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &m)
		return w.Code, m
	}
	if c, m := do("/api/away", fmt.Sprintf(`{"until":%d}`, r.now.Unix()-5)); c != 400 || m["error"] == nil {
		t.Fatalf("%d %v", c, m)
	}
	if c, _ := do("/api/away", `{}`); c != 400 {
		t.Fatalf("%d", c)
	}
	c, m := do("/api/away", fmt.Sprintf(`{"until":%d}`, r.now.Unix()+600))
	if c != 200 || m["active"] != true {
		t.Fatalf("%d %v", c, m)
	}
	if c, m = do("/api/away/stop", `{}`); c != 200 || m["active"] != false || m["summary"] == nil {
		t.Fatalf("%d %v", c, m)
	}
	if c, m = do("/api/away/change", `{"changes":[]}`); c != 400 {
		t.Fatalf("%d %v", c, m)
	}
	if c, m = do("/api/away/dismiss", ``); c != 200 || m["summary"] != nil {
		t.Fatalf("%d %v", c, m)
	}
	if c, _ = do("/api/away/change", `{"changes":[{"id":"x","answers":{}}]}`); c != 409 {
		t.Fatalf("dismissed change: %d", c)
	}
}

func TestStartReturns(t *testing.T) {
	r := newRig(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r.svc.Start(ctx) // the loop only runs at 5 s: Start must return at once
}
