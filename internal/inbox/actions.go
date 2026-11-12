package inbox

import (
	"fmt"
	"net/url"
	"regexp"
	"strings"
)

// Start builds the POST /api/sessions action that runs a registry step.
func Start(key, label, toast string, body map[string]any) Action {
	return Action{Key: key, Label: label, Method: "POST", Path: "/api/sessions", Body: body, Toast: toast}
}

// Post is a plain POST action with an optional body.
func Post(key, label, path, toast string, body any) Action {
	return Action{Key: key, Label: label, Method: "POST", Path: path, Body: body, Toast: toast}
}

// Open is a navigation action: a "#/..." route or an https URL.
func Open(key, label, to string) Action {
	return Action{Key: key, Label: label, Method: "POST", Path: "", Toast: "", Open: to}
}

// WithPrimary, WithClears and WithConfirm set the flags of an action.
func (a Action) WithPrimary() Action { a.Primary = true; return a }
func (a Action) WithClears() Action  { a.Clears = true; return a }
func (a Action) WithConfirm(s string) Action {
	a.Confirm = s
	return a
}

func IssueURL(repo string, n int) string {
	return fmt.Sprintf("https://github.com/%s/issues/%d", repo, n)
}
func PRURL(repo string, n int) string { return fmt.Sprintf("https://github.com/%s/pull/%d", repo, n) }

// SessionRoute is the UI route of a session.
func SessionRoute(id string) string { return "#/sessions/" + id }

// PRDRoute is the UI route that reads a PRD.
func PRDRoute(repo, path string) string {
	return "#/prd?repo=" + url.QueryEscape(repo) + "&path=" + url.QueryEscape(path)
}

var stampRe = regexp.MustCompile(`^\s*(\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)?) — `)

// SplitReason strips a leading "<ISO> — " stamp from a grind reason (G§3 split_reason).
func SplitReason(r string) (stamp, reason string) {
	if m := stampRe.FindStringSubmatch(r); m != nil {
		return m[1], strings.TrimSpace(r[len(m[0]):])
	}
	return "", strings.TrimSpace(r)
}

func equalFold(a, b string) bool { return strings.EqualFold(a, b) }
