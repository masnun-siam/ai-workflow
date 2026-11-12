package grind

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
	"github.com/masnun-siam/setu/internal/home"
)

const (
	testPR   = "https://github.com/acme/app/pull/7"
	testHead = "aaaa1111"
)

var t0 = time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC)

// world is a scripted GitHub: one PR, its reviews and its checks.
type world struct {
	mu                        sync.Mutex
	State, Head, Author, Base string
	Draft                     bool
	Mergeable, Decision       string
	Reviews, Comments, Issue  string // JSON arrays
	Checks                    string // gh pr checks stdout
	ChecksCode                int
	ChecksErr                 string
	EditFail                  map[string]bool
	Edits                     []string
	ReviewCalls               int
	OnChecks                  func()
	Graphql                   string
}

func newWorld() *world {
	return &world{State: "OPEN", Head: testHead, Author: "alice", Base: "staging", Mergeable: "MERGEABLE",
		Reviews: "[]", Comments: "[]", Issue: "[]", Checks: "[]", EditFail: map[string]bool{}}
}

func (w *world) client() *ghtest.Client {
	fn := func(args []string) execx.Result {
		w.mu.Lock()
		defer w.mu.Unlock()
		ok := func(s string) execx.Result { return execx.Result{Stdout: []byte(s)} }
		j := strings.Join(args, " ")
		switch {
		case strings.HasPrefix(j, "pr view"):
			return ok(fmt.Sprintf(`{"state":%q,"isDraft":%t,"headRefOid":%q,"baseRefName":%q,"reviewDecision":%q,"mergeable":%q,"author":{"login":%q}}`,
				w.State, w.Draft, w.Head, w.Base, w.Decision, w.Mergeable, w.Author))
		case strings.HasPrefix(j, "pr checks"):
			if w.OnChecks != nil {
				w.OnChecks()
			}
			return execx.Result{Code: w.ChecksCode, Stdout: []byte(w.Checks), Stderr: []byte(w.ChecksErr)}
		case strings.HasPrefix(j, "pr edit"):
			who := args[len(args)-1]
			w.Edits = append(w.Edits, who)
			if w.EditFail[who] {
				return execx.Result{Code: 1, Stderr: []byte("could not add reviewer")}
			}
			return ok("")
		case strings.HasPrefix(j, "api graphql"):
			return ok(w.Graphql)
		case strings.HasPrefix(j, "run view"):
			return ok("FAILED log tail\n")
		case strings.Contains(j, "/reviews"):
			w.ReviewCalls++
			return ok(w.Reviews)
		case strings.Contains(j, "/pulls/") && strings.HasSuffix(j, "/comments --paginate"):
			return ok(w.Comments)
		case strings.Contains(j, "/issues/") && strings.HasSuffix(j, "/comments --paginate"):
			return ok(w.Issue)
		}
		return execx.Result{Code: 99, Stderr: []byte("world: no rule for " + j)}
	}
	return ghtest.New(ghtest.Rule{Prefix: []string{}, Func: fn})
}

type sent struct{ Channel, Text, ThreadTS string }

type fakeSlack struct {
	mu    sync.Mutex
	Sent  []sent
	Fail  bool
	TS    string
	ChID  string
	Read  string
	Reads int
}

func (f *fakeSlack) Send(_ context.Context, ch, text, ts string) (string, string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Fail {
		return "", "", fmt.Errorf("slack down")
	}
	f.Sent = append(f.Sent, sent{ch, text, ts})
	t := f.TS
	if t == "" {
		t = "1789128876.624469"
	}
	return t, f.ChID, nil
}

func (f *fakeSlack) ReadPermalink(context.Context, string) (string, error) {
	f.Reads++
	return f.Read, nil
}

type env struct {
	t     *testing.T
	h     *home.Home
	w     *world
	slack *fakeSlack
	gh    *ghtest.Client
	now   time.Time
}

