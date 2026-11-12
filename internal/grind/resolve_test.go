package grind

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/masnun-siam/setu/internal/settings"
)

func TestResolveTable(t *testing.T) {
	revs := []settings.Reviewer{
		{ID: "r-00000001", Name: "A", SlackID: "UAAAAAAAA1", GithubLogin: "aaa"},
		{ID: "r-00000002", Name: "B", SlackID: "UBBBBBBBB2", GithubLogin: ""},
		{ID: "r-00000003", Name: "C", SlackID: "", GithubLogin: "ccc"},
	}
	st := func(repos map[string]settings.RepoSettings, active ...string) settings.Settings {
		return settings.Settings{Reviewers: revs, ActiveReviewers: active, Repos: repos,
			SlackChannels: []settings.Channel{{ID: "C0AAAAAAAA", Name: "x"}}}
	}
	ch := Channels{Channels: map[string]string{"Acme/Mapped": "C0MAPPED01"}, BotUID: "UBOT"}
	cases := []struct {
		name      string
		st        settings.Settings
		ch        Channels
		checkouts map[string]string
		repo      string
		want      Reviewers
	}{
		{"unknown repo: empty, no skip", st(nil, "r-00000001"), Channels{}, nil, "acme/none",
			Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}}},
		{"invalid channel", st(map[string]settings.RepoSettings{"acme/app": {SlackChannel: "C0ZZZZZZZZ"}}, "r-00000001"), ch, nil, "acme/app",
			Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}, Skip: strp("invalid Slack channel C0ZZZZZZZZ, pick a channel in Settings")}},
		{"slack via stored channel", st(map[string]settings.RepoSettings{"acme/app": {SlackChannel: "C0AAAAAAAA"}}, "r-00000001", "r-00000002"), ch, nil, "ACME/app",
			Reviewers{Path: strp("slack"), Channel: strp("C0AAAAAAAA"), Mentions: []string{"UAAAAAAAA1", "UBBBBBBBB2"}, Logins: []string{"aaa"}, Unlogged: []string{"UBBBBBBBB2"}}},
		{"slack via channels.json map (case-insensitive), no stored channel", st(map[string]settings.RepoSettings{"acme/mapped": {}}, "r-00000001"), ch, nil, "acme/mapped",
			Reviewers{Path: strp("slack"), Mentions: []string{"UAAAAAAAA1"}, Logins: []string{"aaa"}, Unlogged: []string{}}},
		{"slack, no mentions but bot_uid: usable", st(map[string]settings.RepoSettings{"acme/mapped": {}}, "r-00000003"), ch, nil, "acme/mapped",
			Reviewers{Path: strp("slack"), Mentions: []string{}, Logins: []string{"ccc"}, Unlogged: []string{}}},
		{"slack, no mentions and no bot_uid: skip", st(map[string]settings.RepoSettings{"acme/mapped": {}}, "r-00000003"), Channels{Channels: ch.Channels}, nil, "acme/mapped",
			Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}, Skip: strp(NoReviewer)}},
		{"github path from a checkout", st(nil, "r-00000001", "r-00000003"), ch, map[string]string{"acme/co": "/x"}, "acme/co",
			Reviewers{Path: strp("github"), Mentions: []string{"UAAAAAAAA1"}, Logins: []string{"aaa", "ccc"}, Unlogged: []string{}}},
		{"github path without logins: skip", st(map[string]settings.RepoSettings{"acme/g": {}}, "r-00000002"), ch, nil, "acme/g",
			Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}, Skip: strp(NoReviewer)}},
		{"repo override beats the active list", st(map[string]settings.RepoSettings{"acme/g": {Reviewers: []string{"r-00000003"}}}, "r-00000001"), ch, nil, "acme/g",
			Reviewers{Path: strp("github"), Mentions: []string{}, Logins: []string{"ccc"}, Unlogged: []string{}}},
		{"empty override is a real empty set", st(map[string]settings.RepoSettings{"acme/g": {Reviewers: []string{}}}, "r-00000001"), ch, nil, "acme/g",
			Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}, Skip: strp(NoReviewer)}},
	}
	for _, c := range cases {
		got := Resolve(c.st, c.ch, c.checkouts, c.repo)
		if !reflect.DeepEqual(got, c.want) {
			g, _ := json.Marshal(got)
			w, _ := json.Marshal(c.want)
			t.Errorf("%s:\n got %s\nwant %s", c.name, g, w)
		}
	}
}

