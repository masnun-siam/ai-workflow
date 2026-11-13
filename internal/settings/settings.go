// Package settings owns ui_settings.json, issue_grind.json and ui.json (the notification
// matrix, ntfy and public_url). The on-disk key names are the API names (D13), so a migrated
// data dir is read as is.
package settings

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io/fs"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
)

const (
	DefaultCmd   = "claude"
	DefaultVault = "~/Documents/notes"
	MaxCommands  = 20
	MaxListed    = 50
	settingsFile = "ui_settings.json"
)

var (
	slugRE       = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	loginRE      = regexp.MustCompile(`^[A-Za-z0-9-]{1,39}$`)
	channelRE    = regexp.MustCompile(`^[CGD][A-Z0-9]{8,12}$`)
	slackIDRE    = regexp.MustCompile(`^[UW][A-Z0-9]{8,12}$`)
	reviewerIDRE = regexp.MustCompile(`^r-[0-9a-f]{8}$`)
	branchRE     = regexp.MustCompile(`^[A-Za-z0-9._/-]{1,200}$`)
	hostRE       = regexp.MustCompile(`^[A-Za-z0-9.:\[\]-]{1,253}$`)
)

var (
	RunModels  = []string{"opus", "sonnet", "haiku"}
	RunEfforts = []string{"low", "medium", "high", "xhigh", "max"}
)

type Account struct {
	Label   string `json:"label"`
	Cmd     string `json:"cmd"`
	Builtin bool   `json:"builtin,omitempty"`
}

type Channel struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type Reviewer struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	SlackID     string `json:"slack_id"`
	GithubLogin string `json:"github_login"`
}

// RepoSettings is one repos entry. Reviewers nil = no override (JSON null).
type RepoSettings struct {
	AutoGrind    bool     `json:"auto_grind"`
	SlackChannel string   `json:"slack_channel"`
	Reviewers    []string `json:"reviewers"`
	ReleaseHead  string   `json:"release_head,omitempty"`
	ReleaseBase  string   `json:"release_base,omitempty"`
}

type GrindLimits struct {
	MaxRounds    int `json:"max_rounds"`
	PollInterval int `json:"poll_interval"`
	MaxWait      int `json:"max_wait"`
	MaxIdleWaits int `json:"max_idle_waits"`
	StuckSeen    int `json:"stuck_seen"`
	CITimeout    int `json:"ci_timeout"`
	CIPoll       int `json:"ci_poll"`
}

type CC struct {
	Name    string `json:"name"`
	SlackID string `json:"slack_id"`
}

type ReleaseNote struct {
	ChannelName string `json:"channel_name"`
	ChannelID   string `json:"channel_id"`
	CC          []CC   `json:"cc"`
	Suffix      string `json:"suffix"`
}

type ServerSettings struct {
	Port               int      `json:"port"`
	Tailscale          bool     `json:"tailscale"`
	TailscaleHTTPSPort int      `json:"tailscale_https_port"`
	AllowHosts         []string `json:"allow_hosts"`
}

// Settings is the normalized settings (API §4). Commands lists the built-in account first.
type Settings struct {
	ClaudeLabel     string                  `json:"claude_label"`
	Commands        []Account               `json:"commands"`
	Default         string                  `json:"default"`
	Repos           map[string]RepoSettings `json:"repos"`
	SlackChannels   []Channel               `json:"slack_channels"`
	Reviewers       []Reviewer              `json:"reviewers"`
	ActiveReviewers []string                `json:"active_reviewers"`
	VaultDir        *string                 `json:"vault_dir"`
	GrindMode       string                  `json:"grind_mode"`
	UseJev          bool                    `json:"use_jev"`
	IdleGuard       bool                    `json:"idle_guard"`
	RunModel        *string                 `json:"run_model"`
	RunEffort       *string                 `json:"run_effort"`
	GrindLimits     GrindLimits             `json:"grind_limits"`
	ReleaseNote     ReleaseNote             `json:"release_note"`
	Server          ServerSettings          `json:"server"`
}

// Repo returns the settings of slug (case-insensitive), the zero value when unknown.
func (s Settings) Repo(slug string) RepoSettings {
	if r, ok := s.Repos[slug]; ok {
		return r
	}
	for k, r := range s.Repos {
		if strings.EqualFold(k, slug) {
			return r
		}
	}
	return RepoSettings{}
}