func newEnv(t *testing.T) *env {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv("SETU_HOME", dir+"/setu")
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	e := &env{t: t, h: h, w: newWorld(), slack: &fakeSlack{}, now: t0}
	e.gh = e.w.client()
	e.writeJSON("ui_settings.json", map[string]any{
		"reviewers":        []any{},
		"active_reviewers": []any{},
		"slack_channels":   []any{map[string]string{"id": "C0AAAAAAAA", "name": "reviews"}},
	})
	e.writeJSON("channels.json", map[string]any{
		"workspace_url": "https://acme.slack.com", "bot_uid": "UBOT000001", "owner_uid": "UOWN000001",
		"dm_fallback": "D0DM000001", "known_bots": []string{"helper-bot"},
		"channels": map[string]string{"acme/app": "C0AAAAAAAA"},
		"trigger":  "<@{bot_uid}>, review this PR\n{pr_url}", "retrigger": "<@{bot_uid}> recheck",
	})
	return e
}

func (e *env) writeJSON(name string, v any) {
	e.t.Helper()
	b, _ := json.Marshal(v)
	if err := os.WriteFile(e.h.Path(name), b, 0o600); err != nil {
		e.t.Fatal(err)
	}
}

// run runs `setu <args...>` and returns the exit code, stdout and stderr.
func (e *env) run(args ...string) (int, string, string) { return e.runEnv(nil, args...) }

func (e *env) runEnv(vars map[string]string, args ...string) (int, string, string) {
	e.t.Helper()
	var out, errb bytes.Buffer
	cmds := CommandsWith(CLIDeps{GH: e.gh, Slack: e.slack, Now: func() time.Time { return e.now },
		Sleep: func(ctx context.Context, d time.Duration) error { e.now = e.now.Add(d); return nil }})
	en := cli.Env{Stdin: strings.NewReader(""), Stdout: &out, Stderr: &errb, Home: e.h,
		Getenv: func(k string) string { return vars[k] }}
	code := cli.Run(context.Background(), en, cmds, args)
	return code, out.String(), errb.String()
}

func (e *env) stateFile() string {
	b, err := os.ReadFile(e.h.Path("pr-grind", "acme-app-7.md"))
	if err != nil {
		e.t.Fatal(err)
	}
	return string(b)
}

func (e *env) seedState(extra ...string) {
	e.t.Helper()
	lines := []string{
		"# pr-grind - acme/app #7", "",
		"owner: acme", "repo: app", "number: 7", "author: alice", "base: staging",
		"thread: https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469", "channel: C0AAAAAAAA",
		"reviewers: bob", "reviewers-last: UBOT000001", "last-seen: 2026-11-12T09:00:00Z", "started: 2026-11-12T09:00:00Z",
		"updated: 2026-11-12T09:00:00Z",
	}
	lines = append(lines, extra...)
	if err := os.MkdirAll(e.h.Path("pr-grind"), 0o700); err != nil {
		e.t.Fatal(err)
	}
	if err := os.WriteFile(e.h.Path("pr-grind", "acme-app-7.md"), []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		e.t.Fatal(err)
	}
}

func jsonOf(t *testing.T, s string) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatalf("not JSON: %v\n%s", err, s)
	}
	return m
}

func review(id int, login, state, at, commit, body string) string {
	return fmt.Sprintf(`{"id":%d,"user":{"login":%q,"type":"User"},"state":%q,"submitted_at":%q,"commit_id":%q,"body":%q}`, id, login, state, at, commit, body)
}

func botReview(id int, login, state, at, commit, body string) string {
	return strings.Replace(review(id, login, state, at, commit, body), `"type":"User"`, `"type":"Bot"`, 1)
}

func inline(id, reviewID int, path string, line int, body string) string {
	return fmt.Sprintf(`{"id":%d,"user":{"login":"bob","type":"User"},"path":%q,"line":%d,"body":%q,"in_reply_to_id":null,"pull_request_review_id":%d,"created_at":"2026-11-12T10:30:00Z"}`, id, path, line, body, reviewID)
}

func arr(items ...string) string { return "[" + strings.Join(items, ",") + "]" }

func writeFile(path, body string) error { return os.WriteFile(path, []byte(body), 0o600) }

func osMkdir(p string) error { return os.MkdirAll(p, 0o700) }

func (e *env) files() Files { return Files{e.h} }
