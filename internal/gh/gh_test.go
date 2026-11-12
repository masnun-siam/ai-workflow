package gh_test

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
)

var bg = context.Background()

func TestJSON(t *testing.T) {
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"scalar"}, Stdout: "abc123\n"},
		ghtest.Rule{Prefix: []string{"empty"}, Stdout: ""},
		ghtest.Rule{Prefix: []string{"obj"}, Stdout: `{"a":1}`},
		ghtest.Rule{Prefix: []string{"fail"}, Code: 1, Stderr: "boom\nlast line\n"},
	)
	var s any
	if _, err := c.JSON(bg, []string{"scalar"}, 0, &s); err != nil || s != "abc123" {
		t.Fatalf("scalar: %v %v", s, err)
	}
	var str string
	if _, err := c.JSON(bg, []string{"scalar"}, 0, &str); err != nil || str != "abc123" {
		t.Fatalf("scalar string: %q %v", str, err)
	}
	s = "x"
	if _, err := c.JSON(bg, []string{"empty"}, 0, &s); err != nil || s != nil {
		t.Fatalf("empty -> null: %v %v", s, err)
	}
	var m map[string]int
	if _, err := c.JSON(bg, []string{"obj"}, 0, &m); err != nil || m["a"] != 1 {
		t.Fatalf("obj: %v %v", m, err)
	}
	m = map[string]int{"keep": 1}
	res, err := c.JSON(bg, []string{"fail"}, 0, &m)
	if err == nil || errs.KindOf(err) != errs.KUpstream || err.Error() != "last line" || res.Code != 1 || m["keep"] != 1 {
		t.Fatalf("fail: %v %v", err, m)
	}
	var m2 map[string]int
	if _, err := c.JSON(bg, []string{"scalar"}, 0, &m2); err == nil {
		t.Fatal("non-JSON into a map must error")
	}
}

func TestGraphQL(t *testing.T) {
	reset := time.Now().Add(time.Hour).UTC().Truncate(time.Second)
	okBody := fmt.Sprintf(`{"data":{"x":1,"rateLimit":{"cost":3,"remaining":4990,"resetAt":%q}}}`, reset.Format(time.RFC3339))
	cases := []struct {
		name    string
		rule    ghtest.Rule
		limited bool
		wantErr string
	}{
		{"ok", ghtest.Rule{Stdout: okBody}, false, ""},
		{"stderr rate limit", ghtest.Rule{Code: 1, Stderr: "API Rate Limit exceeded"}, true, "rate limited"},
		{"typed rate limit", ghtest.Rule{Stdout: `{"errors":[{"type":"RATE_LIMITED","message":"x"}]}`}, true, "rate limited"},
		{"payload text is not matched", ghtest.Rule{Stdout: `{"data":{"title":"rate limit docs"}}`}, false, ""},
		{"errors", ghtest.Rule{Stdout: `{"errors":[{"type":"NOT_FOUND","message":"nope"}]}`}, false, `[{"type":"NOT_FOUND","message":"nope","path":null}]`},
		{"rc and stderr", ghtest.Rule{Code: 1, Stderr: "auth failed"}, false, "auth failed"},
		{"non-json", ghtest.Rule{Stdout: "<html>"}, false, "<html>"},
		{"empty output", ghtest.Rule{}, false, "gh did not return a GraphQL response"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := ghtest.New(tc.rule)
			var out map[string]any
			rl, _, err := c.GraphQL(bg, "query{x}", map[string]any{"owner": "o", "name": "n", "number": 7, "after": ""}, &out)
			if tc.wantErr == "" {
				if err != nil {
					t.Fatal(err)
				}
			} else if err == nil || err.Error() != tc.wantErr {
				t.Fatalf("err = %v, want %q", err, tc.wantErr)
			}
			if errors.Is(err, gh.ErrRateLimited) != tc.limited {
				t.Fatalf("limited = %v", errors.Is(err, gh.ErrRateLimited))
			}
			if tc.name == "ok" {
				if rl.Cost != 3 || rl.Remaining != 4990 || !rl.ResetAt.Equal(reset) {
					t.Fatalf("rate limit %+v", rl)
				}
				a := strings.Join(c.Calls[0], " ")
				if !strings.Contains(a, "-f owner=o") || !strings.Contains(a, "-F number=7") || !strings.HasPrefix(a, "api graphql -f query=query{x}") {
					t.Fatalf("argv %v", c.Calls[0])
				}
			}
		})
	}
}

func TestParsePRRef(t *testing.T) {
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"repo", "view"}, Stdout: "acme/widgets\n"},
	)
	good := map[string]gh.PRRef{
		"https://github.com/o/r/pull/12": {Owner: "o", Repo: "r", N: 12},
		"github.com/o/r/pull/12/files":   {Owner: "o", Repo: "r", N: 12},
		"o/r#34":                         {Owner: "o", Repo: "r", N: 34},
		"o/r 56":                         {Owner: "o", Repo: "r", N: 56},
		"  o/r#7 ":                       {Owner: "o", Repo: "r", N: 7},
		"9":                              {Owner: "acme", Repo: "widgets", N: 9},
	}
	for in, want := range good {
		got, err := gh.ParsePRRef(bg, c, in, "")
		if err != nil || got != want {
			t.Errorf("%q: %+v %v", in, got, err)
		}
	}
	_, err := gh.ParsePRRef(bg, c, "nonsense", "")
	if err == nil || err.Error() != "unrecognised PR reference: 'nonsense' (want a URL, owner/repo#N, or N)" || errs.KindOf(err) != errs.KInvalid {
		t.Errorf("unrecognised: %v", err)
	}
	_, err = gh.ParsePRRef(bg, c, "it's", "")
	if err == nil || !strings.Contains(err.Error(), `"it's"`) {
		t.Errorf("repr quoting: %v", err)
	}
	c2 := ghtest.New(ghtest.Rule{Prefix: []string{"repo", "view"}, Code: 1, Stderr: "not a git repository\n"})
	_, err = gh.ParsePRRef(bg, c2, "5", "")
	if err == nil || err.Error() != "cannot resolve owner/repo for PR 5: not a git repository" {
		t.Errorf("bare failure: %v", err)
	}
}

