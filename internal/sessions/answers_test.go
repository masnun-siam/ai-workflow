package sessions

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

const askQ = `{"questions":[{"header":"Pick","question":"Which?","multiSelect":false,"options":[{"label":"A (Recommended)","description":"first"},{"label":"B"}]}]}`

func runAskCLI(t *testing.T, e *tenv, sid string, args ...string) (int, string, string) {
	t.Helper()
	var out, errb bytes.Buffer
	env := cli.Env{Stdin: strings.NewReader(""), Stdout: &out, Stderr: &errb, Home: e.h,
		Getenv: func(k string) string {
			if k == "SETU_SESSION" {
				return sid
			}
			return ""
		}}
	code := cli.Run(context.Background(), env, Commands(), append([]string{"ask"}, args...))
	return code, out.String(), errb.String()
}

func newBareSession(t *testing.T, e *tenv) Record {
	t.Helper()
	rec, err := e.m.create(Record{Command: "/blubird:implement-issue 5", Repo: e.repo, CwdPath: e.repo, Status: StRunning, ClaudeCmd: "claude", SessionID: "sx"})
	mustNoErr(t, err)
	return rec
}

func TestAskCLI(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)

	if code, _, errs := runAskCLI(t, e, "", "--json", askQ); code != 2 || !strings.Contains(errs, "setu ask needs a setu session (SETU_SESSION)") {
		t.Fatalf("no session: %d %q", code, errs)
	}
	if code, _, _ := runAskCLI(t, e, "20990101T000000000000Z-deadbeef", "--json", askQ); code != 2 {
		t.Fatalf("unknown session: %d", code)
	}
	for _, bad := range []string{`not json`, `[1]`, `{"questions":[]}`, `{"questions":[{"question":"q","options":[]}]}`,
		`{"questions":[{"question":"q","options":[{"label":"a"},{"label":"a"}]}]}`,
		`{"questions":[{"question":"q","multiSelect":"yes","options":[{"label":"a"}]}]}`} {
		if code, _, _ := runAskCLI(t, e, rec.ID, "--json", bad); code != 5 {
			t.Fatalf("bad payload %q: exit %d", bad, code)
		}
	}
	code, out, _ := runAskCLI(t, e, rec.ID, "--json", askQ)
	if code != 0 || !strings.HasPrefix(out, "RECORDED q-") || !strings.Contains(out, "End your turn immediately; the answer arrives as your next message: Answer to q-") {
		t.Fatalf("%d %q", code, out)
	}
	got, _ := e.m.Get(rec.ID)
	q := got.PendingQuestion
	if got.Status != StWaiting || q == nil || q.Status != "pending" || !q.AllowFreeText || q.Held || len(q.Questions) != 1 {
		t.Fatalf("%+v", got)
	}
	if qq := q.Questions[0]; qq.Recommended == nil || *qq.Recommended != "A (Recommended)" || !qq.AllowFreeText || qq.Header != "Pick" {
		t.Fatalf("%+v", qq)
	}
	// the same signature is idempotent: same round id, nothing rewritten
	code, out2, _ := runAskCLI(t, e, rec.ID, "--json", askQ)
	if code != 0 || out2 != out {
		t.Fatalf("idempotent: %d %q vs %q", code, out2, out)
	}
	// a different question while one waits: exit 2 with the pinned text
	code, _, errs := runAskCLI(t, e, rec.ID, "--json", `{"questions":[{"question":"other","options":[{"label":"x"}]}]}`)
	if code != 2 || !strings.Contains(errs, "is already waiting for the human; end your turn and wait for its answer instead of asking again") {
		t.Fatalf("%d %q", code, errs)
	}
	// stdin payload works too
	rec2 := newBareSession(t, e)
	var o, eb bytes.Buffer
	c := cli.Run(context.Background(), cli.Env{Stdin: strings.NewReader(askQ), Stdout: &o, Stderr: &eb, Home: e.h,
		Getenv: func(k string) string { return map[string]string{"AIW_UI_SESSION": rec2.ID}[k] }}, Commands(), []string{"ask"})
	if c != 0 {
		t.Fatalf("stdin: %d %s", c, eb.String())
	}
}

