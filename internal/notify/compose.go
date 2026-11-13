package notify

import (
	"net/url"
	"regexp"
	"strconv"
	"strings"
)

type look struct{ icon, withN, withoutN, action string }

// Titles stay ASCII: they travel as an HTTP header.
var looks = map[string]look{
	"waiting":       {"speech_balloon", "setu: #{n} waiting on you", "setu: waiting on you", "Answer"},
	"done":          {"white_check_mark", "setu: #{n} is done", "setu: run done", "Open run"},
	"failed":        {"x", "setu: #{n} failed", "setu: session failed", "Open run"},
	"grind-paused":  {"pause_button", "setu: #{n} grind paused", "setu: grind paused", "Open run"},
	"grind-done":    {"mag", "setu: #{n} grind finished", "setu: grind finished", "Open run"},
	"afk":           {"robot", "setu: away mode ended", "setu: away mode ended", "Open Inbox"},
	"pr-ready":      {"eyes", "setu: #{n} PR is ready", "setu: PR is ready", "Open Inbox"},
	"needs-cleanup": {"broom", "setu: #{n} needs cleanup", "setu: needs cleanup", "Open Inbox"},
	"panel-cap":     {"no_entry", "setu: review panel hit its cap", "setu: review panel hit its cap", "Open Inbox"},
	"dispatch":      {"rocket", "setu: #{n} in a dispatch needs you", "setu: a dispatch needs you", "Open Inbox"},
	"release":       {"package", "setu: #{n} release finished", "setu: release finished", "Open Inbox"},
	"stalled":       {"zzz", "setu: #{n} stalled", "setu: stalled", "Open Inbox"},
}

var boardEvents = map[string]bool{"afk": true, "pr-ready": true, "needs-cleanup": true, "panel-cap": true, "dispatch": true, "release": true, "stalled": true}

var tagUnsafe = regexp.MustCompile(`[^A-Za-z0-9._#/-]+`)

func tag(s string) string {
	s = tagUnsafe.ReplaceAllString(s, "")
	if len(s) > 40 {
		s = s[:40]
	}
	return s
}

func firstLine(s string, limit int) string {
	for _, ln := range strings.Split(s, "\n") {
		if ln = strings.TrimSpace(ln); ln != "" {
			if r := []rune(ln); len(r) > limit {
				return string(r[:limit-1]) + "…"
			}
			return ln
		}
	}
	return ""
}

var commandRE = regexp.MustCompile(`(?s)^/(?:[\w-]+:)?([\w-]+)(?:\s+.*)?$`)

// skillOf is the skill name of a `/name ...` or `/prefix:name ...` command, else "".
func skillOf(command string) string {
	if m := commandRE.FindStringSubmatch(strings.TrimSpace(command)); m != nil {
		return m[1]
	}
	return ""
}

// Headers are ntfy-style headers; Compose is pure.
type Headers map[string]string

// Compose builds the headers and body of one push.
func Compose(event string, n Note, publicURL string) (Headers, string) {
	lk, ok := looks[event]
	if !ok {
		lk = look{"bell", "setu: update", "setu: update", "Open"}
	}
	issue := 0
	if n.Link != nil {
		issue = n.Link.Issue
	}
	family := n.Step
	if family == "" {
		family = skillOf(n.Command)
	}
	tags := []string{lk.icon}
	for _, t := range []string{tag(family), tag(n.Repo[strings.LastIndex(n.Repo, "/")+1:])} {
		if t != "" {
			tags = append(tags, t)
		}
	}
	title := lk.withoutN
	if issue > 0 {
		tags = append(tags, "#"+strconv.Itoa(issue))
		title = strings.ReplaceAll(lk.withN, "{n}", strconv.Itoa(issue))
	}
	prio := "high"
	switch event {
	case "done", "grind-done", "afk", "release":
		prio = "default"
	}
	h := Headers{"Title": title, "Priority": prio, "Tags": strings.Join(tags, ",")}
	var lines []string
	switch {
	case event == "waiting":
		lines = append(lines, firstLine(n.Question, 200))
		if n.Recommended != "" {
			lines = append(lines, "Suggested: "+firstLine(n.Recommended, 80))
		}
	case event == "failed":
		lines = append(lines, firstLine(n.Error, 200))
	case strings.HasPrefix(event, "grind-") || boardEvents[event]:
		lines = append(lines, firstLine(n.Text, 200))
	}
	lines = append(lines, strings.Trim(n.Repo+" · "+firstLine(n.Command, 120), " ·"))
	if click := clickURL(event, n, publicURL); click != "" {
		h["Click"] = click
		if isASCII(click) {
			h["Actions"] = "view, " + lk.action + ", " + click
		}
	}
	var out []string
	for _, l := range lines {
		if l != "" {
			out = append(out, l)
		}
	}
	return h, strings.Join(out, "\n")
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= 0x80 {
			return false
		}
	}
	return true
}

func sessionID(n Note) string {
	if n.SessionID != "" {
		return n.SessionID
	}
	return n.ID
}

// ClickPath is the SPA hash path a notification opens.
func ClickPath(event string, n Note) string {
	if id := sessionID(n); !boardEvents[event] && id != "" {
		return "#/sessions/" + url.PathEscape(id)
	}
	if boardEvents[event] {
		return "#/inbox"
	}
	return "#/activity"
}

func clickURL(event string, n Note, publicURL string) string {
	if publicURL == "" {
		return ""
	}
	return strings.TrimRight(publicURL, "/") + "/" + ClickPath(event, n)
}