// RepoView is a repos entry in the GET shape.
type RepoView struct {
	RepoSettings
	Path           *string `json:"path,omitempty"`
	GrindPath      *string `json:"grind_path,omitempty"`
	ChannelInvalid bool    `json:"channel_invalid"`
}

// SettingsView is the GET /api/settings shape.
type SettingsView struct {
	Settings
	Repos        map[string]RepoView `json:"repos"`
	JevInstalled bool                `json:"jev_installed"`
	BotLabel     *string             `json:"bot_label"`
}

type NtfyConfig struct {
	Server   string `json:"server,omitempty"`
	Topic    string `json:"topic,omitempty"`
	Token    string `json:"token,omitempty"`
	User     string `json:"user,omitempty"`
	Password string `json:"password,omitempty"`
}

// NotifyConfig is ui.json. Channels maps event -> channel -> on (only the cells that are set).
type NotifyConfig struct {
	Ntfy      NtfyConfig                 `json:"ntfy"`
	PublicURL string                     `json:"public_url,omitempty"`
	Channels  map[string]map[string]bool `json:"channels,omitempty"`
}

type Store struct {
	h   *home.Home
	bus *events.Bus

	mu     sync.Mutex
	cur    *loaded
	key    fileKey
	warned time.Time
}

type fileKey struct {
	mod    int64
	size   int64
	exists bool
}

func Open(h *home.Home, bus *events.Bus) *Store { return &Store{h: h, bus: bus} }

func (s *Store) path() string { return s.h.Path(settingsFile) }

func (s *Store) key0() fileKey {
	fi, err := os.Stat(s.path())
	if err != nil {
		return fileKey{}
	}
	return fileKey{fi.ModTime().UnixNano(), fi.Size(), true}
}

// Get returns the normalized settings, re-read when the file changes.
func (s *Store) Get() Settings { return s.get().Settings }

func (s *Store) get() *loaded {
	s.mu.Lock()
	defer s.mu.Unlock()
	k := s.key0()
	if s.cur != nil && s.key == k {
		return s.cur
	}
	raw, exists, corrupt := s.readRaw()
	if !corrupt && (!exists || raw["reviewers"] == nil || raw["auto_grind"] != nil) {
		if r, ok := s.migrateOnDisk(); ok {
			raw = r
		}
	}
	s.cur = normalize(raw)
	s.key = s.key0()
	return s.cur
}

func (s *Store) readRaw() (raw map[string]any, exists, corrupt bool) {
	b, err := os.ReadFile(s.path())
	if err != nil {
		return map[string]any{}, !errors.Is(err, fs.ErrNotExist), !errors.Is(err, fs.ErrNotExist)
	}
	if len(strings.TrimSpace(string(b))) == 0 {
		return map[string]any{}, true, false
	}
	if err := json.Unmarshal(b, &raw); err != nil || raw == nil {
		return map[string]any{}, true, true
	}
	return raw, true, false
}

// migrateOnDisk runs the first-load migration under the file lock. It never touches a corrupt file.
func (s *Store) migrateOnDisk() (map[string]any, bool) {
	unlock, err := home.Lock(s.path())
	if err != nil {
		return nil, false
	}
	defer unlock()
	raw, _, corrupt := s.readRaw()
	if corrupt {
		return nil, false
	}
	if raw["reviewers"] != nil && raw["auto_grind"] == nil {
		return raw, true
	}
	s.migrate(raw)
	if err := home.WriteJSON(s.path(), raw); err != nil {
		log.Printf("settings: cannot write %s: %v", settingsFile, err)
	}
	return jsonNorm(raw), true
}

// migrate is the one-time S§4.1 migration on a raw map (no I/O except reading checkouts/channels).
func (s *Store) migrate(raw map[string]any) {
	if v, ok := raw["auto_grind"]; ok {
		delete(raw, "auto_grind")
		legacy := v == true
		repos, _ := raw["repos"].(map[string]any)
		if repos == nil {
			repos = map[string]any{}
		}
		for slug := range s.checkouts() {
			if _, ok := repos[slug]; !ok {
				repos[slug] = map[string]any{"auto_grind": legacy}
			}
		}
		raw["repos"] = repos
	}
	if raw["reviewers"] == nil {
		s.seedReviewers(raw)
	}
}

func (s *Store) checkouts() map[string]string {
	m := map[string]string{}
	_ = home.ReadJSON(s.h.Path("checkouts.json"), &m)
	return m
}