// meta.json written by the old engine loads, and fields this package does not model survive writes.
func TestLegacyRecordCompat(t *testing.T) {
	e := newEnv(t)
	id := "20260101T120000123456Z-0a1b2c3d"
	dir := sessionDir(e.h, id)
	os.MkdirAll(dir, 0o755)
	os.WriteFile(filepath.Join(dir, "stream.jsonl"), nil, 0o644)
	legacy := `{
  "id": "` + id + `", "command": "/ai-workflow:implement-issue 12", "repo": "acme/app",
  "link": {"owner": "acme", "repo": "app", "issue": 12}, "session_id": "old-sess", "pid": null, "status": "done",
  "cost": 1.5, "tokens": {"input": 10, "cached": 2, "output": 3}, "started_at": "2026-01-01T12:00:00Z",
  "ended_at": "2026-01-01T12:10:00Z", "pending_question": null, "claude_cmd": "claude", "harness": "claude",
  "tokens_base": 77, "afk_retries": 2, "panel": "p-20260101T120000Z-abcdef", "panel_role": "lens", "panel_lens": "security",
  "resumed_fresh": null, "notified": ["done"], "limit_resets_at": null, "weird": {"a": [1, 2]}
}`
	os.WriteFile(filepath.Join(dir, "meta.json"), []byte(legacy), 0o644)
	r, err := e.m.Get(id)
	mustNoErr(t, err)
	if r.Status != StDone || r.Cost == nil || *r.Cost != 1.5 || r.Link.Issue != 12 || r.PanelLens != "security" {
		t.Fatalf("%+v", r)
	}
	pub := e.m.Public(r)
	if pub.Step == nil || *pub.Step != "implement-issue" || pub.Skill == nil || *pub.Skill != "blubird:implement-issue" {
		t.Fatalf("step inference: %v %v", pub.Step, pub.Skill)
	}
	if pub.Panel == nil || pub.Panel.Role != "lens" || *pub.Panel.Lens != "security" {
		t.Fatalf("%+v", pub.Panel)
	}
	if pub.Repo == nil || *pub.Repo != "acme/app" {
		t.Fatalf("slug: %v", pub.Repo)
	}
	// a write keeps unknown fields
	_, err = e.m.Update(id, func(r *Record) error { r.Note = "touched"; return nil })
	mustNoErr(t, err)
	b, _ := os.ReadFile(filepath.Join(dir, "meta.json"))
	var raw map[string]json.RawMessage
	json.Unmarshal(b, &raw)
	for _, k := range []string{"harness", "tokens_base", "afk_retries", "weird"} {
		if _, ok := raw[k]; !ok {
			t.Errorf("field %q lost on rewrite", k)
		}
	}
	if string(raw["tokens_base"]) != "77" {
		t.Errorf("tokens_base: %s", raw["tokens_base"])
	}
	if !strings.HasSuffix(string(b), "\n") || !strings.Contains(string(b), "\n  \"") {
		t.Errorf("not indent-2 with a trailing newline")
	}
	// listed newest first, with a lazily appearing newer session
	n := newBareSession(t, e)
	list := e.m.List(Filter{})
	if len(list) != 2 || list[0].ID != n.ID {
		t.Fatalf("order: %v", list)
	}
}