func TestReviewersVerb(t *testing.T) {
	e := newEnv(t)
	e.writeJSON("ui_settings.json", map[string]any{
		"reviewers":        []any{map[string]string{"id": "r-00000001", "name": "A", "slack_id": "UAAAAAAAA1", "github_login": "aaa"}},
		"active_reviewers": []any{"r-00000001"},
		"slack_channels":   []any{},
	})
	code, out, _ := e.run("grind-reviewers", "--pr", testPR)
	m := jsonOf(t, out)
	// acme/app is mapped in channels.json, so the slack path
	if code != 0 || m["path"] != "slack" || m["channel"] != nil || m["skip"] != nil || len(m["mentions"].([]any)) != 1 {
		t.Fatalf("%d %s", code, out)
	}
	// not a PR url: empty answer
	if code, out, _ := e.run("grind", "reviewers", "--pr", "nope"); code != 0 || jsonOf(t, out)["path"] != nil {
		t.Fatal(out)
	}
	// --strict with unreadable settings: {"error"} and exit 1
	if err := writeFile(e.h.Path("ui_settings.json"), "{not json"); err != nil {
		t.Fatal(err)
	}
	code, out, _ = e.run("grind-reviewers", "--pr", testPR, "--strict")
	if code != 1 || jsonOf(t, out)["error"] == nil {
		t.Fatalf("%d %s", code, out)
	}
	if code, _, _ := e.run("grind-reviewers", "--pr", testPR); code != 0 {
		t.Fatal("lenient mode must not fail")
	}
	if code, _, _ := e.run("grind-reviewers"); code != 64 {
		t.Fatal("--pr is required")
	}
}

func TestGrindModeDispatchOverride(t *testing.T) {
	e := newEnv(t)
	code, out, _ := e.run("grind-mode")
	if code != 0 || out != "deep\n" {
		t.Fatalf("default: %d %q", code, out)
	}
	e.writeJSON("ui_settings.json", map[string]any{"grind_mode": "simple", "reviewers": []any{}})
	if _, out, _ := e.run("grind-mode", "--pr", testPR); out != "simple\n" {
		t.Fatalf("settings: %q", out)
	}
	disp := func(state, grind string, pr int) {
		if err := writeFile(e.h.Path("dispatches", "abc123abc123.json"), ""); err != nil {
			_ = osMkdir(e.h.Path("dispatches"))
		}
		e.writeJSON("dispatches/abc123abc123.json", map[string]any{"state": state, "settings": map[string]any{"grind": grind},
			"lanes": map[string]any{"acme/app#1": map[string]any{"repo": "Acme/App", "pr": pr}}})
	}
	disp("running", "full", 7)
	if _, out, _ := e.run("grind", "mode", "--pr", testPR); out != "deep\n" {
		t.Fatalf("running dispatch with full grind is deep: %q", out)
	}
	disp("paused", "simple", 7)
	e.writeJSON("ui_settings.json", map[string]any{"grind_mode": "deep", "reviewers": []any{}})
	if _, out, _ := e.run("grind-mode", "--pr", testPR); out != "simple\n" {
		t.Fatalf("dispatch overrides settings: %q", out)
	}
	disp("done", "simple", 7)
	if _, out, _ := e.run("grind-mode", "--pr", testPR); out != "deep\n" {
		t.Fatalf("a finished dispatch does not own the PR: %q", out)
	}
	disp("running", "simple", 8)
	if _, out, _ := e.run("grind-mode", "--pr", testPR); out != "deep\n" {
		t.Fatalf("another PR: %q", out)
	}
	// a pinned mode in the state file sits between the dispatch and Settings
	e.seedState("mode: simple")
	if _, out, _ := e.run("grind-mode", "--pr", testPR); out != "simple\n" {
		t.Fatalf("pin: %q", out)
	}
}
