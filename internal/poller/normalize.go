package poller

import (
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const mergedDays = 7

type repoName struct {
	NameWithOwner string `json:"nameWithOwner"`
}

type numberRepo struct {
	Number     int       `json:"number"`
	Repository *repoName `json:"repository"`
}

type closeRef struct {
	Number     int         `json:"number"`
	Repository *repoName   `json:"repository"`
	Parent     *numberRepo `json:"parent"`
}

type nodes[T any] struct {
	Nodes    []*T `json:"nodes"`
	PageInfo struct {
		HasNextPage bool   `json:"hasNextPage"`
		EndCursor   string `json:"endCursor"`
	} `json:"pageInfo"`
}

func (n *nodes[T]) list() []*T {
	if n == nil {
		return nil
	}
	out := make([]*T, 0, len(n.Nodes))
	for _, x := range n.Nodes {
		if x != nil {
			out = append(out, x)
		}
	}
	return out
}

type gqlLabel struct {
	Name string `json:"name"`
}

type gqlSub struct {
	Number     int       `json:"number"`
	Title      string    `json:"title"`
	State      string    `json:"state"`
	Repository *repoName `json:"repository"`
}

type gqlBlocker struct {
	Number     int       `json:"number"`
	State      string    `json:"state"`
	Repository *repoName `json:"repository"`
}

type gqlPR struct {
	Number            int    `json:"number"`
	URL               string `json:"url"`
	IsDraft           bool   `json:"isDraft"`
	State             string `json:"state"`
	MergedAt          string `json:"mergedAt"`
	HeadRefName       string `json:"headRefName"`
	HeadRefOid        string `json:"headRefOid"`
	ReviewDecision    string `json:"reviewDecision"`
	Mergeable         string `json:"mergeable"`
	StatusCheckRollup *struct {
		State string `json:"state"`
	} `json:"statusCheckRollup"`
	// open PRs
	Title                    string `json:"title"`
	UpdatedAt                string `json:"updatedAt"`
	Body                     string `json:"body"`
	LatestOpinionatedReviews *nodes[struct {
		State  string `json:"state"`
		Author *struct {
			Login string `json:"login"`
		} `json:"author"`
	}] `json:"latestOpinionatedReviews"`
	Checks *struct {
		Contexts *struct {
			TotalCount int `json:"totalCount"`
		} `json:"contexts"`
	} `json:"checks"`
	ReviewThreads *nodes[struct {
		IsResolved bool `json:"isResolved"`
		IsOutdated bool `json:"isOutdated"`
	}] `json:"reviewThreads"`
	ClosingIssuesReferences *nodes[closeRef] `json:"closingIssuesReferences"`
}

type gqlIssue struct {
	Number                         int                `json:"number"`
	Title                          string             `json:"title"`
	State                          string             `json:"state"`
	Labels                         *nodes[gqlLabel]   `json:"labels"`
	Parent                         *numberRepo        `json:"parent"`
	SubIssues                      *nodes[gqlSub]     `json:"subIssues"`
	BlockedBy                      *nodes[gqlBlocker] `json:"blockedBy"`
	ClosedByPullRequestsReferences *nodes[gqlPR]      `json:"closedByPullRequestsReferences"`
	ProjectItems                   *nodes[struct {
		FieldValueByName *struct {
			Name string `json:"name"`
		} `json:"fieldValueByName"`
	}] `json:"projectItems"`
}

type gqlMerged struct {
	Number                  int              `json:"number"`
	Title                   string           `json:"title"`
	URL                     string           `json:"url"`
	MergedAt                string           `json:"mergedAt"`
	HeadRefName             string           `json:"headRefName"`
	HeadRefOid              string           `json:"headRefOid"`
	Body                    string           `json:"body"`
	ClosingIssuesReferences *nodes[closeRef] `json:"closingIssuesReferences"`
}

type gqlEpic struct {
	Number    int              `json:"number"`
	Labels    *nodes[gqlLabel] `json:"labels"`
	SubIssues *nodes[gqlSub]   `json:"subIssues"`
}

type gqlRepo struct {
	Issues      *nodes[gqlIssue]  `json:"issues"`
	ClosedEpics *nodes[gqlEpic]   `json:"closedEpics"`
	MergedPRs   *nodes[gqlMerged] `json:"mergedPrs"`
	OpenPRs     *nodes[gqlPR]     `json:"openPrs"`
}

// response is the envelope of a poller query.
type response struct {
	Data struct {
		Repository *gqlRepo `json:"repository"`
	} `json:"data"`
}

var (
	errNoRepo = errors.New("no repository in the GraphQL response")

	reCloses = regexp.MustCompile(`(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b`)
	reBranch = regexp.MustCompile(`^issue-(\d+)(?:-|$)`)
)

var reviewMap = map[string]string{"APPROVED": "approved", "CHANGES_REQUESTED": "changes_requested", "REVIEW_REQUIRED": "review_required"}
var ciMap = map[string]string{"SUCCESS": "success", "FAILURE": "failure", "ERROR": "failure", "PENDING": "pending", "EXPECTED": "pending"}

func refOf(repo string, n int, r *repoName) Ref {
	if r != nil && r.NameWithOwner != "" {
		return Ref{Repo: r.NameWithOwner, N: n}
	}
	return Ref{Repo: repo, N: n}
}

func closedSubs(repo string, subs *nodes[gqlSub]) []ClosedSub {
	out := []ClosedSub{}
	for _, s := range subs.list() {
		if s.State == "CLOSED" {
			out = append(out, ClosedSub{Ref: refOf(repo, s.Number, s.Repository), Title: s.Title})
		}
	}
	return out
}

func prOf(n *gqlPR) PR {
	ci := "none"
	if n.StatusCheckRollup != nil {
		if v, ok := ciMap[strings.ToUpper(n.StatusCheckRollup.State)]; ok {
			ci = v
		}
	}
	review := "none" // the repo has no review rule
	if v, ok := reviewMap[n.ReviewDecision]; ok {
		review = v
	}
	return PR{
		N: n.Number, URL: n.URL, Draft: n.IsDraft, State: n.State, MergedAt: n.MergedAt,
		Head: n.HeadRefName, SHA: n.HeadRefOid, CI: ci, Review: review,
		Conflict: n.Mergeable == "CONFLICTING", // UNKNOWN while GitHub computes it: not a conflict
	}
}

// refsOf: issue numbers a PR is for (GitHub links "Closes #n" only for PRs into the default
// branch): ordered unique union of closing references, closing keywords in the body, the branch.
func refsOf(links *nodes[closeRef], body, head string) []int {
	out := []int{}
	seen := map[int]bool{}
	add := func(n int) {
		if !seen[n] {
			seen[n] = true
			out = append(out, n)
		}
	}
	for _, c := range links.list() {
		add(c.Number)
	}
	for _, m := range reCloses.FindAllStringSubmatch(body, -1) {
		n, _ := strconv.Atoi(m[1])
		add(n)
	}
	if m := reBranch.FindStringSubmatch(head); m != nil {
		n, _ := strconv.Atoi(m[1])
		add(n)
	}
	return out
}

func openExtra(n *gqlPR, review string) (reviewer *string, approved, changes bool, checks, threads int) {
	reviews := n.LatestOpinionatedReviews.list()
	for _, r := range reviews {
		if r.State == "APPROVED" && r.Author != nil {
			l := r.Author.Login
			reviewer = &l
		} else if r.State == "APPROVED" {
			reviewer = nil
		}
		if r.State == "CHANGES_REQUESTED" {
			changes = true
		}
	}
	changes = changes || review == "changes_requested"
	approved = !changes && (review == "approved" || (review == "none" && reviewer != nil && *reviewer != ""))
	for _, t := range n.ReviewThreads.list() {
		if !t.IsResolved && !t.IsOutdated {
			threads++
		}
	}
	if n.Checks != nil && n.Checks.Contexts != nil {
		checks = n.Checks.Contexts.TotalCount
	}
	return
}

func parseTime(s string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339, s)
	return t, err == nil
}