func checksRule(stdout string, code int, stderr string) ghtest.Rule {
	return ghtest.Rule{Prefix: []string{"pr", "checks"}, Stdout: stdout, Code: code, Stderr: stderr}
}

func viewRule(mergeable string) ghtest.Rule {
	return ghtest.Rule{Prefix: []string{"pr", "view"}, Stdout: fmt.Sprintf(`{"headRefOid":"abc","mergeable":%q}`, mergeable)}
}

func TestCISnapshot(t *testing.T) {
	pr := gh.PRRef{Owner: "o", Repo: "r", N: 3}
	rows := func(buckets ...string) string {
		var parts []string
		for i, b := range buckets {
			parts = append(parts, fmt.Sprintf(`{"name":"c%d","state":"S","bucket":%q,"link":"https://x/runs/%d/job/1"}`, i, b, 100+i))
		}
		return "[" + strings.Join(parts, ",") + "]"
	}
	cases := []struct {
		name    string
		rules   []ghtest.Rule
		state   string
		note    string
		failing int
	}{
		{"conflict skips checks", []ghtest.Rule{viewRule("CONFLICTING")}, "conflict", "merge conflict with the base branch", 0},
		{"unknown mergeable falls through", []ghtest.Rule{viewRule("UNKNOWN"), checksRule(rows("pass"), 0, "")}, "green", "", 0},
		{"no checks is green", []ghtest.Rule{viewRule("MERGEABLE"), checksRule("", 1, "no checks reported on the 'x' branch")}, "green", "no checks configured", 0},
		{"nonzero exit with json is read", []ghtest.Rule{viewRule("MERGEABLE"), checksRule(rows("pass", "fail"), 1, "")}, "red", "", 1},
		{"pending beats red", []ghtest.Rule{viewRule("MERGEABLE"), checksRule(rows("fail", "pending", "pass"), 8, "")}, "pending", "", 1},
		{"empty rows green", []ghtest.Rule{viewRule("MERGEABLE"), checksRule("[]", 0, "")}, "green", "", 0},
		{"skipping is green", []ghtest.Rule{viewRule("MERGEABLE"), checksRule(rows("skipping", "pass"), 0, "")}, "green", "", 0},
		{"other failure is error", []ghtest.Rule{viewRule("MERGEABLE"), checksRule("", 1, "HTTP 403: API rate limit exceeded")}, "error", "HTTP 403: API rate limit exceeded", 0},
		{"error note is cut at 300", []ghtest.Rule{viewRule("MERGEABLE"), checksRule("", 1, strings.Repeat("x", 500))}, "error", strings.Repeat("x", 300), 0},
		{"bucket case-insensitive", []ghtest.Rule{viewRule("MERGEABLE"), checksRule(`[{"name":"a","bucket":"FAIL","link":""}]`, 1, "")}, "red", "", 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := gh.CISnapshot(bg, ghtest.New(tc.rules...), pr)
			if got.State != tc.state || got.Note != tc.note || len(got.Failing) != tc.failing || got.HeadSHA != "abc" {
				t.Fatalf("%+v", got)
			}
		})
	}
}

func TestCIJSONShape(t *testing.T) {
	b, _ := json.Marshal(gh.CI{State: "green"})
	if string(b) != `{"state":"green","head_sha":null,"failing":[]}` {
		t.Fatal(string(b))
	}
	b, _ = json.Marshal(gh.CI{State: "red", HeadSHA: "x", Failing: []gh.CIFail{{Name: "n", State: "FAILURE", Bucket: "fail", Link: "l"}}, Note: "hi", CIAttempted: true})
	if string(b) != `{"state":"red","head_sha":"x","failing":[{"name":"n","state":"FAILURE","bucket":"fail","link":"l"}],"note":"hi","ci_attempted":true}` {
		t.Fatal(string(b))
	}
}

