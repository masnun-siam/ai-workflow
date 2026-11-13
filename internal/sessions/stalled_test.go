package sessions

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

const stallReason = "ended without finishing or asking"

// markStalled writes the idle guard's fields the way the hook does: through updateRecord.
func markStalled(t *testing.T, e *tenv, id string) {
	t.Helper()
	_, _, _, err := updateRecord(e.h, id, func(r *Record, _ statKey) error {
		r.Stalled, r.IdleBlocks = stallReason, 2
		return nil
	}, nil)
	mustNoErr(t, err)
}

// rawMeta is meta.json as stored, so a test sees the keys and not the struct's zero values.
func rawMeta(t *testing.T, e *tenv, id string) map[string]json.RawMessage {
	t.Helper()
	b, err := os.ReadFile(metaPath(e.h, id))
	mustNoErr(t, err)
	var m map[string]json.RawMessage
	mustNoErr(t, json.Unmarshal(b, &m))
	return m
}

func assertCleared(t *testing.T, e *tenv, id string) {
	t.Helper()
	m := rawMeta(t, e, id)
	if _, ok := m["stalled"]; ok {
		t.Fatalf("stalled survived the resume: %s", m["stalled"])
	}
	if _, ok := m["idle_blocks"]; ok {
		t.Fatalf("idle_blocks survived the resume: %s", m["idle_blocks"])
	}
}

func (e *tenv) stoppedRecord(t *testing.T, st Status, sid string) Record {
	t.Helper()
	rec, err := e.m.create(Record{Command: "/blubird:implement-issue 5", Step: "implement-issue", Repo: e.repo, CwdPath: e.repo,
		Status: st, ClaudeCmd: "claude", SessionID: sid, Link: &Link{"acme", "app", 5}})
	mustNoErr(t, err)
	return rec
}

func TestStalledRoundTripsAndPublicJSON(t *testing.T) {
	e := newEnv(t)
	rec := e.stoppedRecord(t, StDone, "s1")
	markStalled(t, e, rec.ID)

	m := rawMeta(t, e, rec.ID)
	if string(m["stalled"]) != `"`+stallReason+`"` || string(m["idle_blocks"]) != "2" {
		t.Fatalf("meta.json: stalled=%s idle_blocks=%s", m["stalled"], m["idle_blocks"])
	}
	got, err := e.m.Get(rec.ID)
	mustNoErr(t, err)
	if got.Stalled != stallReason || got.IdleBlocks != 2 {
		t.Fatalf("read back: %+v", got)
	}
	// a write of another field keeps both unchanged
	_, err = e.m.Update(rec.ID, func(r *Record) error { r.Note = "x"; return nil })
	mustNoErr(t, err)
	if m2 := rawMeta(t, e, rec.ID); string(m2["stalled"]) != string(m["stalled"]) || string(m2["idle_blocks"]) != "2" {
		t.Fatalf("after update: %s %s", m2["stalled"], m2["idle_blocks"])
	}

	b, err := json.Marshal(e.m.Public(got))
	mustNoErr(t, err)
	var pub map[string]json.RawMessage
	mustNoErr(t, json.Unmarshal(b, &pub))
	if string(pub["stalled"]) != `"`+stallReason+`"` {
		t.Fatalf("public stalled: %s", pub["stalled"])
	}
	if _, ok := pub["idle_blocks"]; ok {
		t.Fatal("idle_blocks must stay internal")
	}
}

func TestStalledAbsentIsNull(t *testing.T) {
	e := newEnv(t)
	rec := e.stoppedRecord(t, StDone, "s1")
	if _, ok := rawMeta(t, e, rec.ID)["stalled"]; ok {
		t.Fatal("a fresh record has no stalled key")
	}
	got, err := e.m.Get(rec.ID)
	mustNoErr(t, err)
	b, err := json.Marshal(e.m.Public(got))
	mustNoErr(t, err)
	if !strings.Contains(string(b), `"stalled":null`) {
		t.Fatalf("old data must read as stalled null: %s", b)
	}
}

func TestStalledClearedBySendPrompt(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec := e.stoppedRecord(t, StDone, "s1")
	markStalled(t, e, rec.ID)
	state, err := e.m.SendPrompt(context.Background(), rec.ID, "keep going", 4000)
	mustNoErr(t, err)
	if state != "sent" {
		t.Fatal(state)
	}
	e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && len(e.claudeCalls()) == 1 })
	e.settled(rec.ID)
	assertCleared(t, e, rec.ID)
}

func TestStalledClearedByAnswer(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec := e.stoppedRecord(t, StWaiting, "s1")
	_, err := e.m.Update(rec.ID, func(r *Record) error {
		r.PendingQuestion = &Round{ID: "q-1", Status: "pending", Questions: []Question{{Header: "H", Question: "Which?",
			Options: []Option{{Label: "A"}, {Label: "B"}}}}}
		return nil
	})
	mustNoErr(t, err)
	markStalled(t, e, rec.ID)
	_, err = e.m.Answer(context.Background(), rec.ID, "q-1", map[string]Answer{"0": {Labels: []string{"A"}}})
	mustNoErr(t, err)
	e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && len(e.claudeCalls()) == 1 })
	e.settled(rec.ID)
	assertCleared(t, e, rec.ID)
}

func TestStalledClearedByResumeStopped(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec := e.stoppedRecord(t, StStopped, "s1")
	markStalled(t, e, rec.ID)
	_, err := e.m.ResumeStopped(context.Background(), rec.ID, "")
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	assertCleared(t, e, rec.ID)
}

func TestStalledClearedByFreshStart(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--print", e.file("f.jsonl", okStream("s1", 0, 1, 1)), 0)
	// limited before claude reported a session: ResumeStopped starts it over through startFresh
	rec := e.stoppedRecord(t, StLimited, "")
	markStalled(t, e, rec.ID)
	_, err := e.m.ResumeStopped(context.Background(), rec.ID, "")
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	if args := e.lastClaude().Args; strings.Contains(strings.Join(args, " "), "--resume") {
		t.Fatalf("expected a fresh start: %q", args)
	}
	assertCleared(t, e, rec.ID)
}

func TestStalledKeptWhenSessionEndsDone(t *testing.T) {
	e := newEnv(t)
	e.slow("0.5")
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(rec.ID, StRunning)
	markStalled(t, e, rec.ID)
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	if got, _ := e.m.Get(rec.ID); got.Stalled != stallReason || got.IdleBlocks != 2 {
		t.Fatalf("the outcome write cleared the stall: %+v", got)
	}
}