// normalize turns the full-query response into Data. repo is the polled "owner/name": the repo of
// every Ref GitHub did not qualify. projects maps issue number -> raw Status option name.
func normalize(repo string, resp *response, projects map[int]string, now time.Time) (Data, error) {
	r := resp.Data.Repository
	if r == nil {
		return Data{}, errNoRepo
	}
	d := EmptyData()
	for _, i := range r.Issues.list() {
		is := Issue{
			N: i.Number, Title: i.Title, State: i.State, Labels: []string{}, SubIssues: []Ref{},
			ClosedSubs: closedSubs(repo, i.SubIssues), BlockedBy: []Blocker{}, PRs: []PR{},
		}
		if is.State == "" {
			is.State = "OPEN"
		}
		for _, l := range i.Labels.list() {
			if l.Name != "" {
				is.Labels = append(is.Labels, l.Name)
			}
		}
		for _, l := range is.Labels {
			if strings.HasPrefix(strings.ToLower(l), "priority:") {
				if p := strings.TrimSpace(l[strings.Index(l, ":")+1:]); p != "" {
					is.Priority = &p
				}
				break
			}
		}
		if i.Parent != nil {
			p := refOf(repo, i.Parent.Number, i.Parent.Repository)
			is.Parent = &p
		}
		for _, s := range i.SubIssues.list() {
			is.SubIssues = append(is.SubIssues, refOf(repo, s.Number, s.Repository))
		}
		for _, b := range i.BlockedBy.list() {
			is.BlockedBy = append(is.BlockedBy, Blocker{Ref: refOf(repo, b.Number, b.Repository), State: b.State})
		}
		for _, p := range i.ClosedByPullRequestsReferences.list() {
			is.PRs = append(is.PRs, prOf(p))
		}
		if v, ok := projects[i.Number]; ok {
			is.ProjectStatus = v
		}
		d.Issues = append(d.Issues, is)
	}
	byN := map[int]*Issue{}
	for i := range d.Issues {
		byN[d.Issues[i].N] = &d.Issues[i]
	}

	cutoff := now.Add(-mergedDays * 24 * time.Hour)
	for _, p := range r.MergedPRs.list() {
		at, ok := parseTime(p.MergedAt)
		if !ok || at.Before(cutoff) {
			continue
		}
		closes := refsOf(p.ClosingIssuesReferences, p.Body, p.HeadRefName)
		var epic *Ref
		if len(closes) > 0 {
			for _, c := range p.ClosingIssuesReferences.list() {
				if c.Number == closes[0] && c.Parent != nil {
					e := refOf(repo, c.Parent.Number, c.Parent.Repository)
					epic = &e
				}
			}
			if epic == nil { // not linked by GitHub: the issue, still open, names its epic
				if is := byN[closes[0]]; is != nil && is.Parent != nil {
					e := *is.Parent
					epic = &e
				}
			}
		}
		d.Merged = append(d.Merged, Merged{
			N: p.Number, Title: p.Title, URL: p.URL, MergedAt: p.MergedAt, Head: p.HeadRefName,
			Closes: closes, Epic: epic, SHA: p.HeadRefOid,
		})
	}

	for _, node := range r.OpenPRs.list() {
		pr := prOf(node)
		pr.State = "OPEN"
		pr.MergedAt = ""
		refs := refsOf(node.ClosingIssuesReferences, node.Body, node.HeadRefName)
		for _, n := range refs { // attach to its issue when GitHub did not
			if is := byN[n]; is != nil && !hasPR(is.PRs, pr.N) {
				is.PRs = append(is.PRs, pr)
			}
		}
		reviewer, approved, changes, checks, threads := openExtra(node, pr.Review)
		d.OpenPRs = append(d.OpenPRs, OpenPR{
			N: pr.N, Title: node.Title, URL: pr.URL, Draft: pr.Draft, Head: pr.Head, SHA: pr.SHA,
			CI: pr.CI, Review: pr.Review, Conflict: pr.Conflict, Refs: refs, UpdatedAt: node.UpdatedAt,
			Reviewer: reviewer, Approved: approved, ChangesRequested: changes, Checks: checks, ThreadsOpen: threads,
		})
	}
	for _, m := range d.Merged { // a PR merged into a non-default branch leaves its issue open: mark it merged there
		for _, n := range m.Closes {
			if is := byN[n]; is != nil && !hasPR(is.PRs, m.N) {
				is.PRs = append(is.PRs, PR{
					N: m.N, URL: m.URL, State: "MERGED", MergedAt: m.MergedAt, Head: m.Head,
					CI: "success", Review: "none",
				})
			}
		}
	}
	for i := range d.Issues {
		finishStatus(&d.Issues[i])
	}
	for _, e := range r.ClosedEpics.list() {
		ce := ClosedEpic{N: e.Number, Labels: []string{}, ClosedSubs: closedSubs(repo, e.SubIssues)}
		for _, l := range e.Labels.list() {
			if l.Name != "" {
				ce.Labels = append(ce.Labels, l.Name)
			}
		}
		d.ClosedEpics = append(d.ClosedEpics, ce)
	}
	d.IssuesTruncated = r.Issues != nil && r.Issues.PageInfo.HasNextPage
	return d, nil
}