func TestWaitingAnswerResumeDone(t *testing.T) {
	e := newEnv(t)
	t.Setenv("SESSIONS_TEST_AS_SETU", "1")
	e.file("ask.jsonl", jl(initEv("sw"), toolEv("Bash", obj{"command": "  setu ask --json '...'"}), resultEv(0.1, 2, 2, nil)))
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--resume", StdoutFile: e.file("after.jsonl", jl(initEv("sw"), resultEv(0.2, 3, 3, nil)))})
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "cat " + filepath.Join(e.fb, "ask.jsonl") + "; " + os.Args[0] + " ask --json '" + askQ + "'"}})
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	r := e.wait(rec.ID, func(r Record) bool { return r.Status == StWaiting && r.EndedAt != "" })
	e.settled(rec.ID)
	rid := r.PendingQuestion.ID
	if e.notes.count("waiting") != 1 {
		t.Fatalf("waiting notified %d times", e.notes.count("waiting"))
	}
	if n := e.notes.items[0].Note; n.Question != "Which?" || n.Recommended != "A (Recommended)" || n.ID != rec.ID {
		t.Fatalf("%+v", n)
	}

	// validation order
	ctx := context.Background()
	one := map[string]Answer{"0": {Labels: []string{"B"}}}
	if _, err := e.m.Answer(ctx, rec.ID, "", one); kind(err) != "invalid" {
		t.Fatalf("empty round id: %v", err)
	}
	if _, err := e.m.Answer(ctx, rec.ID, "q-other", one); kind(err) != "conflict" {
		t.Fatalf("wrong round: %v", err)
	}
	if _, err := e.m.Answer(ctx, rec.ID, rid, map[string]Answer{"0": {Labels: []string{"nope"}}}); kind(err) != "invalid" {
		t.Fatalf("bad label: %v", err)
	}
	if got, _ := e.m.Get(rec.ID); got.Status != StWaiting || got.PendingQuestion == nil {
		t.Fatalf("a rejected answer must not claim the round: %+v", got)
	}

	// two simultaneous answers: exactly one wins
	var wg sync.WaitGroup
	results := make([]error, 2)
	for i := range results {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, results[i] = e.m.Answer(ctx, rec.ID, rid, one)
		}(i)
	}
	wg.Wait()
	wins := 0
	for _, err := range results {
		if err == nil {
			wins++
		} else if kind(err) != "conflict" {
			t.Fatalf("loser: %v", err)
		}
	}
	if wins != 1 {
		t.Fatalf("answers accepted: %d", wins)
	}
	d := e.wait(rec.ID, func(r Record) bool { return r.Status == StDone })
	if d.PendingQuestion != nil || d.PendingAnswer != "" {
		t.Fatalf("%+v", d)
	}
	want := cat(base, []string{"--append-system-prompt", Headless, "--resume", "sw", `Answer to ` + rid + `: {"0":{"labels":["B"]}}`})
	if got := e.lastClaude().Args; !reflect.DeepEqual(got, want) {
		t.Fatalf("resume argv\n got %q\nwant %q", got, want)
	}
	if d.Cost == nil || *d.Cost < 0.2999 || *d.Cost > 0.3001 || d.Tokens.Input != 5 {
		t.Fatalf("accumulated across the resume: %v %v", *d.Cost, d.Tokens)
	}
	e.settled(rec.ID)
	if e.notes.count("done") != 1 || e.notes.count("waiting") != 1 {
		t.Fatalf("notifications: done %d waiting %d", e.notes.count("done"), e.notes.count("waiting"))
	}
}

func TestAnswerTextMatrix(t *testing.T) {
	multi := Round{ID: "q-1", Questions: []Question{
		{Question: "one", Options: []Option{{Label: "A"}, {Label: "B"}}, AllowFreeText: true},
		{Question: "two", MultiSelect: true, Options: []Option{{Label: "X"}, {Label: "Y"}}, AllowFreeText: false},
	}}
	s := func(v string) *string { return &v }
	long := strings.Repeat("x", 4001)
	for _, tc := range []struct {
		name    string
		a       map[string]Answer
		want    string
		invalid bool
	}{
		{"ok", map[string]Answer{"0": {Labels: []string{"A"}}, "1": {Labels: []string{"X", "Y"}}}, `Answer to q-1: {"0":{"labels":["A"]},"1":{"labels":["X","Y"]}}`, false},
		{"other", map[string]Answer{"0": {Other: s("é <free> & text")}, "1": {None: true}}, `Answer to q-1: {"0":{"other":"é <free> & text"},"1":{"other":"None of these"}}`, false},
		{"missing key", map[string]Answer{"0": {Labels: []string{"A"}}}, "", true},
		{"extra key", map[string]Answer{"0": {Labels: []string{"A"}}, "1": {None: true}, "2": {None: true}}, "", true},
		{"wrong key", map[string]Answer{"0": {Labels: []string{"A"}}, "5": {None: true}}, "", true},
		{"two options on single", map[string]Answer{"0": {Labels: []string{"A", "B"}}, "1": {None: true}}, "", true},
		{"duplicate label", map[string]Answer{"0": {Labels: []string{"A"}}, "1": {Labels: []string{"X", "X"}}}, "", true},
		{"unknown label", map[string]Answer{"0": {Labels: []string{"Z"}}, "1": {None: true}}, "", true},
		{"empty labels", map[string]Answer{"0": {Labels: []string{}}, "1": {None: true}}, "", true},
		{"none on single", map[string]Answer{"0": {None: true}, "1": {None: true}}, "", true},
		{"free text not allowed", map[string]Answer{"0": {Labels: []string{"A"}}, "1": {Other: s("hi")}}, "", true},
		{"empty free text", map[string]Answer{"0": {Other: s("  ")}, "1": {None: true}}, "", true},
		{"nul free text", map[string]Answer{"0": {Other: s("a\x00b")}, "1": {None: true}}, "", true},
		{"too long free text", map[string]Answer{"0": {Other: s(long)}, "1": {None: true}}, "", true},
		{"two kinds", map[string]Answer{"0": {Labels: []string{"A"}, Other: s("x")}, "1": {None: true}}, "", true},
		{"no kind", map[string]Answer{"0": {}, "1": {None: true}}, "", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := AnswerText(multi, tc.a)
			if tc.invalid {
				if kind(err) != "invalid" {
					t.Fatalf("want invalid, got %v / %q", err, got)
				}
				return
			}
			if err != nil || got != tc.want {
				t.Fatalf("got %q err %v\nwant %q", got, err, tc.want)
			}
		})
	}
}