func TestCIWatchAndExpand(t *testing.T) {
	old := gh.CIPollInterval
	gh.CIPollInterval = time.Millisecond
	defer func() { gh.CIPollInterval = old }()
	pr := gh.PRRef{Owner: "o", Repo: "r", N: 3}

	// pending twice, then red
	n := 0
	c := ghtest.New(viewRule("MERGEABLE"), ghtest.Rule{Prefix: []string{"pr", "checks"}, Func: func([]string) execx.Result {
		n++
		if n < 3 {
			return execx.Result{Code: 8, Stdout: []byte(`[{"name":"a","bucket":"pending","link":""}]`)}
		}
		return execx.Result{Code: 1, Stdout: []byte(`[{"name":"a","state":"FAILURE","bucket":"fail","link":"https://github.com/o/r/actions/runs/777/job/9"}]`)}
	}})
	long := strings.Repeat("é", 5000)
	c.Add(ghtest.Rule{Prefix: []string{"run", "view", "777"}, Stdout: long + "\n"})
	res := gh.CIWatch(bg, c, pr, time.Minute)
	if res.State != "red" || n != 3 || res.Note != "" {
		t.Fatalf("%+v n=%d", res, n)
	}
	res = gh.ExpandFailing(bg, c, pr, res)
	if len(res.Failing) != 1 || res.Failing[0].RunID != "777" || len([]rune(res.Failing[0].LogExcerpt)) != 4000 {
		t.Fatalf("%+v", res.Failing)
	}
	if calls := c.CallsMatching("run", "view", "777", "--repo", "o/r", "--log-failed"); len(calls) != 1 {
		t.Fatalf("run view call: %v", c.Calls)
	}

	// cap expiry while pending
	c2 := ghtest.New(viewRule("MERGEABLE"), checksRule(`[{"name":"a","bucket":"pending","link":""}]`, 8, ""))
	res = gh.CIWatch(bg, c2, pr, 20*time.Millisecond)
	if res.State != "pending" || res.Note != "wall-clock cap of 0s expired with checks still pending" {
		t.Fatalf("%+v", res)
	}
	// error keeps polling, then recovers
	k := 0
	c3 := ghtest.New(viewRule("MERGEABLE"), ghtest.Rule{Prefix: []string{"pr", "checks"}, Func: func([]string) execx.Result {
		k++
		if k == 1 {
			return execx.Result{Code: 1, Stderr: []byte("network down")}
		}
		return execx.Result{Stdout: []byte(`[]`)}
	}})
	if res = gh.CIWatch(bg, c3, pr, time.Minute); res.State != "green" || k != 2 {
		t.Fatalf("%+v k=%d", res, k)
	}
	// link without a run id: no log call
	c4 := ghtest.New()
	out := gh.ExpandFailing(bg, c4, pr, gh.CI{State: "red", Failing: []gh.CIFail{{Name: "ext", Link: "https://ci.example/build/1"}}})
	b, _ := json.Marshal(out.Failing)
	if string(b) != `[{"name":"ext","run_id":"","link":"https://ci.example/build/1","log_excerpt":""}]` || len(c4.Calls) != 0 {
		t.Fatalf("%s", b)
	}
}

const threadsPage1 = `{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":true,"endCursor":"CUR1"},"nodes":[
 {"id":"T1","isResolved":false,"isOutdated":false,"path":"a.go","line":10,"comments":{"nodes":[{"databaseId":111,"url":"https://x/c/111","body":"b"}]}},
 {"id":"T2","isResolved":true,"isOutdated":true,"path":"b.go","line":null,"comments":{"nodes":[{"databaseId":222,"url":"https://x/c/222","body":"b"}]}}]}}}}}`
const threadsPage2 = `{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[
 {"id":"T3","isResolved":false,"isOutdated":true,"path":"c.go","line":3,"comments":{"nodes":[]}}]}}}}}`

func threadsClient() *ghtest.Client {
	return ghtest.New(
		ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "cursor=CUR1", Stdout: threadsPage2},
		ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "reviewThreads", Stdout: threadsPage1},
	)
}

func TestListThreads(t *testing.T) {
	c := threadsClient()
	ts, err := gh.ListThreads(bg, c, gh.PRRef{Owner: "o", Repo: "r", N: 5})
	if err != nil || len(ts) != 3 || len(c.Calls) != 2 {
		t.Fatalf("%v %v calls=%d", ts, err, len(c.Calls))
	}
	if ts[0].CommentID != 111 || ts[0].URL != "https://x/c/111" || ts[0].Line == nil || *ts[0].Line != 10 || ts[2].CommentID != 0 {
		t.Fatalf("%+v", ts)
	}
	a := strings.Join(c.Calls[0], " ")
	if !strings.Contains(a, "-f owner=o") || !strings.Contains(a, "-f repo=r") || !strings.Contains(a, "-F number=5") || strings.Contains(a, "-f cursor=") {
		t.Fatalf("first call: %s", a)
	}
	if !strings.Contains(strings.Join(c.Calls[1], " "), "-f cursor=CUR1") {
		t.Fatalf("second call: %v", c.Calls[1])
	}
	if _, err := gh.ListThreads(bg, ghtest.New(ghtest.Rule{Prefix: []string{"api"}, Code: 1, Stderr: "no\n"}), gh.PRRef{Owner: "o", Repo: "r", N: 5}); err == nil || err.Error() != "could not read review threads: no" {
		t.Fatalf("%v", err)
	}
}

func TestThreadForComment(t *testing.T) {
	ts := []gh.Thread{{NodeID: "A", CommentID: 5}, {NodeID: "B", CommentID: 6}}
	for _, id := range []any{6, int64(6), "6", " 6 "} {
		if th, ok := gh.ThreadForComment(ts, id); !ok || th.NodeID != "B" {
			t.Errorf("%v: %v %v", id, th, ok)
		}
	}
	for _, id := range []any{nil, "x", "", 7, 6.5, []int{6}} {
		if _, ok := gh.ThreadForComment(ts, id); ok {
			t.Errorf("%v matched", id)
		}
	}
}

func run(t *testing.T, c gh.Client, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	var so, se bytes.Buffer
	code = cli.Run(bg, cli.Env{Stdout: &so, Stderr: &se, Stdin: strings.NewReader("")}, gh.CommandsWith(c), args)
	return code, so.String(), se.String()
}