func hasPR(prs []PR, n int) bool {
	for _, p := range prs {
		if p.N == n {
			return true
		}
	}
	return false
}

// CanonicalStatus maps a project Status option name to one of the five board statuses
// (case-insensitive, underscores and dashes as spaces), or "".
func CanonicalStatus(name string) string {
	k := strings.ToLower(strings.Join(strings.Fields(strings.NewReplacer("_", " ", "-", " ").Replace(name)), " "))
	for _, s := range []string{StatusBacklog, StatusReady, StatusInProgress, StatusInReview, StatusDone} {
		if strings.ToLower(s) == k {
			return s
		}
	}
	return ""
}

// DerivedStatus is the board status from labels, blockers and PRs alone (G§3): a merged PR is
// Done, an open PR In review, `refined` with no open blocker Ready, else Backlog.
func DerivedStatus(is Issue) string {
	open := false
	for _, p := range is.PRs {
		switch p.State {
		case "MERGED":
			return StatusDone
		case "OPEN":
			open = true
		}
	}
	if open {
		return StatusInReview
	}
	refined := false
	for _, l := range is.Labels {
		if l == "refined" {
			refined = true
		}
	}
	if refined {
		for _, b := range is.BlockedBy {
			if b.State == "OPEN" {
				return StatusBacklog
			}
		}
		return StatusReady
	}
	return StatusBacklog
}

func finishStatus(is *Issue) {
	if c := CanonicalStatus(is.ProjectStatus); c != "" {
		is.Status = c
		return
	}
	is.Status = DerivedStatus(*is)
}
