// Package release owns releases/<id>.json: one release per repo, from the release-pr session
// (cut) through the PR grind and the human merge to the release note (notify).
//
//	cut -> grind -> merge -> notify -> done
//
// Agents never merge: the merge is seen on GitHub (poller hint, else `gh pr view`). The Slack
// note is posted by setu itself, exactly once, and never retried.
package release

import (
	"context"
	"encoding/json"
	"regexp"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

// Stages (API §4 ReleaseStage).
const (
	StCut     = "cut"
	StGrind   = "grind"
	StMerge   = "merge"
	StNotify  = "notify"
	StDone    = "done"
	StSkipped = "skipped"
	StFailed  = "failed"
	StDryRun  = "dry_run"
)

// open reports a stage that still occupies the repo.
func open(stage string) bool {
	switch stage {
	case StCut, StGrind, StMerge, StNotify:
		return true
	}
	return false
}

// GrindState and GrindStatus mirror API §4 (the grind package's Status, through the wiring).
type GrindStatus struct {
	Repo     string  `json:"repo"`
	PR       int     `json:"pr"`
	State    string  `json:"state"` // none|idle|running|paused|approved|done
	Mode     *string `json:"mode"`
	Rounds   int     `json:"rounds"`
	Reason   *string `json:"reason"`
	Thread   *string `json:"thread"`
	Updated  *string `json:"updated"`
	NextPoll *string `json:"next_poll"`
	Session  *string `json:"session"`
}

// Grinds is what release needs from the grind package.
type Grinds interface {
	Get(repo string, pr int) (GrindStatus, bool)
	StartGrind(ctx context.Context, repo string, pr int, by string) (sessions.Record, error)
}

// Sessions is satisfied by *sessions.Manager.
type Sessions interface {
	Launch(ctx context.Context, s sessions.Spec) (sessions.Record, error)
	Get(id string) (sessions.Record, error)
	FinalText(id string) string
	Stop(ctx context.Context, id string) (sessions.Record, error)
}

// Prompts is satisfied by *prompts.Registry.
type Prompts interface {
	BuildIn(step, args, repo string) (prompts.Prompt, error)
}

// Settings is satisfied by *settings.Store.
type Settings interface{ Get() settings.Settings }

// Notifier is satisfied by *notify.Service.
type Notifier interface {
	Notify(event string, n notify.Note)
}

// record is releases/<id>.json.
type record struct {
	ID        string  `json:"id"`
	Repo      string  `json:"repo"`
	Head      string  `json:"head"`
	Base      string  `json:"base"`
	Stage     string  `json:"stage"`
	DryRun    bool    `json:"dry_run"`
	Partial   bool    `json:"partial,omitempty"`
	PR        *int    `json:"pr"`
	PRURL     *string `json:"pr_url"`
	Thread    *string `json:"thread"`
	CutSess   *string `json:"cut_session"`
	NoteSess  *string `json:"note_session"`
	NoteFile  string  `json:"note_file,omitempty"`
	PostedAt  *string `json:"note_posted_at"`
	Permalink *string `json:"note_permalink"`
	MergedAt  *string `json:"merged_at"`
	Error     *string `json:"error"`
	DryRunDir *string `json:"dry_run_dir"`
	CreatedAt string  `json:"created_at"`
	UpdatedAt string  `json:"updated_at"`

	// PostAttemptedAt is set (and persisted) before slackcli runs; once set the note is never
	// sent again, whatever the outcome.
	PostAttemptedAt string `json:"post_attempted_at,omitempty"`
	DraftNotified   bool   `json:"draft_notified,omitempty"`
}

// Release is the API shape (API §4).
type Release struct {
	ID            string       `json:"id"`
	Repo          string       `json:"repo"`
	Head          string       `json:"head"`
	Base          string       `json:"base"`
	Stage         string       `json:"stage"`
	DryRun        bool         `json:"dry_run"`
	PR            *int         `json:"pr"`
	PRURL         *string      `json:"pr_url"`
	Thread        *string      `json:"thread"`
	Grind         *GrindStatus `json:"grind"`
	CutSession    *string      `json:"cut_session"`
	NoteSession   *string      `json:"note_session"`
	Note          *string      `json:"note"`
	NotePostedAt  *string      `json:"note_posted_at"`
	NotePermalink *string      `json:"note_permalink"`
	MergedAt      *string      `json:"merged_at"`
	Error         *string      `json:"error"`
	DryRunDir     *string      `json:"dry_run_dir"`
	CreatedAt     string       `json:"created_at"`
	UpdatedAt     string       `json:"updated_at"`
	Actions       []Action     `json:"actions"`
}

// Action is the server-built button (API §4).
type Action struct {
	Key     string `json:"key"`
	Label   string `json:"label"`
	Method  string `json:"method,omitempty"`
	Path    string `json:"path,omitempty"`
	Body    any    `json:"body,omitempty"`
	Toast   string `json:"toast"`
	Primary bool   `json:"primary,omitempty"`
	Clears  bool   `json:"clears,omitempty"`
	Confirm string `json:"confirm,omitempty"`
	Open    string `json:"open,omitempty"`
}

// ReleaseRepo is one row of the Releases screen.
type ReleaseRepo struct {
	Repo        string       `json:"repo"`
	Name        string       `json:"name"`
	Head        string       `json:"head"`
	Base        string       `json:"base"`
	Ahead       *int         `json:"ahead"`
	PRsWaiting  *int         `json:"prs_waiting"`
	LastRelease *LastRelease `json:"last_release"`
	Open        *string      `json:"open"`
	CheckedAt   *string      `json:"checked_at"`
	Actions     []Action     `json:"actions"`
}

// LastRelease is the newest merged release PR of the repo.
type LastRelease struct {
	PR       int    `json:"pr"`
	MergedAt string `json:"merged_at"`
}

// CutOpts are the options of a cut. Head and Base default to the repo's settings
// (release_head / release_base), then staging and master.
type CutOpts struct {
	DryRun  bool
	Partial bool
	Head    string
	Base    string
}

var idRE = regexp.MustCompile(`^r-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$`)
var branchRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$`)
var prURLRE = regexp.MustCompile(`/pull/([0-9]+)(?:[/?#]|$)`)

// Result is the parsed SETU-RELEASE: line.
type Result struct {
	PR     *string `json:"pr"`
	Thread *string `json:"thread"`
	Reason string  `json:"reason"`
	DryRun string  `json:"dry_run"`
}

// ParseResult finds the last `SETU-RELEASE: {json}` line of a session's final text. ok is false
// when there is none or its JSON is invalid.
func ParseResult(text string) (Result, bool) {
	lines := strings.Split(text, "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		l := strings.TrimSpace(lines[i])
		l = strings.TrimPrefix(l, "`")
		l = strings.TrimSuffix(l, "`")
		rest, found := strings.CutPrefix(l, "SETU-RELEASE:")
		if !found {
			continue
		}
		var r Result
		if json.Unmarshal([]byte(strings.TrimSpace(rest)), &r) != nil {
			return Result{}, false
		}
		return r, true
	}
	return Result{}, false
}

// PRNumber extracts the number of a pull request URL.
func PRNumber(url string) (int, bool) {
	m := prURLRE.FindStringSubmatch(url)
	if m == nil {
		return 0, false
	}
	n, err := strconv.Atoi(m[1])
	return n, err == nil && n > 0
}

var slugRE = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
