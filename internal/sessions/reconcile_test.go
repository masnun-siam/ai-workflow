package sessions

import (
	"context"
	"os"
	"os/exec"
	"syscall"
	"testing"
	"time"
)

// detached starts a script as its own session, appending to the session's stream.jsonl, the way
// a previous server would have left claude running.
func detached(t *testing.T, e *tenv, id, script string) (pid int, started string) {
	t.Helper()
	f, err := os.OpenFile(streamPath(e.h, id), os.O_APPEND|os.O_WRONLY, 0o644)
	mustNoErr(t, err)
	cmd := exec.Command("sh", "-c", script)
	cmd.Stdout = f
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	mustNoErr(t, cmd.Start())
	f.Close()
	go cmd.Wait() // reap, so a finished process is really gone for ps
	t.Cleanup(func() { syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) })
	started, _ = psStart(context.Background(), cmd.Process.Pid)
	return cmd.Process.Pid, started
}

func line(v any) string { return jl(v) }

func TestReconcileReattachesLiveProcess(t *testing.T) {
	e := newEnv(t)
	rec, _ := e.m.create(Record{Command: "/blubird:implement-issue 1", Repo: e.repo, CwdPath: e.repo, Status: StRunning, ClaudeCmd: "claude"})
	script := "printf '%s' '" + line(initEv("sre")) + "'; sleep 0.6; printf '%s' '" + line(resultEv(0.4, 3, 4, nil)) + "'"
	pid, fp := detached(t, e, rec.ID, script)
	if fp == "" {
		t.Fatal("no ps fingerprint")
	}
	e.m.Update(rec.ID, func(r *Record) error { r.PID, r.PidStarted = pid, fp; return nil })

	// a new server comes up
	m2 := New(e.m.d)
	mustNoErr(t, m2.Reconcile(context.Background()))
	if !m2.Alive(rec.ID) {
		t.Fatal("live process not re-attached")
	}
	got := e.wait(rec.ID, func(r Record) bool { return r.Status == StDone })
	if got.SessionID != "sre" || got.Cost == nil || *got.Cost != 0.4 || got.Tokens.Output != 4 {
		t.Fatalf("%+v", got)
	}
}

func TestReconcileDeadAndNeverStarted(t *testing.T) {
	e := newEnv(t)
	mk := func(pid int, fp, stream string) string {
		rec, _ := e.m.create(Record{Command: "c", Repo: e.repo, CwdPath: e.repo, Status: StRunning, ClaudeCmd: "claude", PID: pid, PidStarted: fp})
		os.WriteFile(streamPath(e.h, rec.ID), []byte(stream), 0o644)
		return rec.ID
	}
	ok := mk(999991, "Thu Jan  1 00:00:00 1970", okStream("s", 0.1, 1, 1))
	silent := mk(999992, "Thu Jan  1 00:00:00 1970", jl(initEv("s"), textEv("half way")))
	failedRun := mk(999993, "Thu Jan  1 00:00:00 1970", jl(initEv("s"), resultEv(0, 0, 0, obj{"is_error": true, "errors": []any{"boom"}})))
	never := mk(0, "", "")
	mustNoErr(t, New(e.m.d).Reconcile(context.Background()))

	if r, _ := e.m.Get(ok); r.Status != StDone {
		t.Errorf("finished while down: %+v", r)
	}
	if r, _ := e.m.Get(silent); r.Status != StFailed || r.Error != "claude exited while the UI was down without a successful result; see stderr.log" {
		t.Errorf("silent: %+v", r)
	}
	if r, _ := e.m.Get(failedRun); r.Status != StFailed {
		t.Errorf("error result: %+v", r)
	}
	if r, _ := e.m.Get(never); r.Status != StFailed || r.Error != "session never started (UI exited before spawn)" {
		t.Errorf("never started: %+v", r)
	}
}

func TestReconcileWaitingWatcher(t *testing.T) {
	e := newEnv(t)
	rec, _ := e.m.create(Record{Command: "c", Repo: e.repo, CwdPath: e.repo, Status: StRunning, ClaudeCmd: "claude", SessionID: "sw"})
	pid, fp := detached(t, e, rec.ID, "sleep 1.5")
	e.m.Update(rec.ID, func(r *Record) error {
		r.PID, r.PidStarted, r.Status = pid, fp, StWaiting
		r.PendingQuestion = &Round{ID: "q-1", Status: "pending", AllowFreeText: true, Questions: []Question{{Question: "?", Options: []Option{{Label: "A"}}}}}
		return nil
	})
	m2 := New(e.m.d)
	mustNoErr(t, m2.Reconcile(context.Background()))
	if !m2.Alive(rec.ID) {
		t.Fatal("waiting session's process not held")
	}
	// no second process may be resumed while the first lives
	_, err := m2.Answer(context.Background(), rec.ID, "q-1", map[string]Answer{"0": {Labels: []string{"A"}}})
	if kind(err) != "conflict" {
		t.Fatalf("answer while process alive: %v", err)
	}
	got := e.wait(rec.ID, func(r Record) bool { return r.EndedAt != "" })
	if got.Status != StWaiting || got.PendingQuestion == nil {
		t.Fatalf("watcher changed the round: %+v", got)
	}
	deadline := time.Now().Add(5 * time.Second)
	for m2.Alive(rec.ID) && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if m2.Alive(rec.ID) {
		t.Fatal("watcher did not release the session")
	}
}

func TestStopReattachedProcess(t *testing.T) {
	e := newEnv(t)
	rec, _ := e.m.create(Record{Command: "c", Repo: e.repo, CwdPath: e.repo, Status: StRunning, ClaudeCmd: "claude"})
	pid, fp := detached(t, e, rec.ID, "sleep 60")
	e.m.Update(rec.ID, func(r *Record) error { r.PID, r.PidStarted = pid, fp; return nil })
	m2 := New(e.m.d)
	mustNoErr(t, m2.Reconcile(context.Background()))
	out, err := m2.Stop(context.Background(), rec.ID)
	mustNoErr(t, err)
	if out.Status != StStopped {
		t.Fatalf("%+v", out)
	}
	if exec_ps(itoa(pid)) {
		t.Fatal("process survived stop")
	}
	e.settled(rec.ID)
	if got, _ := e.m.Get(rec.ID); got.Status != StStopped {
		t.Fatalf("follower overwrote stopped: %v", got.Status)
	}
}

func itoa(n int) string { return fmtInt(n) }