type channelsJSON struct {
	Channels map[string]string `json:"channels"`
	BotUID   string            `json:"bot_uid"`
	BotLabel string            `json:"bot_label"`
}

func (s *Store) channelsJSON() channelsJSON {
	var c channelsJSON
	b, err := os.ReadFile(s.h.Path("channels.json"))
	if err != nil {
		return c
	}
	var m map[string]any
	if json.Unmarshal(b, &m) != nil {
		return c
	}
	if ch, ok := m["channels"].(map[string]any); ok {
		c.Channels = map[string]string{}
		for k, v := range ch {
			if id, ok := v.(string); ok {
				c.Channels[k] = id
			}
		}
	}
	c.BotUID, _ = m["bot_uid"].(string)
	c.BotLabel, _ = m["bot_label"].(string)
	return c
}

func newReviewerID(taken map[string]bool) string {
	for {
		var b [4]byte
		_, _ = rand.Read(b[:])
		id := "r-" + hex.EncodeToString(b[:])
		if !taken[id] {
			taken[id] = true
			return id
		}
	}
}

// seedReviewers seeds slack_channels, reviewers and active_reviewers from the old settings
// and channels.json, and drops each repo's old `reviewer`.
func (s *Store) seedReviewers(raw map[string]any) {
	cj := s.channelsJSON()
	repos := map[string]map[string]any{}
	if rm, ok := raw["repos"].(map[string]any); ok {
		for k, v := range rm {
			if m, ok := v.(map[string]any); ok {
				repos[k] = m
			}
		}
	}
	chans := []map[string]any{}
	revs := []map[string]any{}
	taken := map[string]bool{}
	addChannel := func(id string) {
		id = strings.TrimSpace(id)
		if !channelRE.MatchString(id) || len(chans) >= MaxListed {
			return
		}
		for _, c := range chans {
			if c["id"] == id {
				return
			}
		}
		chans = append(chans, map[string]any{"id": id, "name": id})
	}
	addReviewer := func(name, sid, login string) string {
		id := newReviewerID(taken)
		revs = append(revs, map[string]any{"id": id, "name": name, "slack_id": sid, "github_login": login})
		return id
	}
	keys := sortedKeys(repos)
	for _, k := range keys {
		ch, _ := repos[k]["slack_channel"].(string)
		addChannel(ch)
	}
	for _, k := range sortedKeys(cj.Channels) {
		addChannel(cj.Channels[k])
	}
	active := []any{}
	if slackIDRE.MatchString(cj.BotUID) {
		label := strings.TrimSpace(cj.BotLabel)
		if r := []rune(label); len(r) > 60 {
			label = strings.TrimSpace(string(r[:60]))
		}
		if label == "" {
			label = "Review bot"
		}
		active = append(active, addReviewer(label, cj.BotUID, ""))
	}
	for _, k := range keys {
		r := repos[k]
		login, _ := r["reviewer"].(string)
		login = strings.TrimSpace(login)
		delete(r, "reviewer")
		var rid string
		if loginRE.MatchString(login) {
			for _, x := range revs {
				if strings.EqualFold(x["github_login"].(string), login) {
					rid = x["id"].(string)
				}
			}
			if rid == "" && len(revs) < MaxListed {
				rid = addReviewer(login, "", login)
			}
		}
		ch, _ := r["slack_channel"].(string)
		hasChannel := strings.TrimSpace(ch) != "" || cj.Channels[k] != ""
		if rid != "" && !hasChannel {
			r["reviewers"] = []any{rid}
		} else {
			r["reviewers"] = nil
		}
	}
	if len(repos) > 0 {
		out := map[string]any{}
		for k, v := range repos {
			out[k] = v
		}
		raw["repos"] = out
	}
	raw["slack_channels"], raw["reviewers"], raw["active_reviewers"] = chans, revs, active
}

// ---------- normalization ----------

type loaded struct {
	Settings
	vaultRaw string // the stored vault_dir, "" = unset
}