func TestCLIThreadsList(t *testing.T) {
	code, out, _ := run(t, threadsClient(), "threads", "list", "o/r#5")
	want := `[
  {
    "node_id": "T1",
    "is_resolved": false,
    "is_outdated": false,
    "comment_id": 111,
    "url": "https://x/c/111",
    "path": "a.go",
    "line": 10
  },
  {
    "node_id": "T2",
    "is_resolved": true,
    "is_outdated": true,
    "comment_id": 222,
    "url": "https://x/c/222",
    "path": "b.go",
    "line": null
  },
  {
    "node_id": "T3",
    "is_resolved": false,
    "is_outdated": true,
    "comment_id": null,
    "url": null,
    "path": "c.go",
    "line": 3
  }
]
`
	if code != 0 || out != want {
		t.Fatalf("code=%d\n%s", code, out)
	}
	code, out, _ = run(t, threadsClient(), "threads", "list", "o/r#5", "--open-only")
	var arr []map[string]any
	_ = json.Unmarshal([]byte(out), &arr)
	if code != 0 || len(arr) != 2 || arr[0]["node_id"] != "T1" || arr[1]["node_id"] != "T3" {
		t.Fatalf("open-only: %s", out)
	}
	code, out, _ = run(t, threadsClient(), "threads", "list", "--for-comment", "222", "o/r#5")
	arr = nil
	_ = json.Unmarshal([]byte(out), &arr)
	if code != 0 || len(arr) != 1 || arr[0]["node_id"] != "T2" {
		t.Fatalf("for-comment: %s", out)
	}
	// for-comment applies after open-only: T2 is resolved, so nothing
	code, out, _ = run(t, threadsClient(), "threads", "list", "o/r#5", "--open-only", "--for-comment=222")
	if code != 0 || out != "[]\n" {
		t.Fatalf("both: %q", out)
	}
	code, _, errOut := run(t, ghtest.New(ghtest.Rule{Prefix: []string{"api"}, Code: 1, Stderr: "denied"}), "threads", "list", "o/r#5")
	if code != 1 || errOut != "could not read review threads: denied\n" {
		t.Fatalf("read failure: %d %q", code, errOut)
	}
	code, _, errOut = run(t, threadsClient(), "threads", "list", "garbage")
	if code != 64 || errOut != "unrecognised PR reference: 'garbage' (want a URL, owner/repo#N, or N)\n" {
		t.Fatalf("bad ref: %d %q", code, errOut)
	}
	if code, _, _ = run(t, threadsClient(), "threads", "list"); code != 64 {
		t.Fatalf("missing pr: %d", code)
	}
}

func TestCLIThreadsResolve(t *testing.T) {
	resolve := func(id string) ghtest.Rule {
		return ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "id=" + id, Stdout: `{"data":{"resolveReviewThread":{"thread":{"id":"` + id + `","isResolved":true}}}}`}
	}
	c := ghtest.New(resolve("A"),
		ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "id=B", Stdout: `{"errors":[{"message":"nope"}]}`},
		ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "id=C", Stdout: `{"data":{"resolveReviewThread":{"thread":{"id":"C","isResolved":false}}}}`},
		ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "id=D", Code: 1, Stderr: "HTTP 500\n"},
	)
	code, out, errOut := run(t, c, "threads", "resolve", "A", "B")
	if code != 0 || out != "resolved A\n" || !strings.HasPrefix(errOut, "warning: could not resolve B: ") {
		t.Fatalf("partial: %d %q %q", code, out, errOut)
	}
	code, out, errOut = run(t, c, "threads", "resolve", "B", "C", "D")
	if code != 1 || out != "" || !strings.Contains(errOut, "warning: could not resolve C:\n") || !strings.Contains(errOut, "could not resolve D: HTTP 500") {
		t.Fatalf("all failed: %d %q %q", code, out, errOut)
	}
	if code, _, _ = run(t, c, "threads", "resolve"); code != 64 {
		t.Fatalf("no ids: %d", code)
	}
}

func TestCLICIStatus(t *testing.T) {
	c := ghtest.New(viewRule("MERGEABLE"),
		checksRule(`[{"name":"build","state":"FAILURE","bucket":"fail","link":"https://github.com/o/r/actions/runs/42/job/1"},{"name":"lint","state":"SUCCESS","bucket":"pass","link":""}]`, 1, ""),
		ghtest.Rule{Prefix: []string{"run", "view", "42"}, Stdout: "log tail — é\n"},
	)
	code, out, _ := run(t, c, "ci", "status", "https://github.com/o/r/pull/3")
	want := `{
  "state": "red",
  "head_sha": "abc",
  "failing": [
    {
      "name": "build",
      "run_id": "42",
      "link": "https://github.com/o/r/actions/runs/42/job/1",
      "log_excerpt": "log tail \u2014 \u00e9"
    }
  ]
}
`
	if code != 0 || out != want {
		t.Fatalf("code=%d\n%s", code, out)
	}
	code, out, _ = run(t, ghtest.New(viewRule("CONFLICTING")), "ci", "status", "o/r#3")
	if code != 0 || out != "{\n  \"state\": \"conflict\",\n  \"head_sha\": \"abc\",\n  \"failing\": [],\n  \"note\": \"merge conflict with the base branch\"\n}\n" {
		t.Fatalf("conflict: %d %q", code, out)
	}
	if code, _, errOut := run(t, c, "ci", "status", "nope"); code != 64 || !strings.HasPrefix(errOut, "unrecognised PR reference") {
		t.Fatalf("bad ref: %d %q", code, errOut)
	}
	if code, _, _ := run(t, c, "ci", "status", "o/r#3", "--timeout", "abc"); code != 64 {
		t.Fatalf("bad timeout: %d", code)
	}
	if code, _, _ := run(t, c, "ci", "bogus"); code != 64 {
		t.Fatalf("bad subverb: %d", code)
	}
	// --watch with a one-second cap and checks pending: state stays pending, note set
	old := gh.CIPollInterval
	gh.CIPollInterval = time.Millisecond
	defer func() { gh.CIPollInterval = old }()
	cp := ghtest.New(viewRule("MERGEABLE"), checksRule(`[{"name":"a","bucket":"pending","link":""}]`, 8, ""))
	code, out, _ = run(t, cp, "ci", "status", "o/r#3", "--watch", "--timeout", "0")
	if code != 0 || !strings.Contains(out, `"note": "wall-clock cap of 0s expired with checks still pending"`) {
		t.Fatalf("watch: %d %s", code, out)
	}
}

