package grind

import (
	"encoding/json"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/home"
)

const (
	defaultTrigger   = "<@{bot_uid}>, review this PR\n{pr_url}"
	defaultRetrigger = "<@{bot_uid}> recheck"
)

// Channels is channels.json (read only; Settings never writes it). Templates hold {bot_uid} and
// {pr_url} only.
type Channels struct {
	WorkspaceURL string            `json:"workspace_url"`
	BotUID       string            `json:"bot_uid"`
	OwnerUID     string            `json:"owner_uid"`
	BotLabel     string            `json:"bot_label"`
	DMFallback   string            `json:"dm_fallback"`
	KnownBots    []string          `json:"known_bots"`
	Channels     map[string]string `json:"channels"`
	Trigger      string            `json:"trigger"`
	Retrigger    string            `json:"retrigger"`
}

// LoadChannels reads channels.json; a missing or unreadable file is the zero value. The older key
// `workspace` is accepted for `workspace_url`.
func LoadChannels(h *home.Home) Channels {
	var c Channels
	b, err := os.ReadFile(h.Path("channels.json"))
	if err != nil {
		return c
	}
	_ = json.Unmarshal(b, &c)
	if c.WorkspaceURL == "" {
		var alt struct {
			Workspace string `json:"workspace"`
		}
		if json.Unmarshal(b, &alt) == nil {
			c.WorkspaceURL = alt.Workspace
		}
	}
	c.WorkspaceURL = strings.TrimRight(c.WorkspaceURL, "/")
	return c
}

// Mapped is the channel id channels.json maps repo to (case-insensitive), "" when none.
func (c Channels) Mapped(repo string) string {
	for k, v := range c.Channels {
		if strings.EqualFold(k, repo) && v != "" {
			return v
		}
	}
	return ""
}

// Fill expands a trigger or retrigger template. ids are joined so the text has one <@id> each.
func (c Channels) Fill(tmpl string, ids []string, prURL string) string {
	if tmpl == "" {
		tmpl = defaultRetrigger
	}
	t := strings.ReplaceAll(tmpl, "{bot_uid}", strings.Join(ids, "> <@"))
	return strings.ReplaceAll(t, "{pr_url}", prURL)
}

// IsBot reports whether login is a known automation account (case-insensitive).
func (c Channels) IsBot(login string) bool {
	for _, b := range c.KnownBots {
		if strings.EqualFold(b, login) {
			return true
		}
	}
	return false
}