func normalize(raw map[string]any) *loaded {
	l := &loaded{}
	st := &l.Settings
	alias, _ := raw["claude_label"].(string)
	alias = strings.TrimSpace(alias)
	if alias == "" {
		alias = DefaultCmd
	}
	st.ClaudeLabel = alias
	st.Commands = []Account{{Label: alias, Cmd: DefaultCmd, Builtin: true}}
	seen := map[string]bool{alias: true}
	if list, ok := raw["commands"].([]any); ok {
		for _, e := range list {
			m, ok := e.(map[string]any)
			if !ok {
				continue
			}
			label, ok1 := m["label"].(string)
			cmd, ok2 := m["cmd"].(string)
			if !ok1 || !ok2 || label == "" || seen[label] {
				continue
			}
			if h, _ := m["harness"].(string); h != "" && h != "claude" {
				continue // codex accounts are dropped
			}
			seen[label] = true
			st.Commands = append(st.Commands, Account{Label: label, Cmd: cmd})
		}
	}
	st.Default = alias
	if d, _ := raw["default"].(string); seen[d] {
		st.Default = d
	}
	st.SlackChannels = channelsOf(raw["slack_channels"])
	st.Reviewers = reviewersOf(raw["reviewers"])
	rids := map[string]bool{}
	for _, r := range st.Reviewers {
		rids[r.ID] = true
	}
	st.ActiveReviewers = known(raw["active_reviewers"], rids)
	st.Repos = map[string]RepoSettings{}
	if rm, ok := raw["repos"].(map[string]any); ok {
		for slug, v := range rm {
			r := repoOf(v)
			if r.Reviewers != nil {
				r.Reviewers = known(r.Reviewers, rids)
			}
			st.Repos[slug] = r
		}
	}
	vault := DefaultVault
	if v, _ := raw["vault_dir"].(string); v != "" {
		vault = v
		l.vaultRaw = v
	}
	vault = expandHome(vault)
	st.VaultDir = &vault
	st.GrindMode = "deep"
	if m, _ := raw["grind_mode"].(string); m == "simple" || m == "deep" {
		st.GrindMode = m
	}
	st.UseJev = true
	if b, ok := raw["use_jev"].(bool); ok {
		st.UseJev = b
	}
	st.IdleGuard = true
	if b, ok := raw["idle_guard"].(bool); ok {
		st.IdleGuard = b
	}
	if m, _ := raw["run_model"].(string); contains(RunModels, m) {
		st.RunModel = &m
	}
	if e, _ := raw["run_effort"].(string); contains(RunEfforts, e) {
		st.RunEffort = &e
	}
	st.GrindLimits = grindLimitsOf(raw["grind_limits"])
	st.ReleaseNote = releaseNoteOf(raw["release_note"])
	st.Server = serverOf(raw["server"])
	return l
}

func defaultGrindLimits() GrindLimits {
	return GrindLimits{MaxRounds: 10, PollInterval: 60, MaxWait: 1500, MaxIdleWaits: 4, StuckSeen: 2, CITimeout: 1200, CIPoll: 30}
}

func grindLimitsOf(v any) GrindLimits {
	g := defaultGrindLimits()
	m, _ := v.(map[string]any)
	for k, p := range map[string]*int{"max_rounds": &g.MaxRounds, "poll_interval": &g.PollInterval, "max_wait": &g.MaxWait,
		"max_idle_waits": &g.MaxIdleWaits, "stuck_seen": &g.StuckSeen, "ci_timeout": &g.CITimeout, "ci_poll": &g.CIPoll} {
		if n, ok := intOf(m[k]); ok && n >= 1 {
			*p = n
		}
	}
	return g
}

func defaultReleaseNote() ReleaseNote {
	return ReleaseNote{ChannelName: "dc-supports", ChannelID: "C06RSFFRUFM", Suffix: "vai", CC: []CC{
		{Name: "Ashique", SlackID: "UAY0MVDHT"}, {Name: "Najmul", SlackID: "U01012AA4FL"}, {Name: "Abir", SlackID: "U067P3ADDDM"}}}
}

func releaseNoteOf(v any) ReleaseNote {
	r := defaultReleaseNote()
	m, ok := v.(map[string]any)
	if !ok {
		return r
	}
	if s, ok := m["channel_name"].(string); ok && s != "" {
		r.ChannelName = s
	}
	if s, ok := m["channel_id"].(string); ok && channelRE.MatchString(s) {
		r.ChannelID = s
	}
	if s, ok := m["suffix"].(string); ok {
		r.Suffix = s
	}
	if list, ok := m["cc"].([]any); ok {
		r.CC = []CC{}
		for _, e := range list {
			c, ok := e.(map[string]any)
			if !ok {
				continue
			}
			n, _ := c["name"].(string)
			id, _ := c["slack_id"].(string)
			if n != "" && slackIDRE.MatchString(id) {
				r.CC = append(r.CC, CC{n, id})
			}
		}
	}
	return r
}

