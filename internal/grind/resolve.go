package grind

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/settings"
)

// NoReviewer is the resolver skip when a repo has nobody to ask.
const NoReviewer = "no Slack channel or reviewer, its lanes skip grinding"

// Reviewers is who a PR's grind asks (W§6.4). Path is "slack", "github" or nil.
type Reviewers struct {
	Path     *string  `json:"path"`
	Channel  *string  `json:"channel"`
	Mentions []string `json:"mentions"`
	Logins   []string `json:"logins"`
	Unlogged []string `json:"unlogged"`
	Skip     *string  `json:"skip"`
}

func emptyReviewers(skip string) Reviewers {
	return Reviewers{Mentions: []string{}, Logins: []string{}, Unlogged: []string{}, Skip: strp(skip)}
}

func findFold[V any](m map[string]V, key string) (V, bool) {
	var zero V
	for k, v := range m {
		if strings.EqualFold(k, key) {
			return v, true
		}
	}
	return zero, false
}

// Resolve answers who the grind of repo asks. No network. A repo absent from settings.repos,
// channels.json and the checkouts registry gets an empty answer without a skip.
func Resolve(st settings.Settings, ch Channels, checkouts map[string]string, repo string) Reviewers {
	r, inSettings := findFold(st.Repos, repo)
	mapped := ch.Mapped(repo)
	_, inCheckouts := findFold(checkouts, repo)
	if !inSettings && mapped == "" && !inCheckouts {
		return emptyReviewers("")
	}
	stored := r.SlackChannel
	if stored != "" {
		listed := false
		for _, c := range st.SlackChannels {
			if c.ID == stored {
				listed = true
			}
		}
		if !listed {
			return emptyReviewers("invalid Slack channel " + stored + ", pick a channel in Settings")
		}
	}
	path := "github"
	if stored != "" || mapped != "" {
		path = "slack"
	}
	ids := st.ActiveReviewers
	if r.Reviewers != nil {
		ids = r.Reviewers
	}
	out := emptyReviewers("")
	for _, x := range st.Reviewers {
		in := false
		for _, id := range ids {
			if id == x.ID {
				in = true
			}
		}
		if !in {
			continue
		}
		if x.SlackID != "" {
			out.Mentions = append(out.Mentions, x.SlackID)
		}
		if x.GithubLogin != "" {
			out.Logins = append(out.Logins, x.GithubLogin)
		}
		if path == "slack" && x.SlackID != "" && x.GithubLogin == "" {
			out.Unlogged = append(out.Unlogged, x.SlackID)
		}
	}
	if (path == "slack" && len(out.Mentions) == 0 && ch.BotUID == "") || (path == "github" && len(out.Logins) == 0) {
		return emptyReviewers(NoReviewer)
	}
	out.Path = &path
	out.Channel = strp(stored)
	return out
}

// ResolvePR is Resolve for a PR URL (a URL that is not a PR gives the empty answer). strict makes
// an unreadable ui_settings.json an error instead of falling back to defaults.
func ResolvePR(h *home.Home, st *settings.Store, prURL string, strict bool) (Reviewers, error) {
	m := reURLRepo.FindStringSubmatch(prURL)
	if m == nil {
		return emptyReviewers(""), nil
	}
	if strict {
		if err := checkSettingsReadable(h); err != nil {
			return emptyReviewers(""), err
		}
	}
	checkouts := map[string]string{}
	_ = home.ReadJSON(h.Path("checkouts.json"), &checkouts)
	return Resolve(st.Get(), LoadChannels(h), checkouts, m[1]+"/"+m[2]), nil
}

func checkSettingsReadable(h *home.Home) error {
	b, err := os.ReadFile(h.Path("ui_settings.json"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("cannot read ui_settings.json: %v", err)
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return fmt.Errorf("cannot read ui_settings.json: %v", err)
	}
	if _, ok := v.(map[string]any); !ok {
		return fmt.Errorf("cannot read ui_settings.json: not an object")
	}
	return nil
}
