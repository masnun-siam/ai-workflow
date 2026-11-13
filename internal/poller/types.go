// Package poller polls GitHub per repo with a cheap GraphQL probe and a full query only when the
// probe saw a change (G§1.3), keeps the result as an in-memory Snapshot, and never writes to GitHub.
package poller

import (
	"fmt"
	"time"
)

// Board statuses (blubird's Projects v2 Status field values).
const (
	StatusBacklog    = "Backlog"
	StatusReady      = "Ready"
	StatusInProgress = "In progress"
	StatusInReview   = "In review"
	StatusDone       = "Done"
)

// Ref points at an issue, possibly in another repo of the same product (parents, sub-issues and
// blockers cross repos). Repo is "owner/name".
type Ref struct {
	Repo string `json:"repo"`
	N    int    `json:"n"`
}

// String is the IssueKey "owner/name#n".
func (r Ref) String() string { return fmt.Sprintf("%s#%d", r.Repo, r.N) }

// ClosedSub is a closed sub-issue (an epic's finished child).
type ClosedSub struct {
	Ref
	Title string `json:"title"`
}

// Blocker is a blocking issue; BlockedBy lists all blockers, consumers filter on State "OPEN".
type Blocker struct {
	Ref
	State string `json:"state"`
}

// PR is a pull request attached to an issue.
type PR struct {
	N        int    `json:"n"`
	URL      string `json:"url"`
	Draft    bool   `json:"draft"`
	State    string `json:"state"` // OPEN | CLOSED | MERGED
	MergedAt string `json:"merged_at"`
	Head     string `json:"head"`
	SHA      string `json:"sha"`
	CI       string `json:"ci"`     // success | failure | pending | none
	Review   string `json:"review"` // approved | changes_requested | review_required | none
	Conflict bool   `json:"conflict"`
}

// Issue is an OPEN issue (epics included: an epic has the label "epic").
type Issue struct {
	N          int         `json:"n"`
	Title      string      `json:"title"`
	State      string      `json:"state"`
	Labels     []string    `json:"labels"`
	Priority   *string     `json:"priority"`
	Parent     *Ref        `json:"parent"`
	SubIssues  []Ref       `json:"sub_issues"`
	ClosedSubs []ClosedSub `json:"closed_subs"`
	BlockedBy  []Blocker   `json:"blocked_by"`
	PRs        []PR        `json:"prs"`
	// ProjectStatus is the raw Projects v2 "Status" option name when the issue is on a project
	// ("" otherwise). Status is the effective board status: the project's value when it is one of the
	// five known statuses, else derived from labels, blockers and PRs (G§3 mapping). "In progress" can
	// only come from the project (a live session is not known here; views overlay it).
	ProjectStatus string `json:"project_status"`
	Status        string `json:"status"`
}

// Merged is a PR merged in the last 7 days.
type Merged struct {
	N        int    `json:"n"`
	Title    string `json:"title"`
	URL      string `json:"url"`
	MergedAt string `json:"merged_at"`
	Head     string `json:"head"`
	Closes   []int  `json:"closes"`
	Epic     *Ref   `json:"epic"`
	SHA      string `json:"sha"`
}

// OpenPR is an open pull request with its review state.
type OpenPR struct {
	N        int    `json:"n"`
	Title    string `json:"title"`
	URL      string `json:"url"`
	Draft    bool   `json:"draft"`
	Head     string `json:"head"`
	SHA      string `json:"sha"`
	CI       string `json:"ci"`
	Review   string `json:"review"`
	Conflict bool   `json:"conflict"`
	// Refs are the issues the PR is for: GitHub's closing links, closing keywords in the body, the
	// `issue-<n>-` branch name.
	Refs             []int   `json:"refs"`
	Reviewer         *string `json:"reviewer"` // login of the last approving review
	Approved         bool    `json:"approved"`
	ChangesRequested bool    `json:"changes_requested"`
	Checks           int     `json:"checks"`       // status checks that ran
	ThreadsOpen      int     `json:"threads_open"` // unresolved, non-outdated review threads
	UpdatedAt        string  `json:"updated_at"`   // when GitHub last touched the PR (RFC 3339)
}

// ClosedEpic is one of the 50 most recently updated CLOSED issues labelled epic.
type ClosedEpic struct {
	N          int         `json:"n"`
	Labels     []string    `json:"labels"`
	ClosedSubs []ClosedSub `json:"closed_subs"`
}

// Data is what one full fetch learned. All lists are non-nil.
type Data struct {
	Issues          []Issue      `json:"issues"`
	Merged          []Merged     `json:"merged"`
	OpenPRs         []OpenPR     `json:"open_prs"`
	ClosedEpics     []ClosedEpic `json:"closed_epics"`
	IssuesTruncated bool         `json:"issues_truncated"`
	// ProjectsNote says why Projects v2 status was not read ("" when it was, or the repo has none).
	ProjectsNote string `json:"projects_note,omitempty"`
}

// EmptyData is the shape before the first fetch.
func EmptyData() Data {
	return Data{Issues: []Issue{}, Merged: []Merged{}, OpenPRs: []OpenPR{}, ClosedEpics: []ClosedEpic{}}
}

// Empty reports whether d equals EmptyData (the "first poll" test for notifications).
func (d Data) Empty() bool {
	return len(d.Issues) == 0 && len(d.Merged) == 0 && len(d.OpenPRs) == 0 && len(d.ClosedEpics) == 0 && !d.IssuesTruncated
}

// Snapshot is a repo's state from memory; it never waits on GitHub.
type Snapshot struct {
	Repo      string     `json:"repo"`
	Data      Data       `json:"data"`
	Stale     bool       `json:"stale"`
	FetchedAt *time.Time `json:"fetched_at"` // nil before the first good poll
	Error     string     `json:"error"`      // "" after a good poll; "rate limited" or gh's message
	RetryAt   *time.Time `json:"retry_at"`   // end of a rate-limit pause, else nil
}

// Fresh reports a snapshot that is current: not stale and fetched at least once.
func (s Snapshot) Fresh() bool { return !s.Stale && s.FetchedAt != nil }

// GrindFact is the grind state of a PR as far as the merge gate cares.
type GrindFact struct {
	State string // running | idle | paused | done
}

// MergeBlockers is why an open PR may not merge, or "" (G§4.1). Order: draft, conflict, changes
// requested, unresolved threads, no approving review (skipped when solo). CI mode and grind are the
// caller's job.
func MergeBlockers(pr OpenPR, solo bool) string {
	switch {
	case pr.Draft:
		return "PR is a draft"
	case pr.Conflict:
		return "PR has a merge conflict"
	case pr.ChangesRequested:
		return "changes requested"
	case pr.ThreadsOpen > 0:
		return "unresolved review threads"
	case !pr.Approved && !solo:
		return "no approving review"
	}
	return ""
}

// MergeReady: CI is green, no blockers, and with grinding on the grind is done (a stopped one
// counts). A nil pr or a CI other than "success" is never ready.
func MergeReady(pr *OpenPR, g *GrindFact, grindOn, solo bool) bool {
	if pr == nil || pr.CI != "success" {
		return false
	}
	if grindOn && (g == nil || g.State != "done") {
		return false
	}
	return MergeBlockers(*pr, solo) == ""
}