func defaultServer() ServerSettings {
	return ServerSettings{Port: 8420, Tailscale: true, TailscaleHTTPSPort: 443, AllowHosts: []string{}}
}

func serverOf(v any) ServerSettings {
	sv := defaultServer()
	m, ok := v.(map[string]any)
	if !ok {
		return sv
	}
	if n, ok := intOf(m["port"]); ok && n >= 1 && n <= 65535 {
		sv.Port = n
	}
	if b, ok := m["tailscale"].(bool); ok {
		sv.Tailscale = b
	}
	if n, ok := intOf(m["tailscale_https_port"]); ok && (n == 443 || n == 8443 || n == 10000) {
		sv.TailscaleHTTPSPort = n
	}
	if list, ok := m["allow_hosts"].([]any); ok {
		for _, e := range list {
			if h, ok := e.(string); ok && hostRE.MatchString(h) {
				sv.AllowHosts = append(sv.AllowHosts, h)
			}
		}
	}
	return sv
}

func channelsOf(v any) []Channel {
	out := []Channel{}
	list, _ := v.([]any)
	for _, e := range list {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		id, ok1 := m["id"].(string)
		name, ok2 := m["name"].(string)
		if ok1 && ok2 && channelRE.MatchString(id) {
			out = append(out, Channel{id, name})
		}
	}
	return out
}

func reviewersOf(v any) []Reviewer {
	out := []Reviewer{}
	list, _ := v.([]any)
	for _, e := range list {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		id, a := m["id"].(string)
		name, b := m["name"].(string)
		sid, c := m["slack_id"].(string)
		login, d := m["github_login"].(string)
		if a && b && c && d && reviewerIDRE.MatchString(id) {
			out = append(out, Reviewer{id, name, sid, login})
		}
	}
	return out
}

func repoOf(v any) RepoSettings {
	m, _ := v.(map[string]any)
	r := RepoSettings{}
	r.AutoGrind = m["auto_grind"] == true
	r.SlackChannel, _ = m["slack_channel"].(string)
	if list, ok := m["reviewers"].([]any); ok {
		ids := []string{}
		for _, e := range list {
			s, ok := e.(string)
			if !ok {
				ids = nil
				break
			}
			ids = append(ids, s)
		}
		r.Reviewers = ids
	}
	r.ReleaseHead, _ = m["release_head"].(string)
	r.ReleaseBase, _ = m["release_base"].(string)
	return r
}

func known(v any, ids map[string]bool) []string {
	out := []string{}
	switch list := v.(type) {
	case []any:
		for _, e := range list {
			if s, ok := e.(string); ok && ids[s] {
				out = append(out, s)
			}
		}
	case []string:
		for _, s := range list {
			if ids[s] {
				out = append(out, s)
			}
		}
	}
	return out
}

func intOf(v any) (int, bool) {
	f, ok := v.(float64)
	if !ok || f != float64(int(f)) {
		return 0, false
	}
	return int(f), true
}

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

func expandHome(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		if u, err := os.UserHomeDir(); err == nil {
			return filepath.Join(u, strings.TrimPrefix(p, "~"))
		}
	}
	return p
}

// ---------- accessors ----------

// Accounts lists the accounts, the built-in first.
func (s *Store) Accounts() []Account { return append([]Account(nil), s.Get().Commands...) }

func (s *Store) Account(label string) (Account, bool) {
	for _, a := range s.Get().Commands {
		if a.Label == label {
			return a, true
		}
	}
	return Account{}, false
}

// Default is the account new work runs on.
func (s *Store) Default() Account {
	st := s.Get()
	for _, a := range st.Commands {
		if a.Label == st.Default {
			return a
		}
	}
	return st.Commands[0]
}

// CheckRun validates a model / effort pair ("" = unset), S§4.2.
func (s *Store) CheckRun(model, effort string) error { return CheckRun(model, effort) }

func CheckRun(model, effort string) error {
	if model != "" && !contains(RunModels, model) {
		return errs.Invalid("model must be one of %s", strings.Join(RunModels, ", "))
	}
	if effort != "" && !contains(RunEfforts, effort) {
		return errs.Invalid("effort must be one of %s", strings.Join(RunEfforts, ", "))
	}
	return nil
}

