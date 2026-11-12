package grind

import (
	"strings"
	"testing"
	"time"
)

func TestDocHeader(t *testing.T) {
	d := parseDoc([]byte("# t\n\nowner: acme\nrepo: app\nnumber: 7\nthread: github\n\n## Round 1 - x\n- finding: a: b\ndone: 2026-11-12T10:00:00Z - approved (deep)\n"))
	if d.Get("owner") != "acme" || d.Get("thread") != "github" {
		t.Fatal("header read")
	}
	if d.Get("done") != "2026-11-12T10:00:00Z - approved (deep)" {
		t.Fatalf("done under a round is terminal: %q", d.Get("done"))
	}
	if d.Rounds() != 1 || len(d.Findings()) != 1 || d.Findings()[0] != "a: b" {
		t.Fatalf("rounds/findings %d %v", d.Rounds(), d.Findings())
	}
	d.Set("author", "alice") // inserted after the last header key line
	i := strings.Index(string(d.bytes()), "author: alice")
	if i < strings.Index(string(d.bytes()), "thread: github") || i > strings.Index(string(d.bytes()), "## Round") {
		t.Fatalf("author misplaced:\n%s", d.bytes())
	}
	d.Set("thread", "https://x.slack.com/archives/C1/p1")
	if strings.Count(string(d.bytes()), "thread:") != 1 {
		t.Fatal("Set must replace in place")
	}
	d.Del("done")
	if d.Get("done") != "" || strings.Contains(string(d.bytes()), "done:") {
		t.Fatal("Del done must drop the line under the round too")
	}
	if d.Rounds() != 1 {
		t.Fatal("rounds survive")
	}
}

func TestDocFirstOccurrenceAndMultiline(t *testing.T) {
	d := parseDoc([]byte("a: 1\na: 2\nci-attempt: s1 - started\n\n## Round 1\n"))
	if d.Get("a") != "1" {
		t.Fatal("first occurrence wins")
	}
	d.Add("ci-attempt", "s2 - started")
	if got := d.All("ci-attempt"); len(got) != 2 {
		t.Fatalf("%v", got)
	}
	if !d.HasPrefix("ci-attempt: s2 ") || d.HasPrefix("ci-attempt: s3 ") {
		t.Fatal("HasPrefix")
	}
	d.DelPrefix("ci-attempt: s1 ")
	if len(d.All("ci-attempt")) != 1 {
		t.Fatal("DelPrefix")
	}
}

func TestStatusOfDoc(t *testing.T) {
	k := Key{"acme", "app", 7}
	cases := []struct {
		name, text, state, reason string
		rounds                    int
	}{
		{"running", "owner: acme\nrepo: app\nthread: github\n## Round 1\n## Round 2\n", StRunning, "", 2},
		{"paused", "owner: acme\nrepo: app\npaused: 2026-11-12T10:00:00Z - CI red\n", StPaused, "CI red", 0},
		{"paused em dash", "owner: acme\nrepo: app\npaused: 2026-09-11T10:00:00Z — round cap\n", StPaused, "round cap", 0},
		{"approved", "owner: acme\nrepo: app\ndone: 2026-11-12T10:00:00Z - approved (deep), 2 rounds\n", StApproved, "approved (deep), 2 rounds", 0},
		{"done", "owner: acme\nrepo: app\ndone: 2026-11-12T10:00:00Z - stopped from the UI\n", StDone, "stopped from the UI", 0},
		{"done under round", "owner: acme\nrepo: app\n\n## Round 1\ndone: 2026-11-12T10:00:00Z - merged\n", StDone, "merged", 1},
	}
	for _, c := range cases {
		st := StatusOfDoc(k, parseDoc([]byte(c.text)), "simple", time.Time{})
		got := ""
		if st.Reason != nil {
			got = *st.Reason
		}
		if st.State != c.state || got != c.reason || st.Rounds != c.rounds {
			t.Errorf("%s: %+v", c.name, st)
		}
		if st.Mode == nil || *st.Mode != "simple" {
			t.Errorf("%s: mode fallback", c.name)
		}
	}
	if st := StatusOfDoc(k, nil, "", time.Time{}); st.State != StNone {
		t.Fatal("none")
	}
}

func TestIndexValidity(t *testing.T) {
	e := newEnv(t)
	e.seedState()
	write := func(name, body string) {
		if err := writeFile(e.h.Path("pr-grind", name), body); err != nil {
			t.Fatal(err)
		}
	}
	write("x-y-3.md", "owner: x\nrepo: y\nnumber: 3\nthread: github\n")                             // github thread is valid
	write("x-y-4.md", "owner: x\nrepo: y\nnumber: 4\nthread: not-a-url\n")                          // invalid
	write("x-y-5.md", "owner: ..\nrepo: y\nnumber: 5\nthread: https://a.slack.com/archives/C/p1\n") // invalid owner
	write("x-y-6.md", "owner: x\nrepo: y\nnumber: 6x\nthread: github\n")                            // invalid number
	idx := Index(Files{e.h}, "deep")
	if len(idx) != 2 || idx[0].Repo != "acme/app" || idx[1].PR != 3 {
		t.Fatalf("%+v", idx)
	}
	if idx[1].Thread != nil {
		t.Fatal("thread only when https")
	}
	if k, ok := (Files{e.h}).FindByThread("https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469?x=1"); !ok || k.N != 7 {
		t.Fatal("FindByThread")
	}
}
