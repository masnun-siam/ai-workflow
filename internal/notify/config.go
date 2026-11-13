package notify

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/home"
)

// Channels in matrix order. "ntfy" stays a first-class channel (D7).
var Channels = []string{"browser", "ntfy", "mac", "push"}

// Event is one matrix row.
type Event struct {
	Key   string `json:"key"`
	Label string `json:"label"`
	Group string `json:"group"`
}

// Events in display order (W§4.1 minus prd-comment/pipeline, plus release).
var Events = []Event{
	{"waiting", "A session is waiting on you", "Needs you"},
	{"failed", "A session failed", "Needs you"},
	{"dispatch", "A dispatch needs you", "Needs you"},
	{"panel-cap", "Review panel hit its cap", "Needs you"},
	{"stalled", "A session or lane stalled", "Needs you"},
	{"pr-ready", "PR is ready for review", "Pull requests"},
	{"needs-cleanup", "Merged issue needs cleanup", "Pull requests"},
	{"grind-paused", "Grind paused", "Pull requests"},
	{"grind-done", "Grind finished", "Pull requests"},
	{"done", "A session is done", "Finished"},
	{"afk", "Away mode ended", "Finished"},
	{"release", "A release finished", "Finished"},
}

func isEvent(k string) bool {
	for _, e := range Events {
		if e.Key == k {
			return true
		}
	}
	return false
}

func isChannel(c string) bool {
	for _, x := range Channels {
		if x == c {
			return true
		}
	}
	return false
}

// DefaultCell is the matrix default: stalled off everywhere (it is opt-in, apart from real
// questions), otherwise ntfy always on, push always off, browser and mac on unless the event is in
// the Finished group or is grind-done.
func DefaultCell(event, channel string) bool {
	if event == "stalled" {
		return false
	}
	switch channel {
	case "ntfy":
		return true
	case "push":
		return false
	}
	for _, e := range Events {
		if e.Key == event {
			return e.Group != "Finished" && event != "grind-done"
		}
	}
	return false
}

// Cells is one row of the matrix.
type Cells map[string]bool

// NtfyConfig is the ntfy block of ui.json after env overrides.
type NtfyConfig struct {
	Server, Topic, Token, User, Password string
}

// Config is the notification part of ui.json.
type Config struct {
	Ntfy      NtfyConfig
	PublicURL string
	Stored    map[string]map[string]bool // event -> channel -> stored bool cells
	EnvKeys   []string                   // ntfy keys overridden by the environment
}

// Matrix is the defaults overlaid with the stored boolean cells.
func (c Config) Matrix() map[string]Cells {
	out := map[string]Cells{}
	for _, e := range Events {
		row := Cells{}
		for _, ch := range Channels {
			v, ok := c.Stored[e.Key][ch]
			if !ok {
				v = DefaultCell(e.Key, ch)
			}
			row[ch] = v
		}
		out[e.Key] = row
	}
	return out
}

// cellsFor returns the routing for an event; an unknown event goes to ntfy only.
func (c Config) cellsFor(event string) Cells {
	if m, ok := c.Matrix()[event]; ok {
		return m
	}
	return Cells{"browser": false, "ntfy": true, "mac": false, "push": false}
}

func (s *Service) uiPath() string { return s.h.Path("ui.json") }

// LoadConfig reads ui.json (ignored with a warning when its mode is looser than 0600, or when it
// is unreadable or not an object) and applies the env overrides SETU_NTFY_* then AIW_NTFY_*.
func (s *Service) LoadConfig() Config {
	cfg := Config{Stored: map[string]map[string]bool{}}
	path := s.uiPath()
	var raw map[string]any
	if st, err := os.Stat(path); err == nil {
		if st.Mode().Perm()&0o077 != 0 {
			s.warnf("ignoring %s: mode %#o is looser than 0600; run chmod 600 %s", path, st.Mode().Perm(), path)
		} else if b, err := os.ReadFile(path); err != nil {
			s.warnf("ignoring %s: unreadable", path)
		} else if len(strings.TrimSpace(string(b))) > 0 {
			if err := json.Unmarshal(b, &raw); err != nil || raw == nil {
				s.warnf("ignoring %s: expected a JSON object", path)
				raw = nil
			}
		}
	}
	str := func(m map[string]any, k string) string { v, _ := m[k].(string); return v }
	nt, _ := raw["ntfy"].(map[string]any)
	n := NtfyConfig{str(nt, "server"), str(nt, "topic"), str(nt, "token"), str(nt, "user"), str(nt, "password")}
	for _, k := range []string{"server", "topic", "token", "user", "password"} {
		v := s.getenv("SETU_NTFY_" + strings.ToUpper(k))
		if v == "" {
			v = s.getenv("AIW_NTFY_" + strings.ToUpper(k))
		}
		if v == "" {
			continue
		}
		cfg.EnvKeys = append(cfg.EnvKeys, k)
		switch k {
		case "server":
			n.Server = v
		case "topic":
			n.Topic = v
		case "token":
			n.Token = v
		case "user":
			n.User = v
		case "password":
			n.Password = v
		}
	}
	cfg.Ntfy = n
	cfg.PublicURL = str(raw, "public_url")
	if ch, ok := raw["channels"].(map[string]any); ok {
		for _, e := range Events {
			row, ok := ch[e.Key].(map[string]any)
			if !ok {
				continue
			}
			for _, c := range Channels {
				if b, ok := row[c].(bool); ok {
					if cfg.Stored[e.Key] == nil {
						cfg.Stored[e.Key] = map[string]bool{}
					}
					cfg.Stored[e.Key][c] = b
				}
			}
		}
	}
	return cfg
}

// update is a locked read-modify-write of ui.json that keeps every unknown key (ntfy block
// included). The file ends up 0600.
func (s *Service) update(fn func(m map[string]any) error) error {
	_, err := home.UpdateJSON(s.uiPath(), func(m *map[string]any) error {
		if *m == nil {
			*m = map[string]any{}
		}
		return fn(*m)
	})
	return err
}

// SetCell stores one matrix cell.
func (s *Service) SetCell(event, channel string, on bool) error {
	if !isEvent(event) {
		return fmt.Errorf("unknown event %q", event)
	}
	if !isChannel(channel) {
		return fmt.Errorf("unknown channel %q", channel)
	}
	return s.update(func(m map[string]any) error {
		ch, _ := m["channels"].(map[string]any)
		if ch == nil {
			ch = map[string]any{}
		}
		row, _ := ch[event].(map[string]any)
		if row == nil {
			row = map[string]any{}
		}
		row[channel] = on
		ch[event] = row
		m["channels"] = ch
		return nil
	})
}

// SetPublicURL stores public_url (empty removes it).
func (s *Service) SetPublicURL(u string) error {
	return s.update(func(m map[string]any) error {
		if u == "" {
			delete(m, "public_url")
		} else {
			m["public_url"] = u
		}
		return nil
	})
}