func TestGuardRelayApproveAndDeny(t *testing.T) {
	for _, approve := range []bool{true, false} {
		name := "deny"
		if approve {
			name = "approve"
		}
		t.Run(name, func(t *testing.T) {
			e := newEnv(t)
			claudeMD := filepath.Join(e.repo, "CLAUDE.md")
			os.WriteFile(claudeMD, []byte("# hi\n"), 0o644)
			fx, err := os.ReadFile("testdata/claude_guard_ask.jsonl")
			mustNoErr(t, err)
			e.claudeRule("--resume", e.file("after.jsonl", okStream("sess-guard", 0.01, 1, 1)), 0)
			e.claudeRule("--print", e.file("guard.jsonl", strings.ReplaceAll(string(fx), "@ROOT@", e.repo)), 0)
			rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
			mustNoErr(t, err)
			r := e.wait(rec.ID, func(r Record) bool { return r.Status == StWaiting && r.EndedAt != "" })
			e.settled(rec.ID)
			q := r.PendingQuestion
			if q == nil || q.ID != "guard-toolu_015RguardFixture" || !q.Held || r.GuardEdit == nil || r.GuardEdit.ToolName != "Edit" {
				t.Fatalf("%+v / %+v", q, r.GuardEdit)
			}
			qq := q.Questions[0]
			if qq.Header != "Protected file" || qq.AllowFreeText || qq.MultiSelect || len(qq.Options) != 2 ||
				!strings.Contains(qq.Question, "`"+claudeMD+"`") || !strings.Contains(qq.Question, "```diff\n- # hi\n\n+ # hi\nedited by agent\n\n```") {
				t.Fatalf("question: %q", qq.Question)
			}
			label := "Deny"
			if approve {
				label = "Approve"
			}
			_, err = e.m.Answer(context.Background(), rec.ID, q.ID, map[string]Answer{"0": {Labels: []string{label}}})
			mustNoErr(t, err)
			e.status(rec.ID, StDone)
			e.settled(rec.ID)
			b, _ := os.ReadFile(claudeMD)
			args := e.lastClaude().Args
			last := args[len(args)-1]
			if approve {
				if string(b) != "# hi\nedited by agent\n" || !strings.HasSuffix(last, "\nThe human approved the edit to "+claudeMD+" and the UI applied it. Continue.") {
					t.Fatalf("approve: file %q last %q", b, last)
				}
			} else if string(b) != "# hi\n" || !strings.HasSuffix(last, "\nThe human denied this edit to "+claudeMD+". Leave it unchanged and continue without it.") {
				t.Fatalf("deny: file %q last %q", b, last)
			}
			if got, _ := e.m.Get(rec.ID); got.GuardEdit != nil {
				t.Fatal("guard_edit not cleared")
			}
		})
	}
}

