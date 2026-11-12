// Package blubird detects the blubird Claude Code plugin and installs or updates it through the
// `claude plugin ...` commands.
package blubird

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
)

const (
	pluginName      = "blubird"
	marketplaceName = "agentic-workflow"
	marketplaceRepo = "blubird-interactiveltd/agentic-workflow"
	stepTimeout     = 300 * time.Second
)

// Status is the Blubird type of API.md §4.
type Status struct {
	Installed       bool     `json:"installed"`
	Version         string   `json:"version"`
	Latest          string   `json:"latest"`
	UpdateAvailable bool     `json:"update_available"`
	InstallPath     string   `json:"install_path"`
	Marketplace     string   `json:"marketplace"`
	Skills          []string `json:"skills"`
	Hooks           []string `json:"hooks"`
	Busy            string   `json:"busy"` // "" | "installing" | "updating"
	Error           string   `json:"error"`
}

type Manager struct {
	h   *home.Home
	bus *events.Bus

	mu     sync.Mutex
	cache  Status
	stamp  string // mtimes the cache was built from
	busy   string
	errMsg string
	wg     sync.WaitGroup
}

func New(h *home.Home, bus *events.Bus) *Manager { return &Manager{h: h, bus: bus} }

func configDir() string {
	if d := os.Getenv("CLAUDE_CONFIG_DIR"); d != "" {
		return d
	}
	hd, _ := os.UserHomeDir()
	return filepath.Join(hd, ".claude")
}

func pluginsDir() string { return filepath.Join(configDir(), "plugins") }

func mtime(p string) string {
	fi, err := os.Stat(p)
	if err != nil {
		return "-"
	}
	return fi.ModTime().Format(time.RFC3339Nano)
}

// Status returns the cached status, re-detecting when installed_plugins.json or the marketplace
// registry changed on disk.
func (m *Manager) Status() Status {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.statusLocked()
}

func (m *Manager) statusLocked() Status {
	stamp := mtime(filepath.Join(pluginsDir(), "installed_plugins.json")) + "|" + mtime(filepath.Join(pluginsDir(), "known_marketplaces.json")) + "|" + pluginsDir()
	if stamp != m.stamp {
		m.cache = detect()
		m.stamp = stamp
	}
	s := m.cache
	s.Busy, s.Error = m.busy, m.errMsg
	return s
}

type installedFile struct {
	Plugins map[string][]struct {
		Scope       string `json:"scope"`
		InstallPath string `json:"installPath"`
		Version     string `json:"version"`
	} `json:"plugins"`
}