func TestAuth(t *testing.T) {
	n := 0
	c := ghtest.New(ghtest.Rule{Prefix: []string{"api", "user"}, Func: func([]string) execx.Result {
		n++
		return execx.Result{Stdout: []byte("Octo\n")}
	}})
	a := gh.NewAuth(c)
	ch := make(chan gh.Auth, 4)
	a.OnChange(func(v gh.Auth) { ch <- v })
	got := a.Get(bg)
	if !got.OK || got.Login != "Octo" || !got.Solo("octo") || got.Solo("other") {
		t.Fatalf("%+v", got)
	}
	if v := <-ch; v.Login != "Octo" {
		t.Fatalf("first flip %+v", v)
	}
	a.Get(bg)
	if n != 1 {
		t.Fatalf("cached call count %d", n)
	}
}

func TestAuthStaleRefresh(t *testing.T) {
	calls := make(chan struct{}, 10)
	n := 0
	c := ghtest.New(ghtest.Rule{Prefix: []string{"api", "user"}, Func: func([]string) execx.Result {
		n++
		defer func() { calls <- struct{}{} }()
		switch n {
		case 1:
			return execx.Result{Stdout: []byte("octo\n")}
		case 2:
			return execx.Result{Code: 124, Stderr: []byte("timed out after 60s")}
		default:
			return execx.Result{Code: 1, Stderr: []byte("To get started with GitHub CLI, please run:  gh auth login\nmore")}
		}
	}})
	a := gh.NewAuth(c)
	var off atomic.Int64 // seconds added to the real clock
	gh.SetAuthClock(a, func() time.Time { return time.Now().Add(time.Duration(off.Load()) * time.Second) })
	step := int64(2 * gh.AuthTTL / time.Second)
	a.Get(bg)
	<-calls
	off.Add(step)
	// stale: serves the old value at once, refreshes behind
	if v := a.Get(bg); !v.OK {
		t.Fatalf("stale serve %+v", v)
	}
	<-calls
	time.Sleep(50 * time.Millisecond)
	// a timed-out refresh keeps the previous value
	off.Add(step)
	if v := a.Get(bg); !v.OK || v.Login != "octo" {
		t.Fatalf("after timeout %+v", v)
	}
	<-calls
	time.Sleep(50 * time.Millisecond)
	off.Add(step)
	a.Get(bg)
	<-calls
	time.Sleep(50 * time.Millisecond)
	v := a.Get(bg)
	if v.OK || v.Error != "To get started with GitHub CLI, please run:  gh auth login" {
		t.Fatalf("signed out %+v", v)
	}
}

func TestIssuePopup(t *testing.T) {
	issue := `{"number":7,"title":"T","html_url":"https://github.com/o/r/issues/7","state":"open","state_reason":null,"user":{"login":"ann"},"created_at":"2026-01-01T00:00:00Z",
	 "labels":[{"name":"bug","color":"f00"}],"assignees":[{"login":"bob"},null],"milestone":{"title":"M1"},"body_html":"<p><a href=\"x\">l</a></p>","comments":2}`
	comments := `[{"user":null,"created_at":"2026-01-02T00:00:00Z","body_html":"<a href=\"y\">c</a>"}]`
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/7/comments?per_page=100", Stdout: comments},
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/7", Stdout: issue},
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/8", Code: 1, Stderr: "gh: Not Found (HTTP 404)\n"},
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/9/comments", Code: 1, Stderr: "boom\nHTTP 500\n"},
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/9", Stdout: `{"number":9}`},
		ghtest.Rule{Prefix: []string{"api", "-H"}, Contains: "issues/10", Code: 1, Stderr: "dial tcp\nconnection refused\n"},
	)
	v, err := gh.IssuePopup(bg, c, "o/r", 7)
	if err != nil {
		t.Fatal(err)
	}
	if v.Number != 7 || v.Author != "ann" || v.CommentCount != 2 || len(v.Comments) != 1 || v.Comments[0].Author != "ghost" ||
		v.Assignees[1] != "ghost" || *v.Milestone != "M1" || v.IsPR || v.StateReason != nil ||
		!strings.Contains(v.BodyHTML, `<a target="_blank" rel="noopener noreferrer" href="x">`) || !strings.Contains(v.Comments[0].BodyHTML, "noopener") {
		t.Fatalf("%+v", v)
	}
	if got := strings.Join(c.Calls[0], " "); got != "api -H Accept: application/vnd.github.html+json repos/o/r/issues/7" {
		t.Fatal(got)
	}
	if _, err = gh.IssuePopup(bg, c, "o/r", 8); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("404: %v", err)
	}
	if _, err = gh.IssuePopup(bg, c, "o/r", 9); errs.KindOf(err) != errs.KUpstream || err.Error() != "HTTP 500" {
		t.Fatalf("comments 502: %v", err)
	}
	if _, err = gh.IssuePopup(bg, c, "o/r", 10); errs.KindOf(err) != errs.KUpstream || err.Error() != "connection refused" {
		t.Fatalf("502: %v", err)
	}
	if _, err = gh.IssuePopup(bg, c, "../r", 1); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("invalid: %v", err)
	}
}