func TestGuardApproveCannotApply(t *testing.T) {
	e := newEnv(t)
	os.WriteFile(filepath.Join(e.repo, "CLAUDE.md"), []byte("# hi\n"), 0o644)
	fx, _ := os.ReadFile("testdata/claude_guard_ask.jsonl")
	e.claudeRule("--resume", e.file("after.jsonl", okStream("sess-guard", 0.01, 1, 1)), 0)
	e.claudeRule("--print", e.file("guard.jsonl", strings.ReplaceAll(string(fx), "@ROOT@", e.repo)), 0)
	rec, _ := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	r := e.wait(rec.ID, func(r Record) bool { return r.Status == StWaiting && r.EndedAt != "" })
	e.settled(rec.ID)
	os.WriteFile(filepath.Join(e.repo, "CLAUDE.md"), []byte("changed meanwhile\n"), 0o644)
	_, err := e.m.Answer(context.Background(), rec.ID, r.PendingQuestion.ID, map[string]Answer{"0": {Labels: []string{"Approve"}}})
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	args := e.lastClaude().Args
	if !strings.Contains(args[len(args)-1], "approved the edit but the UI could not apply it: edit 1: the text to replace is no longer in the file. Say so and continue.") {
		t.Fatalf("%q", args[len(args)-1])
	}
}

func TestMaskSecretsBlock(t *testing.T) {
	e := newEnv(t)
	fx, err := os.ReadFile("testdata/claude_secret_block.jsonl")
	mustNoErr(t, err)
	e.claudeRule("--print", e.file("secret.jsonl", strings.ReplaceAll(string(fx), "@ROOT@", e.repo)), 0)
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	r := e.status(rec.ID, StFailed)
	if !strings.HasPrefix(r.Error, "blocked by mask-secrets: This prompt was not sent because it contains a secret (github_token).") ||
		r.PendingQuestion != nil || r.PendingAnswer != "" || r.Hooks != 1 {
		t.Fatalf("%+v", r)
	}
	e.settled(rec.ID)
	evs, _, err := e.m.Stream(rec.ID, 0)
	mustNoErr(t, err)
	var hook *TranscriptEvent
	for i := range evs {
		if evs[i].Kind == "hook" {
			hook = &evs[i]
		}
	}
	if hook == nil || hook.Name != "mask-secrets" || hook.Event != "UserPromptSubmit" || !*hook.Blocked || !strings.Contains(*hook.Text, "github_token") {
		t.Fatalf("%+v", evs)
	}
}

func TestAskedButNoRoundRecorded(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--print", e.file("a.jsonl", jl(initEv("sa"), toolEv("Bash", obj{"command": "setu ask --json '{}'"}), resultEv(0, 1, 1, nil))), 0)
	rec, _ := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	r := e.status(rec.ID, StFailed)
	if r.Error != "setu ask ran but recorded no question; see stream.jsonl" {
		t.Fatal(r.Error)
	}
}

func TestHookEventsFromStream(t *testing.T) {
	e := newEnv(t)
	stream := jl(initEv("sh"),
		obj{"type": "system", "subtype": "hook_started", "hook_name": "SessionStart:startup", "hook_event": "SessionStart"},
		obj{"type": "system", "subtype": "hook_response", "hook_name": "SessionStart:startup", "hook_event": "SessionStart", "output": "", "exit_code": 0},
		obj{"type": "system", "subtype": "hook_response", "hook_name": "PostToolUse:mask-secrets", "hook_event": "PostToolUse", "output": "masked 1 secret in tool output", "exit_code": 0},
		obj{"type": "system", "subtype": "hook_response", "hook_name": "Stop:idle-guard", "hook_event": "Stop", "stderr": "idle guard: still working", "exit_code": 2},
		resultEv(0.1, 1, 1, nil))
	e.claudeRule("--print", e.file("h.jsonl", stream), 0)
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
	if len(hooks) != 2 || hooks[0].Name != "PostToolUse:mask-secrets" || *hooks[0].Blocked || !*hooks[1].Blocked || hooks[1].Event != "Stop" {
		t.Fatalf("%+v", hooks)
	}
	if e.m.Public(r).Hooks != 2 {
		t.Fatal("hooks count not in the API shape")
	}
}
