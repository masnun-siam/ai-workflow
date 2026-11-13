package settings

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
)

func setup(t *testing.T) (*Store, *home.Home, *events.Bus) {
	t.Helper()
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("SETU_HOME", filepath.Join(root, ".setu"))
	bin := filepath.Join(root, "bin")
	if err := os.MkdirAll(bin, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, n := range []string{"claude", "cc-profile", "other"} {
		if err := os.WriteFile(filepath.Join(bin, n), []byte("#!/bin/sh\n"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	bus := events.New()
	return Open(h, bus), h, bus
}

func write(t *testing.T, h *home.Home, name, body string) {
	t.Helper()
	if err := os.WriteFile(h.Path(name), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func save(s *Store, body string) (SettingsView, error) { return s.Save(json.RawMessage(body)) }

func wantErr(t *testing.T, err error, sub string) {
	t.Helper()
	if err == nil {
		t.Fatalf("want error containing %q, got nil", sub)
	}
	if errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("want invalid, got %v", err)
	}
	if !strings.Contains(err.Error(), sub) {
		t.Fatalf("error %q does not contain %q", err, sub)
	}
}

func TestDefaults(t *testing.T) {
	s, h, _ := setup(t)
	st := s.Get()
	if st.Default != "claude" || len(st.Commands) != 1 || !st.Commands[0].Builtin {
		t.Fatalf("%+v", st.Commands)
	}
	if st.GrindMode != "deep" || !st.UseJev || !st.IdleGuard || st.RunModel != nil {
		t.Fatalf("%+v", st)
	}
	if st.GrindLimits != (GrindLimits{10, 60, 1500, 4, 2, 1200, 30}) {
		t.Fatalf("%+v", st.GrindLimits)
	}
	if st.ReleaseNote.ChannelID != "C06RSFFRUFM" || len(st.ReleaseNote.CC) != 3 || st.ReleaseNote.Suffix != "vai" {
		t.Fatalf("%+v", st.ReleaseNote)
	}
	if st.Server.Port != 8420 || st.Server.TailscaleHTTPSPort != 443 {
		t.Fatalf("%+v", st.Server)
	}
	if !strings.HasSuffix(*st.VaultDir, "Documents/notes") {
		t.Fatal(*st.VaultDir)
	}
	// a missing file is created with seeded lists on first load
	b, err := os.ReadFile(h.Path("ui_settings.json"))
	if err != nil || !strings.Contains(string(b), `"reviewers"`) {
		t.Fatalf("not seeded: %v %s", err, b)
	}
}

func TestOldFileLoadsUnchanged(t *testing.T) {
	s, h, _ := setup(t)
	write(t, h, "ui_settings.json", `{
	  "claude_label": "main",
	  "commands": [
	    {"label": "masum", "cmd": "cc masum", "harness": "claude"},
	    {"label": "gpt", "cmd": "codex", "harness": "codex", "models": ["gpt-5"]},
	    {"label": "main", "cmd": "claude"}
	  ],
	  "default": "masum",
	  "repos": {"a/b": {"auto_grind": true, "slack_channel": "C0123ABCDE", "reviewers": ["r-00000001", "r-ffffffff"]}},
	  "slack_channels": [{"id":"C0123ABCDE","name":"x"},{"id":"bad","name":"y"}],
	  "reviewers": [{"id":"r-00000001","name":"Bot","slack_id":"U0123ABCDE","github_login":""}],
	  "active_reviewers": ["r-00000001","r-zzzz"],
	  "grind_mode": "simple", "use_jev": false, "run_model": "opus", "run_effort": "high",
	  "vault_dir": "~/v"
	}`)
	st := s.Get()
	if st.ClaudeLabel != "main" || len(st.Commands) != 2 || st.Commands[1].Label != "masum" || st.Default != "masum" {
		t.Fatalf("%+v", st.Commands)
	}
	r := st.Repos["a/b"]
	if !r.AutoGrind || r.SlackChannel != "C0123ABCDE" || len(r.Reviewers) != 1 {
		t.Fatalf("%+v", r)
	}
	if len(st.SlackChannels) != 1 || st.GrindMode != "simple" || st.UseJev || !st.IdleGuard || *st.RunModel != "opus" || *st.RunEffort != "high" {
		t.Fatalf("%+v", st)
	}
	if len(st.ActiveReviewers) != 1 {
		t.Fatalf("%+v", st.ActiveReviewers)
	}
	if !strings.HasSuffix(*st.VaultDir, "/v") || strings.HasPrefix(*st.VaultDir, "~") {
		t.Fatal(*st.VaultDir)
	}
	if st.Server.Port != 8420 {
		t.Fatal("new keys must default")
	}
	if a := s.Default(); a.Label != "masum" || a.Cmd != "cc masum" {
		t.Fatalf("%+v", a)
	}
	if _, ok := s.Account("gpt"); ok {
		t.Fatal("codex account must be dropped")
	}
}

func TestLegacyAutoGrindAndSeed(t *testing.T) {
	s, h, _ := setup(t)
	write(t, h, "checkouts.json", `{"o/one":"/x/one","o/two":"/x/two"}`)
	write(t, h, "channels.json", `{"bot_uid":"U0BOT00001","bot_label":"Helper","channels":{"o/two":"C0222222222"}}`)
	write(t, h, "ui_settings.json", `{"auto_grind": true, "repos": {"o/two": {"reviewer": "alice", "slack_channel": "C0111111111"}, "o/three": {"reviewer":"Bob"}}}`)
	st := s.Get()
	if !st.Repos["o/one"].AutoGrind {
		t.Fatalf("legacy auto_grind not seeded: %+v", st.Repos)
	}
	if st.Repos["o/two"].AutoGrind {
		t.Fatal("existing repo entries are not overwritten")
	}
	if len(st.Reviewers) != 3 || st.Reviewers[0].Name != "Helper" || st.Reviewers[0].SlackID != "U0BOT00001" {
		t.Fatalf("%+v", st.Reviewers)
	}
	if len(st.ActiveReviewers) != 1 || st.ActiveReviewers[0] != st.Reviewers[0].ID {
		t.Fatalf("%+v", st.ActiveReviewers)
	}
	if st.Repos["o/two"].Reviewers != nil { // has a channel: no override
		t.Fatalf("%+v", st.Repos["o/two"])
	}
	if r := st.Repos["o/three"].Reviewers; len(r) != 1 {
		t.Fatalf("login-only repo gets an override: %+v", st.Repos["o/three"])
	}
	if len(st.SlackChannels) != 2 {
		t.Fatalf("%+v", st.SlackChannels)
	}
	b, _ := os.ReadFile(h.Path("ui_settings.json"))
	if strings.Contains(string(b), `"auto_grind": true,`) && strings.Contains(string(b), `"reviewer":`) {
		t.Fatalf("legacy keys must be gone: %s", b)
	}
	v := s.View()
	if v.BotLabel == nil || *v.BotLabel != "Helper" {
		t.Fatal("bot_label")
	}
	if rv := v.Repos["o/two"]; rv.GrindPath == nil || *rv.GrindPath != "slack" || rv.Path == nil || *rv.Path != "/x/two" {
		t.Fatalf("%+v", rv)
	}
	if rv := v.Repos["o/three"]; *rv.GrindPath != "github" || rv.Path != nil {
		t.Fatalf("%+v", rv)
	}
}

func TestCorruptFileNeverOverwrittenByLoad(t *testing.T) {
	s, h, _ := setup(t)
	write(t, h, "ui_settings.json", `{not json`)
	_ = s.Get()
	b, _ := os.ReadFile(h.Path("ui_settings.json"))
	if string(b) != `{not json` {
		t.Fatalf("corrupt file rewritten: %s", b)
	}
	if _, err := save(s, `{"grind_mode":"simple"}`); err != nil {
		t.Fatal(err)
	}
	m, _ := filepath.Glob(h.Path("ui_settings.json.corrupt-*"))
	if len(m) != 1 || s.Get().GrindMode != "simple" {
		t.Fatalf("backup %v", m)
	}
}

func TestSaveValidation(t *testing.T) {
	long := strings.Repeat("a", 41)
	tests := []struct{ name, body, err string }{
		{"commands type", `{"commands": 3}`, "commands must be a list"},
		{"label empty", `{"commands":[{"label":" ","cmd":"other"}]}`, "label must be"},
		{"label long", `{"commands":[{"label":"` + long + `","cmd":"other"}]}`, "label must be"},
		{"dup label", `{"commands":[{"label":"a","cmd":"other"},{"label":"a","cmd":"cc x"}]}`, "duplicate label: 'a'"},
		{"label is builtin alias", `{"commands":[{"label":"claude","cmd":"other"}]}`, "duplicate label"},
		{"cmd not found", `{"commands":[{"label":"a","cmd":"nope-zzz"}]}`, "'nope-zzz' not found on PATH"},
		{"cmd empty", `{"commands":[{"label":"a","cmd":" "}]}`, "must not be empty"},
		{"cmd unparsable", `{"commands":[{"label":"a","cmd":"cc 'x"}]}`, "cannot parse command"},
		{"cmd long", `{"commands":[{"label":"a","cmd":"` + strings.Repeat("a", 201) + `"}]}`, "at most 200"},
		{"dup cmd", `{"commands":[{"label":"a","cmd":"other"},{"label":"b","cmd":"other"}]}`, "each account needs its own command"},
		{"cmd = claude", `{"commands":[{"label":"a","cmd":"claude"}]}`, "each account needs its own command"},
		{"codex", `{"commands":[{"label":"a","cmd":"other","harness":"codex"}]}`, "harness must be claude"},
		{"default unknown", `{"commands":[],"default":"zz"}`, "default must be one of the labels"},
		{"two builtins", `{"commands":[{"label":"x","cmd":"claude","builtin":true},{"label":"y","cmd":"claude","builtin":true}]}`, "only one built-in"},
		{"too many", `{"commands":[` + strings.TrimSuffix(strings.Repeat(`{"label":"a","cmd":"other"},`, 21), ",") + `]}`, "at most 20"},
		{"vault relative", `{"vault_dir":"notes"}`, "absolute"},
		{"mode", `{"grind_mode":"x"}`, "deep or simple"},
		{"jev type", `{"use_jev":"yes"}`, "wrong type"},
		{"idle guard type", `{"idle_guard":"yes"}`, "wrong type"},
		{"model", `{"run_model":"gpt"}`, "model must be one of opus, sonnet, haiku"},
		{"effort", `{"run_effort":"ultra"}`, "effort must be one of low, medium, high, xhigh, max"},
		{"channel id", `{"slack_channels":[{"id":"x","name":"n"}]}`, "channel id must look like"},
		{"channel name", `{"slack_channels":[{"id":"C0123ABCDE","name":""}]}`, "1 to 60"},
		{"channel dup", `{"slack_channels":[{"id":"C0123ABCDE","name":"a"},{"id":"C0123ABCDE","name":"b"}]}`, "already listed"},
		{"reviewer name", `{"reviewers":[{"name":"","github_login":"a"}]}`, "reviewer name"},
		{"reviewer none", `{"reviewers":[{"name":"n"}]}`, "add a Slack id or a GitHub login"},
		{"reviewer slack", `{"reviewers":[{"name":"n","slack_id":"x"}]}`, "Slack id must look like"},
		{"reviewer login", `{"reviewers":[{"name":"n","github_login":"a b"}]}`, "not a GitHub login"},
		{"reviewer dup slack", `{"reviewers":[{"name":"a","slack_id":"U0123ABCDE"},{"name":"b","slack_id":"U0123ABCDE"}]}`, "already listed"},
		{"reviewer dup login", `{"reviewers":[{"name":"a","github_login":"Al"},{"name":"b","github_login":"al"}]}`, "login al is already listed"},
		{"reviewer id", `{"reviewers":[{"id":"zz","name":"a","github_login":"al"}]}`, "r-<8 hex>"},
		{"active unknown", `{"active_reviewers":["r-00000000"]}`, "unknown reviewer id"},
		{"active type", `{"active_reviewers":"x"}`, "list of ids"},
		{"repo key", `{"repos":{"bad":{}}}`, "owner/repo"},
		{"repo value", `{"repos":{"a/b":3}}`, "owner/repo"},
		{"repo channel unlisted", `{"repos":{"a/b":{"slack_channel":"C0123ABCDE"}}}`, "not a listed channel"},
		{"repo reviewers", `{"repos":{"a/b":{"reviewers":["r-00000000"]}}}`, "unknown reviewer id"},
		{"repo branch", `{"repos":{"a/b":{"release_head":"a b"}}}`, "branch name"},
		{"limits key", `{"grind_limits":{"zz":1}}`, "unknown grind_limits key"},
		{"limits value", `{"grind_limits":{"max_rounds":0}}`, "whole number"},
		{"release channel", `{"release_note":{"channel_id":"x"}}`, "channel_id"},
		{"release cc", `{"release_note":{"cc":[{"name":"a","slack_id":"x"}]}}`, "cc"},
		{"server port", `{"server":{"port":70000}}`, "port"},
		{"server https", `{"server":{"tailscale_https_port":444}}`, "443, 8443 or 10000"},
		{"server host", `{"server":{"allow_hosts":["a b"]}}`, "invalid host"},
		{"not object", `[1]`, "JSON object"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s, _, _ := setup(t)
			_, err := save(s, tc.body)
			wantErr(t, err, tc.err)
		})
	}
}

func TestSaveRoundTripAndPartial(t *testing.T) {
	s, h, bus := setup(t)
	ch, cancel := bus.Subscribe(8)
	defer cancel()
	v, err := save(s, `{
	  "commands":[{"label":"Main","cmd":"claude","builtin":true},{"label":"masum","cmd":" cc masum "}],
	  "default":"masum",
	  "slack_channels":[{"id":"C0123ABCDE","name":" dev "}],
	  "reviewers":[{"name":"Bot","slack_id":"U0123ABCDE"},{"name":"Al","github_login":"al"}],
	  "vault_dir":"~/vault","grind_mode":"simple","use_jev":false,"idle_guard":false,"run_model":"sonnet","run_effort":"low",
	  "repos":{"o/r":{"auto_grind":true,"slack_channel":"C0123ABCDE","release_head":"dev"}},
	  "grind_limits":{"max_rounds":5},"release_note":{"suffix":"x"},"server":{"port":9000,"allow_hosts":["Box.ts.net"]}
	}`)
	if err != nil {
		t.Fatal(err)
	}
	if v.ClaudeLabel != "Main" || v.Default != "masum" || len(v.Commands) != 2 || v.Commands[1].Cmd != "cc masum" {
		t.Fatalf("%+v", v.Settings)
	}
	if len(v.Reviewers) != 2 || !reviewerIDRE.MatchString(v.Reviewers[0].ID) || v.SlackChannels[0].Name != "dev" {
		t.Fatalf("%+v", v.Reviewers)
	}
	if v.GrindLimits.MaxRounds != 5 || v.GrindLimits.CIPoll != 30 || v.ReleaseNote.Suffix != "x" || v.ReleaseNote.ChannelID != "C06RSFFRUFM" {
		t.Fatalf("%+v %+v", v.GrindLimits, v.ReleaseNote)
	}
	if v.Server.Port != 9000 || v.Server.AllowHosts[0] != "box.ts.net" || !v.Server.Tailscale {
		t.Fatalf("%+v", v.Server)
	}
	if rv := v.Repos["o/r"]; !rv.AutoGrind || rv.ReleaseHead != "dev" || rv.ChannelInvalid {
		t.Fatalf("%+v", rv)
	}
	select {
	case e := <-ch:
		if e.Topic != events.TUsage {
			t.Fatalf("%+v", e)
		}
	default:
		t.Fatal("no usage event")
	}
	// disk: default stored, builtin not stored
	b, _ := os.ReadFile(h.Path("ui_settings.json"))
	var disk map[string]any
	_ = json.Unmarshal(b, &disk)
	if disk["default"] != "masum" || len(disk["commands"].([]any)) != 1 || disk["claude_label"] != "Main" || disk["idle_guard"] != false {
		t.Fatalf("%s", b)
	}

	// a partial save keeps every omitted key, accounts included
	v, err = save(s, `{"repos":{"o/r":{"auto_grind":false,"slack_channel":"C0123ABCDE"},"x/y":{"auto_grind":true}}}`)
	if err != nil {
		t.Fatal(err)
	}
	if v.Default != "masum" || len(v.Commands) != 2 || v.GrindMode != "simple" || v.UseJev || v.IdleGuard || len(v.Reviewers) != 2 || *v.RunModel != "sonnet" {
		t.Fatalf("%+v", v.Settings)
	}
	if v.Repos["o/r"].AutoGrind || !v.Repos["x/y"].AutoGrind || v.Repos["o/r"].ReleaseHead != "dev" {
		t.Fatalf("%+v", v.Repos)
	}
	if !strings.HasSuffix(*v.VaultDir, "/vault") {
		t.Fatal(*v.VaultDir)
	}
	// reviewers kept on a per-repo save; override kept minus removed reviewers
	id := v.Reviewers[0].ID
	if _, err = save(s, `{"repos":{"o/r":{"reviewers":["`+id+`"],"slack_channel":""}}}`); err != nil {
		t.Fatal(err)
	}
	v, err = save(s, `{"repos":{"o/r":{"slack_channel":""}},"reviewers":[{"name":"Al","github_login":"al"}]}`)
	if err != nil {
		t.Fatal(err)
	}
	if got := v.Repos["o/r"].Reviewers; got == nil || len(got) != 0 {
		t.Fatalf("override should survive empty: %#v", got)
	}
	// clearing values
	v, err = save(s, `{"run_model":null,"vault_dir":"","default":null,"commands":[{"label":"Main","cmd":"claude","builtin":true}]}`)
	if err != nil {
		t.Fatal(err)
	}
	if v.RunModel != nil || v.Default != "Main" || len(v.Commands) != 1 {
		t.Fatalf("%+v", v.Settings)
	}
}

func TestChannelRules(t *testing.T) {
	s, _, _ := setup(t)
	if _, err := save(s, `{"slack_channels":[{"id":"C0123ABCDE","name":"a"}],"repos":{"o/r":{"slack_channel":"C0123ABCDE"}}}`); err != nil {
		t.Fatal(err)
	}
	_, err := save(s, `{"slack_channels":[]}`)
	wantErr(t, err, "channel C0123ABCDE is used by o/r")
	// an unchanged legacy channel that was never listed stays allowed
	s2, h2, _ := setup(t)
	write(t, h2, "ui_settings.json", `{"reviewers":[],"repos":{"o/r":{"slack_channel":"CLEGACY123"}}}`)
	v, err := save(s2, `{"repos":{"o/r":{"slack_channel":"CLEGACY123"}}}`)
	if err != nil || !v.Repos["o/r"].ChannelInvalid {
		t.Fatalf("%v %+v", err, v.Repos)
	}
}

func TestCacheFollowsMtime(t *testing.T) {
	s, h, _ := setup(t)
	_ = s.Get()
	write(t, h, "ui_settings.json", `{"reviewers":[],"grind_mode":"simple","claude_label":"zzzz-longer-label"}`)
	if got := s.Get(); got.GrindMode != "simple" || got.ClaudeLabel != "zzzz-longer-label" {
		t.Fatalf("%+v", got)
	}
}

func TestCheckRun(t *testing.T) {
	s, _, _ := setup(t)
	for _, tc := range []struct {
		m, e string
		ok   bool
	}{{"", "", true}, {"opus", "max", true}, {"haiku", "xhigh", true}, {"gpt", "", false}, {"", "ultra", false}} {
		if err := s.CheckRun(tc.m, tc.e); (err == nil) != tc.ok {
			t.Fatalf("%v: %v", tc, err)
		}
	}
}

func TestIssueGrind(t *testing.T) {
	s, h, _ := setup(t)
	write(t, h, "issue_grind.json", `{"o/r":{"7":true}}`)
	if on, set := s.IssueGrind("O/R", 7); !on || !set {
		t.Fatal("legacy file")
	}
	if _, set := s.IssueGrind("o/r", 8); set {
		t.Fatal("unset")
	}
	if err := s.SetIssueGrind("O/R", 8, false); err != nil {
		t.Fatal(err)
	}
	if on, set := s.IssueGrind("o/r", 8); on || !set {
		t.Fatal("explicit off")
	}
	if on, _ := s.IssueGrind("o/r", 7); !on {
		t.Fatal("other issue kept")
	}
	if s.SetIssueGrind("bad", 1, true) == nil || s.SetIssueGrind("o/r", 0, true) == nil {
		t.Fatal("validation")
	}
}

func TestNotifyMode(t *testing.T) {
	s, h, _ := setup(t)
	write(t, h, "ui.json", `{"ntfy":{"server":"https://n.example","topic":"t","token":"k"},"public_url":"https://p","channels":{"done":{"mac":false}}}`)
	if c := s.Notify(); c.Ntfy.Topic != "" || c.PublicURL != "" {
		t.Fatalf("0644 ui.json must be ignored: %+v", c)
	}
	if err := os.Chmod(h.Path("ui.json"), 0o600); err != nil {
		t.Fatal(err)
	}
	c := s.Notify()
	if c.Ntfy.Topic != "t" || c.Ntfy.Token != "k" || c.PublicURL != "https://p" || c.Channels["done"]["mac"] {
		t.Fatalf("%+v", c)
	}
	c.Channels["done"]["push"] = true
	if err := s.SaveNotify(c); err != nil {
		t.Fatal(err)
	}
	fi, _ := os.Stat(h.Path("ui.json"))
	if fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode())
	}
	if !s.Notify().Channels["done"]["push"] {
		t.Fatal("not saved")
	}
	if _, err := s.UpdateNotify(func(c *NotifyConfig) error { c.PublicURL = ""; return nil }); err != nil || s.Notify().PublicURL != "" {
		t.Fatal(err)
	}
}

func TestSplitAndResolve(t *testing.T) {
	for in, want := range map[string]string{
		`a b  c`: "a|b|c", `a "b c" d`: "a|b c|d", `a 'b "c"' d`: "a|b \"c\"|d", `a\ b c`: "a b|c", `"a\"b" c`: `a"b|c`, `x ""`: "x|", ``: "",
	} {
		got, err := Split(in)
		if err != nil || strings.Join(got, "|") != want {
			t.Errorf("%q: %v %v", in, got, err)
		}
	}
	for _, in := range []string{`a "b`, `a 'b`, `a\`} {
		if _, err := Split(in); err == nil {
			t.Errorf("%q should fail", in)
		}
	}
	setup(t)
	argv, err := ResolveCmd("cc masum --x")
	if err != nil || filepath.Base(argv[0]) != "cc-profile" || !filepath.IsAbs(argv[0]) || argv[1] != "masum" || argv[2] != "--x" {
		t.Fatalf("%v %v", argv, err)
	}
	if _, err := ResolveCmd("zzz-nope"); err == nil || err.Error() != "'zzz-nope' not found on PATH" {
		t.Fatal(err)
	}
}

func TestRoutes(t *testing.T) {
	s, _, _ := setup(t)
	mux := http.NewServeMux()
	for _, r := range Routes(Deps{Store: s}) {
		mux.Handle(r.Pattern, r.Handler)
	}
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("GET", "/api/settings", nil))
	var v map[string]any
	if rec.Code != 200 || json.Unmarshal(rec.Body.Bytes(), &v) != nil || v["grind_mode"] != "deep" || v["bot_label"] != nil {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	req := httptest.NewRequest("PUT", "/api/settings", strings.NewReader(`{"grind_mode":"simple"}`))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"simple"`) {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
	req = httptest.NewRequest("PUT", "/api/settings", strings.NewReader(`{"grind_mode":"x"}`))
	req.Header.Set("Content-Type", "application/json")
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != 400 || !strings.Contains(rec.Body.String(), "deep or simple") {
		t.Fatalf("%d %s", rec.Code, rec.Body)
	}
}

func TestIdleGuardOverHTTP(t *testing.T) {
	s, h, _ := setup(t)
	mux := http.NewServeMux()
	for _, r := range Routes(Deps{Store: s}) {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(method, body string) (int, map[string]any) {
		t.Helper()
		req := httptest.NewRequest(method, "/api/settings", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		var v map[string]any
		_ = json.Unmarshal(rec.Body.Bytes(), &v)
		return rec.Code, v
	}
	if code, v := do("GET", ""); code != 200 || v["idle_guard"] != true {
		t.Fatalf("fresh home: %d %v", code, v["idle_guard"])
	}
	if code, v := do("PUT", `{"idle_guard":false}`); code != 200 || v["idle_guard"] != false {
		t.Fatalf("save off: %d %v", code, v)
	}
	if code, v := do("PUT", `{"grind_mode":"simple"}`); code != 200 || v["idle_guard"] != false {
		t.Fatalf("partial save must keep it: %d %v", code, v["idle_guard"])
	}
	before, _ := os.ReadFile(h.Path("ui_settings.json"))
	code, v := do("PUT", `{"idle_guard":"yes"}`)
	if code != 400 || !strings.Contains(v["error"].(string), "wrong type") {
		t.Fatalf("wrong type: %d %v", code, v)
	}
	if after, _ := os.ReadFile(h.Path("ui_settings.json")); string(after) != string(before) {
		t.Fatal("a rejected save wrote the file")
	}
	if code, v := do("GET", ""); code != 200 || v["idle_guard"] != false || s.Get().IdleGuard {
		t.Fatalf("after reject: %d %v", code, v["idle_guard"])
	}
}