// View is the GET /api/settings shape.
func (s *Store) View() SettingsView { return s.viewOf(s.get()) }

func (s *Store) viewOf(l *loaded) SettingsView {
	checkouts := s.checkouts()
	cj := s.channelsJSON()
	mapped := map[string]bool{}
	for k, v := range cj.Channels {
		if v != "" {
			mapped[strings.ToLower(k)] = true
		}
	}
	listed := map[string]bool{}
	for _, c := range l.SlackChannels {
		listed[c.ID] = true
	}
	v := SettingsView{Settings: l.Settings, Repos: map[string]RepoView{}}
	add := func(slug string) {
		if _, ok := v.Repos[slug]; ok {
			return
		}
		r := l.Repos[slug]
		if r.Reviewers != nil {
			r.Reviewers = append([]string{}, r.Reviewers...)
		}
		rv := RepoView{RepoSettings: r}
		rv.ChannelInvalid = r.SlackChannel != "" && !listed[r.SlackChannel]
		gp := "github"
		if r.SlackChannel != "" || mapped[strings.ToLower(slug)] {
			gp = "slack"
		}
		rv.GrindPath = &gp
		if p, ok := checkouts[slug]; ok {
			rv.Path = &p
		}
		v.Repos[slug] = rv
	}
	for slug := range checkouts {
		add(slug)
	}
	for slug := range l.Repos {
		add(slug)
	}
	if _, err := exec.LookPath("jev"); err == nil {
		v.JevInstalled = true
	}
	if cj.BotLabel != "" {
		bl := cj.BotLabel
		v.BotLabel = &bl
	}
	return v
}

func (s *Store) publish() {
	if s.bus != nil {
		s.bus.Publish(events.TUsage, map[string]any{"kind": "settings"})
	}
}

// ---------- per-issue grind ----------

func (s *Store) issueGrindPath() string { return s.h.Path("issue_grind.json") }

func (s *Store) IssueGrind(slug string, issue int) (on, set bool) {
	m := map[string]map[string]bool{}
	_ = home.ReadJSON(s.issueGrindPath(), &m)
	v, ok := m[strings.ToLower(slug)][itoa(issue)]
	return v, ok
}

func (s *Store) SetIssueGrind(slug string, issue int, on bool) error {
	if !slugRE.MatchString(slug) {
		return errs.Invalid("repo must be owner/repo")
	}
	if issue < 1 {
		return errs.Invalid("issue must be a number and on must be true or false")
	}
	_, err := home.UpdateJSON(s.issueGrindPath(), func(m *map[string]map[string]bool) error {
		if *m == nil {
			*m = map[string]map[string]bool{}
		}
		k := strings.ToLower(slug)
		if (*m)[k] == nil {
			(*m)[k] = map[string]bool{}
		}
		(*m)[k][itoa(issue)] = on
		return nil
	})
	return err
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}

// ---------- ui.json ----------

func (s *Store) uiPath() string { return s.h.Path("ui.json") }

// Notify reads ui.json. A file with a group/other permission bit set is ignored with a warning.
func (s *Store) Notify() NotifyConfig {
	var c NotifyConfig
	fi, err := os.Stat(s.uiPath())
	if err != nil {
		return c
	}
	if fi.Mode().Perm()&0o077 != 0 {
		s.mu.Lock()
		if !s.warned.Equal(fi.ModTime()) {
			s.warned = fi.ModTime()
			log.Printf("settings: ignoring ui.json: mode %o is too open, run chmod 600", fi.Mode().Perm())
		}
		s.mu.Unlock()
		return c
	}
	_ = home.ReadJSON(s.uiPath(), &c)
	return c
}

// SaveNotify replaces ui.json (mode 0600).
func (s *Store) SaveNotify(c NotifyConfig) error {
	_, err := s.UpdateNotify(func(cur *NotifyConfig) error { *cur = c; return nil })
	return err
}

// UpdateNotify is a locked read-modify-write of ui.json (0600).
func (s *Store) UpdateNotify(fn func(*NotifyConfig) error) (NotifyConfig, error) {
	return home.UpdateJSON(s.uiPath(), fn)
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

// jsonNorm round-trips m through JSON so every value is a generic any (what normalize reads).
func jsonNorm(m map[string]any) map[string]any {
	b, err := json.Marshal(m)
	if err != nil {
		return m
	}
	out := map[string]any{}
	if json.Unmarshal(b, &out) != nil {
		return m
	}
	return out
}
