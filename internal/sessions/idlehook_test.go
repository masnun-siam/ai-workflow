package sessions

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

// settingsArg returns the --settings value of argv, or "" when there is none.
func settingsArg(argv []string) string {
	if i := slices.Index(argv, "--settings"); i >= 0 && i+1 < len(argv) {
		return argv[i+1]
	}
	return ""
}

func TestIdleHookSettingsJSON(t *testing.T) {
	e := newEnv(t)
	var got struct {
		Hooks map[string][]struct {
			Hooks []struct {
				Type, Command string
				Timeout       int
			}
		}
	}
	mustNoErr(t, json.Unmarshal([]byte(e.m.idleHookSettings()), &got))
	stop := got.Hooks["Stop"]
	if len(got.Hooks) != 1 || len(stop) != 1 || len(stop[0].Hooks) != 1 {
		t.Fatalf("%+v", got)
	}
	h := stop[0].Hooks[0]
	if h.Type != "command" || h.Timeout != 10 || h.Command != shellQuote(filepath.Join(e.fb, "setu"))+" hook idle" {
		t.Fatalf("%+v", h)
	}
}

func TestIdleHookStartArgv(t *testing.T) {
	ctx := context.Background()
	blubird := Prompt{Step: "implement-issue", Display: "/blubird:implement-issue 1", Text: "/blubird:implement-issue 1"}
	setuStep := Prompt{Step: "pr-grind", Display: "/pr-grind 5", Text: "SETU pr-grind"}
	for _, tc := range []struct {
		name   string
		guard  bool
		spec   Spec
		hooked bool
	}{
		{"ui blubird run", true, Spec{Prompt: blubird, Gate: true}, true},
		{"lane", true, Spec{Prompt: blubird, Gate: true, Kind: "lane"}, true},
		{"grind", true, Spec{Prompt: setuStep, Gate: true, Kind: "grind"}, false},
		{"panel-root", true, Spec{Prompt: blubird, Gate: true, Kind: "panel-root"}, false},
		{"lens", true, Spec{Prompt: blubird, Kind: "lens"}, false},
		{"coordinator", true, Spec{Prompt: blubird, Gate: true, Kind: "coordinator"}, false},
		{"ui setu-source step", true, Spec{Prompt: setuStep, Gate: true}, false},
		{"custom prompt", true, Spec{Prompt: Prompt{Display: "hi", Text: "hi"}}, false},
		{"guard off ui run", false, Spec{Prompt: blubird, Gate: true}, false},
		{"guard off lane", false, Spec{Prompt: blubird, Gate: true, Kind: "lane"}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e := newEnv(t)
			e.settings.idleGuard = tc.guard
			e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
			e.claudeRule("--print", e.file("ok.jsonl", okStream("s1", 0, 1, 1)), 0)
			tc.spec.Cwd = "acme/app"
			rec, err := e.m.Launch(ctx, tc.spec)
			mustNoErr(t, err)
			e.status(rec.ID, StDone)
			e.settled(rec.ID)
			start := e.lastClaude().Args
			mustNoErr(t, e.m.Resume(ctx, rec.ID, "again"))
			e.wait(rec.ID, func(r Record) bool { return len(e.claudeCalls()) == 2 && r.Status == StDone })
			resume := e.lastClaude().Args
			for name, argv := range map[string][]string{"start": start, "resume": resume} {
				got := settingsArg(argv)
				if tc.hooked && got != e.m.idleHookSettings() {
					t.Fatalf("%s: no idle hook: %q", name, argv)
				}
				if !tc.hooked && slices.Contains(argv, "--settings") {
					t.Fatalf("%s: unexpected --settings: %q", name, argv)
				}
				if tc.hooked && (argv[5] != "--settings" || argv[len(argv)-1] != map[string]string{"start": tc.spec.Prompt.Text, "resume": "again"}[name]) {
					t.Fatalf("%s: --settings must follow the base args and the prompt stay last: %q", name, argv)
				}
			}
		})
	}
}

func TestIdleHookGuardOffArgvUnchanged(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--print", e.file("ok.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec, err := e.m.Launch(context.Background(), Spec{Prompt: Prompt{Step: "implement-issue", Display: "/blubird:implement-issue 1", Text: "/blubird:implement-issue 1"}, Cwd: "acme/app", Gate: true, Kind: "lane"})
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	want := cat(base, []string{"--append-system-prompt", Headless, "/blubird:implement-issue 1"})
	if got := e.lastClaude().Args; !reflect.DeepEqual(got, want) {
		t.Fatalf("argv\n got %q\nwant %q", got, want)
	}
}