func detect() Status {
	st := Status{Marketplace: marketplaceName, Skills: []string{}, Hooks: []string{}}
	var inst installedFile
	if b, err := os.ReadFile(filepath.Join(pluginsDir(), "installed_plugins.json")); err == nil {
		_ = json.Unmarshal(b, &inst)
	}
	keys := make([]string, 0, len(inst.Plugins))
	for k := range inst.Plugins {
		if strings.HasPrefix(k, pluginName+"@") {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	for _, k := range keys {
		recs := inst.Plugins[k]
		sort.SliceStable(recs, func(i, j int) bool { return recs[i].Scope == "user" && recs[j].Scope != "user" })
		for _, r := range recs {
			if fi, err := os.Stat(r.InstallPath); r.InstallPath == "" || err != nil || !fi.IsDir() {
				continue
			}
			st.Installed = true
			st.Version = r.Version
			st.InstallPath = r.InstallPath
			st.Marketplace = strings.TrimPrefix(k, pluginName+"@")
			break
		}
		if st.Installed {
			break
		}
	}
	if st.Installed {
		st.Skills = listSkills(st.InstallPath)
		st.Hooks = listHooks(st.InstallPath)
	}
	st.Latest = latestVersion(st.Marketplace)
	st.UpdateAvailable = st.Installed && st.Latest != "" && st.Latest != st.Version
	return st
}

func listSkills(root string) []string {
	out := []string{}
	ents, _ := os.ReadDir(filepath.Join(root, "skills"))
	for _, e := range ents {
		if _, err := os.Stat(filepath.Join(root, "skills", e.Name(), "SKILL.md")); err == nil {
			out = append(out, e.Name())
		}
	}
	return out
}

// listHooks returns the hook event names declared by the plugin (hooks/hooks.json).
func listHooks(root string) []string {
	out := []string{}
	b, err := os.ReadFile(filepath.Join(root, "hooks", "hooks.json"))
	if err != nil {
		return out
	}
	var f struct {
		Hooks map[string]json.RawMessage `json:"hooks"`
	}
	if json.Unmarshal(b, &f) != nil {
		return out
	}
	for k := range f.Hooks {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// latestVersion reads the version blubird has in the marketplace manifest, "" when unknown.
func latestVersion(marketplace string) string {
	var known map[string]struct {
		InstallLocation string `json:"installLocation"`
	}
	b, err := os.ReadFile(filepath.Join(pluginsDir(), "known_marketplaces.json"))
	if err != nil || json.Unmarshal(b, &known) != nil {
		return ""
	}
	loc := known[marketplace].InstallLocation
	if loc == "" {
		return ""
	}
	mb, err := os.ReadFile(filepath.Join(loc, ".claude-plugin", "marketplace.json"))
	if err != nil {
		return ""
	}
	var mf struct {
		Plugins []struct {
			Name    string          `json:"name"`
			Version string          `json:"version"`
			Source  json.RawMessage `json:"source"`
		} `json:"plugins"`
	}
	if json.Unmarshal(mb, &mf) != nil {
		return ""
	}
	for _, p := range mf.Plugins {
		if p.Name != pluginName {
			continue
		}
		if p.Version != "" {
			return p.Version
		}
		var src string
		if json.Unmarshal(p.Source, &src) == nil && src != "" {
			if pb, err := os.ReadFile(filepath.Join(loc, src, ".claude-plugin", "plugin.json")); err == nil {
				var pj struct {
					Version string `json:"version"`
				}
				if json.Unmarshal(pb, &pj) == nil {
					return pj.Version
				}
			}
		}
	}
	return ""
}

// SkillDir returns the directory of one of blubird's skills.
func (m *Manager) SkillDir(skill string) (string, bool) {
	if skill == "" || strings.ContainsAny(skill, `/\`) || strings.Contains(skill, "..") {
		return "", false
	}
	st := m.Status()
	if !st.Installed {
		return "", false
	}
	d := filepath.Join(st.InstallPath, "skills", skill)
	if fi, err := os.Stat(filepath.Join(d, "SKILL.md")); err != nil || fi.IsDir() {
		return "", false
	}
	return d, true
}

// Install starts the install job and returns at once. errs.Conflict when a job is running,
// errs.Upstream when `claude` is not on PATH.
func (m *Manager) Install(ctx context.Context) error {
	return m.start("installing", [][]string{
		{"claude", "plugin", "marketplace", "add", marketplaceRepo},
		{"claude", "plugin", "install", pluginName + "@" + marketplaceName},
	}, func(r execx.Result, i int) bool {
		// adding a marketplace that is already there is not a failure
		return i == 0 && strings.Contains(strings.ToLower(string(r.Stdout)+string(r.Stderr)), "already")
	})
}

func (m *Manager) Update(ctx context.Context) error {
	return m.start("updating", [][]string{
		{"claude", "plugin", "marketplace", "update", marketplaceName},
		{"claude", "plugin", "update", pluginName + "@" + marketplaceName},
	}, func(r execx.Result, i int) bool {
		// older claude versions have no `plugin update`: that counts as success
		return i == 1 && strings.Contains(strings.ToLower(string(r.Stdout)+string(r.Stderr)), "unknown command")
	})
}

func (m *Manager) start(kind string, steps [][]string, tolerate func(execx.Result, int) bool) error {
	if _, err := exec.LookPath("claude"); err != nil {
		return errs.Upstream("claude is not on PATH")
	}
	m.mu.Lock()
	if m.busy != "" {
		b := m.busy
		m.mu.Unlock()
		return errs.Conflict("blubird is "+b, nil)
	}
	m.busy, m.errMsg = kind, ""
	m.wg.Add(1)
	m.mu.Unlock()
	m.publish()
	go func() {
		defer m.wg.Done()
		// The job outlives the HTTP request that started it.
		ctx := context.Background()
		var failure string
		for i, argv := range steps {
			r := execx.Run(ctx, argv, execx.Opts{Timeout: stepTimeout})
			if r.Code != 0 && !tolerate(r, i) {
				failure = strings.Join(argv[1:], " ") + ": " + r.LastLine()
				if r.LastLine() == "" {
					failure = strings.Join(argv[1:], " ") + ": exit " + strconv.Itoa(r.Code)
				}
				break
			}
		}
		m.mu.Lock()
		m.busy, m.errMsg = "", failure
		m.stamp = "" // force re-detect
		m.mu.Unlock()
		m.publish()
		m.toast(kind, failure)
	}()
	return nil
}

// Wait blocks until the running job (if any) has finished.
func (m *Manager) Wait() { m.wg.Wait() }

func (m *Manager) publish() {
	if m.bus != nil {
		m.bus.Publish(events.TProducts, map[string]any{"kind": "blubird"})
	}
}

var toastSeq = time.Now().UnixMilli()

func (m *Manager) toast(kind, failure string) {
	if m.bus == nil {
		return
	}
	verb := map[string]string{"installing": "installed", "updating": "updated"}[kind]
	t := map[string]any{"id": nextToast(), "event": "info", "title": "blubird " + verb, "body": "", "path": "#/settings", "level": "info"}
	if failure != "" {
		t["event"], t["level"], t["title"], t["body"] = "error", "error", "blubird was not "+verb, failure
	}
	m.bus.Publish(events.TToast, t)
}

var toastMu sync.Mutex

func nextToast() int64 {
	toastMu.Lock()
	defer toastMu.Unlock()
	toastSeq++
	return toastSeq
}