func TestPRPopup(t *testing.T) {
	big := strings.Repeat("x", 60_001)
	mid := strings.Repeat("y", 250_000)
	files := fmt.Sprintf(`[{"filename":"a","status":"modified","additions":1,"deletions":2,"patch":"@@ a"},
	 {"filename":"big","status":"added","additions":9,"deletions":0,"patch":%q},
	 {"filename":"m1","status":"added","additions":1,"deletions":0,"patch":%q},
	 {"filename":"m2","status":"added","additions":1,"deletions":0,"patch":%q},
	 {"filename":"m3","status":"added","additions":1,"deletions":0,"patch":%q},
	 {"filename":"bin","status":"added","additions":0,"deletions":0}]`, big, mid[:59_000], mid[:59_000], strings.Repeat("z", 59_000)) // ok, cut, in, in, ...,
	pr := `{"number":3,"title":"P","html_url":"https://github.com/o/r/pull/3","state":"open","draft":true,"merged":false,"user":{"login":"ann"},
	 "head":{"ref":"feat","sha":"deadbeefcafe"},"base":{"ref":"staging"},"mergeable_state":"dirty","body_html":"<p>b</p>","additions":10,"deletions":3}`
	commits := `[{"sha":"1234567890","author":{"login":"ann"},"commit":{"message":"first\nbody","author":{"name":"Ann"}}},
	 {"sha":"abcdefghij","author":null,"commit":{"message":"two","author":{"name":"Zed"}}},
	 {"sha":"zzzzzzzzzz","author":null,"commit":{"message":"three","author":{}}}]`
	comments := `[{"user":{"login":"c1"},"created_at":"2026-01-03T00:00:00Z","body_html":"hi"}]`
	reviews := `[{"user":{"login":"r1"},"state":"APPROVED","submitted_at":"2026-01-02T00:00:00Z","body_html":""},
	 {"user":{"login":"r2"},"state":"PENDING","submitted_at":"2026-01-01T00:00:00Z","body_html":"x"},
	 {"user":{"login":"r3"},"state":"COMMENTED","submitted_at":"2026-01-04T00:00:00Z","body_html":""},
	 {"user":{"login":"r4"},"state":"COMMENTED","submitted_at":"2026-01-05T00:00:00Z","body_html":"<p>see</p>"}]`
	rollup := `{"statusCheckRollup":[{"__typename":"CheckRun","name":"build","detailsUrl":"u1","status":"COMPLETED","conclusion":"FAILURE"},
	 {"__typename":"CheckRun","name":"test","detailsUrl":"u2","status":"IN_PROGRESS","conclusion":""},
	 {"__typename":"CheckRun","name":"lint","detailsUrl":"u3","status":"COMPLETED","conclusion":"SUCCESS"},
	 {"__typename":"StatusContext","context":"ci/x","targetUrl":"u4","state":"PENDING"},
	 {"__typename":"StatusContext","context":"ci/y","targetUrl":"u5","state":"ERROR"}]}`
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/files", Stdout: files},
		ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/commits", Stdout: commits},
		ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/reviews", Stdout: reviews},
		ghtest.Rule{Prefix: []string{"api"}, Contains: "issues/3/comments", Stdout: comments},
		ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3", Stdout: pr},
		ghtest.Rule{Prefix: []string{"pr", "view"}, Stdout: rollup},
	)
	v, err := gh.PRPopup(bg, c, "o/r", 3)
	if err != nil {
		t.Fatal(err)
	}
	if v.State != "draft" || !v.Conflict || v.Head != "feat" || v.Base != "staging" || v.HeadSHA != "deadbeefcafe" || v.Author != "ann" {
		t.Fatalf("%+v", v)
	}
	var cut []string
	for _, f := range v.Files {
		if f.PatchCut {
			if f.Patch != nil {
				t.Errorf("%s: cut but patch set", f.Path)
			}
			cut = append(cut, f.Path)
		}
	}
	// a ok; big > 60000 cut; m1 59000 ok (total 59009); m2 ok; m3 ok... budget 500000: a(4)+m1+m2+m3 = 177004 -> all fit
	if len(cut) != 1 || cut[0] != "big" {
		t.Fatalf("cut = %v", cut)
	}
	if v.Files[5].Patch != nil || v.Files[5].PatchCut {
		t.Fatalf("binary file: %+v", v.Files[5])
	}
	if len(v.Commits) != 3 || v.Commits[0].SHA != "1234567" || v.Commits[0].Message != "first" || v.Commits[1].Author != "Zed" || v.Commits[2].Author != "ghost" {
		t.Fatalf("%+v", v.Commits)
	}
	var conv []string
	for _, it := range v.Conversation {
		conv = append(conv, it.Kind+":"+it.Author+":"+it.State)
	}
	if strings.Join(conv, ",") != "review:r1:APPROVED,comment:c1:,review:r4:COMMENTED" {
		t.Fatalf("conversation %v", conv)
	}
	got := map[string]string{}
	for _, ch := range v.Checks {
		got[ch.Name] = ch.Bucket
	}
	if fmt.Sprint(got) != "map[build:red ci/x:pending ci/y:red lint:green test:pending]" {
		t.Fatalf("%v", got)
	}
	if len(c.Calls) != 6 {
		t.Fatalf("calls %d", len(c.Calls))
	}
}