func TestIdleHookTurnedOnAddsAtResume(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.claudeRule("--resume", e.file("r.jsonl", okStream("s1", 0, 1, 1)), 0)
	e.claudeRule("--print", e.file("ok.jsonl", okStream("s1", 0, 1, 1)), 0)
	rec, err := e.m.StartSession(ctx, e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	if slices.Contains(e.lastClaude().Args, "--settings") {
		t.Fatalf("guard off at start: %q", e.lastClaude().Args)
	}
	e.settings.idleGuard = true
	mustNoErr(t, e.m.Resume(ctx, rec.ID, "again"))
	e.wait(rec.ID, func(r Record) bool { return len(e.claudeCalls()) == 2 && r.Status == StDone })
	if settingsArg(e.lastClaude().Args) != e.m.idleHookSettings() {
		t.Fatalf("resume after turning it on lacks the hook: %q", e.lastClaude().Args)
	}
}

func TestIdleHookBlocksInTranscript(t *testing.T) {
	e := newEnv(t)
	blockOut, _ := json.Marshal(map[string]string{"decision": "block", "reason": idleReason})
	line := obj{"type": "system", "subtype": "hook_response", "hook_name": "Stop", "hook_event": "Stop", "stdout": string(blockOut) + "\n", "exit_code": 0}
	plain := obj{"type": "system", "subtype": "hook_response", "hook_name": "Stop", "hook_event": "Stop", "stdout": "all good", "exit_code": 0}
	e.claudeRule("--print", e.file("h.jsonl", jl(initEv("sh"), line, line, plain, resultEv(0.1, 1, 1, nil))), 0)
	rec, _ := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	r := e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && r.Hooks == 3 })
	e.settled(rec.ID)
	evs, _, _ := e.m.Stream(rec.ID, 0)
	var hooks []TranscriptEvent
	for _, ev := range evs {
		if ev.Kind == "hook" {
			hooks = append(hooks, ev)
		}
	}
	if len(hooks) != 3 {
		t.Fatalf("%+v", hooks)
	}
	for _, h := range hooks[:2] {
		if !*h.Blocked || h.Text == nil || *h.Text != idleReason || h.Event != "Stop" {
			t.Fatalf("%+v", h)
		}
	}
	if *hooks[2].Blocked || *hooks[2].Text != "all good" {
		t.Fatalf("plain hook: %+v", hooks[2])
	}
	if e.m.Public(r).Hooks != 3 {
		t.Fatal("hooks count")
	}
}

// The skill's own guard stays off in the child even when setu attaches its hook.
func TestIdleHookEnvKeepsBlubirdGuardOff(t *testing.T) {
	e := newEnv(t)
	e.settings.idleGuard = true
	out := filepath.Join(e.fb, "env.txt")
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "env > " + out + "; cat " + filepath.Join(e.fb, "ok.jsonl")}})
	e.file("ok.jsonl", okStream("s1", 0.1, 1, 1))
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	b, _ := os.ReadFile(out)
	if !strings.Contains(string(b), "BLUBIRD_IDLE_GUARD=off") {
		t.Fatal("BLUBIRD_IDLE_GUARD=off missing from the child env")
	}
	if settingsArg(e.lastClaude().Args) == "" {
		t.Fatalf("no hook: %q", e.lastClaude().Args)
	}
}

// claude -p reports a Stop hook block as a "Stop hook feedback" user turn (no hook_response line).
func TestIdleHookStopFeedbackInTranscript(t *testing.T) {
	e := newEnv(t)
	feedback := obj{"type": "user", "message": obj{"role": "user", "content": []any{obj{"type": "text", "text": "Stop hook feedback:\n" + idleReason}}}}
	asString := obj{"type": "user", "message": obj{"role": "user", "content": "Stop hook feedback:\n" + idleReason}}
	toolResult := obj{"type": "user", "message": obj{"role": "user", "content": []any{obj{"type": "tool_result", "tool_use_id": "t1", "content": "Stop hook feedback:\nx"}}}}
	plainUser := obj{"type": "user", "message": obj{"role": "user", "content": []any{obj{"type": "text", "text": "carry on"}}}}
	e.claudeRule("--print", e.file("h.jsonl", jl(initEv("sh"), feedback, toolResult, plainUser, asString, resultEv(0.1, 1, 1, nil))), 0)
	rec, _ := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	r := e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && r.Hooks == 2 })
	e.settled(rec.ID)
	evs, _, _ := e.m.Stream(rec.ID, 0)
	var hooks []TranscriptEvent
	for _, ev := range evs {
		if ev.Kind == "hook" {
			hooks = append(hooks, ev)
		}
	}
	if len(hooks) != 2 {
		t.Fatalf("%+v", hooks)
	}
	for _, h := range hooks {
		if !*h.Blocked || *h.Text != idleReason || h.Event != "Stop" || h.Name != "Stop" {
			t.Fatalf("%+v", h)
		}
	}
	if e.m.Public(r).Hooks != 2 {
		t.Fatal("hooks count")
	}
}
