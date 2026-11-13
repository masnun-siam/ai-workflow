package sessions

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/server"
)

const continueImplement = "Continue the `implement-issue` flow from where you stopped. Do the remaining steps, then end as the idle guard says."

// postAction POSTs a session action through the real routes.
func postAction(t *testing.T, e *tenv, id, action string) (int, map[string]any) {
	t.Helper()
	srv := server.New(server.Config{Port: 8420}, e.bus, Routes(RouteDeps{Manager: e.m}))
	r := httptest.NewRequest("POST", "/api/sessions/"+id+"/"+action, strings.NewReader(""))
	r.Host = "127.0.0.1:8420"
	w := httptest.NewRecorder()
	srv.Handler().ServeHTTP(w, r)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func TestContinueText(t *testing.T) {
	if got := ContinueText("implement-issue"); got != continueImplement {
		t.Fatalf("%q", got)
	}
}

func TestContinueResumesSameSession(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec := e.stoppedRecord(t, StDone, "s1")
	markStalled(t, e, rec.ID)

	code, out := postAction(t, e, rec.ID, "continue")
	if code != 200 || out["id"] != rec.ID {
		t.Fatalf("%d %v", code, out)
	}
	if v, ok := out["stalled"]; !ok || v != nil {
		t.Fatalf("response stalled must be null: %v", out)
	}
	e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && len(e.claudeCalls()) == 1 })
	e.settled(rec.ID)
	call := e.lastClaude()
	args := strings.Join(call.Args, " ")
	if !strings.Contains(args, "--resume s1") {
		t.Fatalf("not the same claude session: %q", call.Args)
	}
	if !strings.Contains(args, continueImplement) && !strings.Contains(call.Stdin, continueImplement) {
		t.Fatalf("FR-6 message not sent: args=%q stdin=%q", call.Args, call.Stdin)
	}
	assertCleared(t, e, rec.ID)
}

func TestContinueNotStalledConflict(t *testing.T) {
	e := newEnv(t)
	rec := e.stoppedRecord(t, StDone, "s1")
	code, out := postAction(t, e, rec.ID, "continue")
	if code != 409 || out["error"] != "session is not stalled" || out["id"] != rec.ID {
		t.Fatalf("%d %v", code, out)
	}
	if n := len(e.claudeCalls()); n != 0 {
		t.Fatalf("claude ran %d times", n)
	}
}

func TestContinueUnknownID(t *testing.T) {
	e := newEnv(t)
	if code, out := postAction(t, e, "20990101T000000000000Z-deadbeef", "continue"); code != 404 {
		t.Fatalf("%d %v", code, out)
	}
}

func TestContinueLiveSessionForIssueConflict(t *testing.T) {
	e := newEnv(t)
	rec := e.stoppedRecord(t, StDone, "s1")
	markStalled(t, e, rec.ID)
	other := e.stoppedRecord(t, StRunning, "s2")

	code, out := postAction(t, e, rec.ID, "continue")
	if code != 409 || out["id"] != other.ID {
		t.Fatalf("%d %v", code, out)
	}
	if n := len(e.claudeCalls()); n != 0 {
		t.Fatalf("claude ran %d times", n)
	}
	if got, _ := e.m.Get(rec.ID); got.Stalled != stallReason {
		t.Fatalf("a refused continue must keep the stall: %+v", got)
	}
}