func TestPRPopupTotalCapAndErrors(t *testing.T) {
	var parts []string
	for i := 0; i < 10; i++ {
		parts = append(parts, fmt.Sprintf(`{"filename":"f%d","patch":%q}`, i, strings.Repeat("p", 59_000)))
	}
	rules := func(prBody string, code int, stderr string) []ghtest.Rule {
		return []ghtest.Rule{
			ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/files", Stdout: "[" + strings.Join(parts, ",") + "]"},
			ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/commits", Stdout: "[]"},
			ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3/reviews", Stdout: "[]"},
			ghtest.Rule{Prefix: []string{"api"}, Contains: "issues/3/comments", Stdout: "[]"},
			ghtest.Rule{Prefix: []string{"api"}, Contains: "pulls/3", Stdout: prBody, Code: code, Stderr: stderr},
			ghtest.Rule{Prefix: []string{"pr", "view"}, Code: 1, Stderr: "no rollup"},
		}
	}
	v, err := gh.PRPopup(bg, ghtest.New(rules(`{"number":3,"state":"closed","merged_at":"2026-01-01T00:00:00Z"}`, 0, "")...), "o/r", 3)
	if err != nil || v.State != "merged" {
		t.Fatalf("%v %v", v.State, err)
	}
	withPatch := 0
	for _, f := range v.Files {
		if f.Patch != nil {
			withPatch++
		}
	}
	if withPatch != 8 || len(v.Checks) != 0 { // 8 x 59000 = 472000; the 9th would pass 500000
		t.Fatalf("withPatch=%d checks=%v", withPatch, v.Checks)
	}
	if _, err = gh.PRPopup(bg, ghtest.New(rules("", 1, "HTTP 404: Not Found")...), "o/r", 3); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("404: %v", err)
	}
	if _, err = gh.PRPopup(bg, ghtest.New(rules("", 1, "HTTP 502\nbad gateway")...), "o/r", 3); errs.KindOf(err) != errs.KUpstream || err.Error() != "bad gateway" {
		t.Fatalf("502: %v", err)
	}
}

func TestOpenItemsAndBranches(t *testing.T) {
	rows := `[{"number":1,"title":"old","labels":[{"name":"a"}],"updatedAt":"2026-01-01T00:00:00Z","url":"https://github.com/o/r/issues/1"},
	 {"number":2,"title":"new","labels":[],"updatedAt":"2026-02-01T00:00:00Z","url":"http://insecure","isDraft":true},
	 {"title":"no number"}]`
	c := ghtest.New(ghtest.Rule{Prefix: []string{"pr", "list", "--repo", "o/r", "--state", "open", "--limit", "100", "--json", "number,title,labels,updatedAt,url,isDraft"}, Stdout: rows},
		ghtest.Rule{Prefix: []string{"issue", "list"}, Code: 1, Stderr: "no access\n"})
	items, err := gh.OpenItems(bg, c, "o/r", "pr")
	if err != nil || len(items) != 2 || items[0].Number != 2 || !items[0].Draft || items[0].URL != "" || items[1].URL == "" || items[1].Labels[0] != "a" {
		t.Fatalf("%+v %v", items, err)
	}
	if _, err = gh.OpenItems(bg, c, "o/r", "bogus"); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
	if _, err = gh.OpenItems(bg, c, "o/r", "issue"); errs.KindOf(err) != errs.KUpstream || err.Error() != "no access" {
		t.Fatal(err)
	}

	b := ghtest.New(
		ghtest.Rule{Prefix: []string{"repo", "view", "o/r"}, Stdout: "main\n"},
		ghtest.Rule{Prefix: []string{"api", "repos/o/r/branches", "--paginate"}, Stdout: "zeta\nmain\nalpha\nzeta\n"},
		ghtest.Rule{Prefix: []string{"repo", "view", "o/bad"}, Code: 1, Stderr: "Could not resolve\n"},
	)
	bl, err := gh.Branches(bg, b, "o/r")
	if err != nil || bl.Default != "main" || strings.Join(bl.Branches, ",") != "main,alpha,zeta" {
		t.Fatalf("%+v %v", bl, err)
	}
	if _, err = gh.Branches(bg, b, "o/bad"); errs.KindOf(err) != errs.KUpstream {
		t.Fatal(err)
	}
	for _, bad := range []string{"o", "../x", "o/..", "o/r/x", "a b/c"} {
		if _, err = gh.Branches(bg, b, bad); errs.KindOf(err) != errs.KInvalid || err.Error() != "repo must be owner/name" {
			t.Errorf("%q: %v", bad, err)
		}
	}
}

func TestWrites(t *testing.T) {
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"api", "repos/o/r/issues/4/comments"}, Stdout: `{"html_url":"https://github.com/o/r/issues/4#c1"}`},
		ghtest.Rule{Prefix: []string{"issue", "close", "5"}, Code: 1, Stderr: "  denied  \n"},
		ghtest.Rule{Prefix: []string{"issue"}},
		ghtest.Rule{Prefix: []string{"pr"}},
	)
	url, err := gh.Comment(bg, c, "o/r", 4, "hello")
	if err != nil || url != "https://github.com/o/r/issues/4#c1" || strings.Join(c.Calls[0], " ") != "api repos/o/r/issues/4/comments -f body=hello" {
		t.Fatalf("%q %v %v", url, err, c.Calls)
	}
	for _, bad := range []string{"", "  \n", strings.Repeat("a", gh.MaxComment+1)} {
		if _, err = gh.Comment(bg, c, "o/r", 4, bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("comment %d chars: %v", len(bad), err)
		}
	}
	if err = gh.SetIssueState(bg, c, "o/r", 4, "closed", "not_planned"); err != nil || strings.Join(c.Calls[len(c.Calls)-1], " ") != "issue close 4 -R o/r --reason not planned" {
		t.Fatalf("%v %v", err, c.Calls)
	}
	if err = gh.SetIssueState(bg, c, "o/r", 4, "open", ""); err != nil || strings.Join(c.Calls[len(c.Calls)-1], " ") != "issue reopen 4 -R o/r" {
		t.Fatal(err)
	}
	if err = gh.SetIssueState(bg, c, "o/r", 4, "closed", "weird"); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
	if err = gh.SetIssueState(bg, c, "o/r", 4, "merged", ""); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
	if err = gh.SetPRState(bg, c, "o/r", 4, "closed"); err != nil || strings.Join(c.Calls[len(c.Calls)-1], " ") != "pr close 4 -R o/r" {
		t.Fatal(err)
	}
	sha := strings.Repeat("a", 40)
	if err = gh.MergePR(bg, c, "o/r", 4, sha); err != nil || strings.Join(c.Calls[len(c.Calls)-1], " ") != "pr merge 4 -R o/r --merge --match-head-commit "+sha {
		t.Fatalf("%v %v", err, c.Calls[len(c.Calls)-1])
	}
	for _, bad := range []string{"", "abc", strings.Repeat("A", 40), strings.Repeat("a", 41)} {
		if err = gh.MergePR(bg, c, "o/r", 4, bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("sha %q: %v", bad, err)
		}
	}
	closed, err := gh.CloseEpic(bg, c, "o/r", 9, []int{1, 2})
	if err != nil || fmt.Sprint(closed) != "[1 2 9]" {
		t.Fatalf("%v %v", closed, err)
	}
	closed, err = gh.CloseEpic(bg, c, "o/r", 9, []int{1, 5, 2})
	if err == nil || fmt.Sprint(closed) != "[1]" || err.Error() != "closing #5 failed (denied); closed so far: #1" || errs.KindOf(err) != errs.KUpstream {
		t.Fatalf("%v %v", closed, err)
	}
}

func TestRoutes(t *testing.T) {
	c := ghtest.New(
		ghtest.Rule{Prefix: []string{"api", "repos/o/r/issues/4/comments"}, Stdout: `{"html_url":"u"}`},
		ghtest.Rule{Prefix: []string{"issue", "close", "4"}},
		ghtest.Rule{Prefix: []string{"issue", "close", "9"}},
		ghtest.Rule{Prefix: []string{"pr", "merge"}, Code: 1, Stderr: "head moved"},
	)
	var repolled []string
	routes := gh.Routes(gh.Deps{Client: c,
		Repoll:       func(_ context.Context, slug string) { repolled = append(repolled, slug) },
		OpenChildren: func(slug string, epic int) []int { return []int{4} }})
	mux := http.NewServeMux()
	for _, r := range routes {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(method, path, body string) (int, map[string]any) {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		var out map[string]any
		_ = json.Unmarshal(rec.Body.Bytes(), &out)
		return rec.Code, out
	}
	if code, out := do("POST", "/api/issues/o/r/4/comment", `{"text":"hi"}`); code != 200 || out["url"] != "u" {
		t.Fatalf("comment %d %v", code, out)
	}
	if code, _ := do("POST", "/api/pulls/o/r/4/comment", `{"text":"hi"}`); code != 404 && code != 200 && code != 502 {
		t.Fatalf("pulls comment %d", code)
	}
	if code, out := do("POST", "/api/issues/o/r/4/state", `{"state":"closed"}`); code != 200 || out["state"] != "closed" || len(repolled) != 1 {
		t.Fatalf("state %d %v %v", code, out, repolled)
	}
	if code, out := do("POST", "/api/issues/o/r/4/state", `{"state":"nope"}`); code != 400 {
		t.Fatalf("bad state %d %v", code, out)
	}
	if code, _ := do("POST", "/api/pulls/o/r/4/merge", `{"sha":"`+strings.Repeat("b", 40)+`"}`); code != 502 {
		t.Fatalf("merge %d", code)
	}
	if code, _ := do("POST", "/api/pulls/o/r/4/merge", `{"sha":"x"}`); code != 400 {
		t.Fatalf("merge sha %d", code)
	}
	if code, out := do("POST", "/api/epics/o/r/9/close", `{}`); code != 200 || fmt.Sprint(out["closed"]) != "[4 9]" {
		t.Fatalf("epic %d %v", code, out)
	}
	if code, out := do("GET", "/api/issues/o/r/abc", ""); code != 404 && code != 400 {
		t.Fatalf("bad id %d %v", code, out)
	}
	if code, out := do("GET", "/api/repos/o/r/open?kind=bogus", ""); code != 400 {
		t.Fatalf("open kind %d %v", code, out)
	}
}
