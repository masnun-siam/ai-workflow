package gh

import (
	"context"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
)

// Popup caps (G§1.2).
const (
	MaxComments   = 100
	PRPage        = 100
	MaxPatch      = 60_000
	MaxPatchTotal = 500_000
)

const htmlHeader = "Accept: application/vnd.github.html+json"

var (
	reName    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)
	reRepo    = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	reLinkTag = regexp.MustCompile(`<a\s`)
)

// ValidIssueID checks owner, repo and a decimal number.
func ValidIssueID(owner, repo, n string) bool {
	if !reName.MatchString(owner) || !reName.MatchString(repo) || n == "" {
		return false
	}
	for _, r := range n {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func linksOut(html string) string {
	return reLinkTag.ReplaceAllString(html, `<a target="_blank" rel="noopener noreferrer" `)
}

type restUser struct {
	Login string `json:"login"`
}

func userName(u *restUser) string {
	if u == nil || u.Login == "" {
		return "ghost"
	}
	return u.Login
}

type restLabel struct {
	Name  string `json:"name"`
	Color string `json:"color"`
}

type restComment struct {
	User      *restUser `json:"user"`
	CreatedAt string    `json:"created_at"`
	BodyHTML  string    `json:"body_html"`
}

// IssueView is the issue popup (G§1.2).
type IssueView struct {
	Number       int           `json:"number"`
	Title        string        `json:"title"`
	URL          string        `json:"url"`
	State        string        `json:"state"`
	StateReason  *string       `json:"state_reason"`
	IsPR         bool          `json:"is_pr"`
	Merged       bool          `json:"merged"`
	Author       string        `json:"author"`
	CreatedAt    string        `json:"created_at"`
	Labels       []LabelView   `json:"labels"`
	Assignees    []string      `json:"assignees"`
	Milestone    *string       `json:"milestone"`
	BodyHTML     string        `json:"body_html"`
	CommentCount int           `json:"comment_count"`
	Comments     []CommentView `json:"comments"`
}

type LabelView struct {
	Name  string `json:"name"`
	Color string `json:"color"`
}

type CommentView struct {
	Author    string `json:"author"`
	CreatedAt string `json:"created_at"`
	BodyHTML  string `json:"body_html"`
}

type restIssue struct {
	Number      int     `json:"number"`
	Title       string  `json:"title"`
	HTMLURL     string  `json:"html_url"`
	State       string  `json:"state"`
	StateReason *string `json:"state_reason"`
	PullRequest *struct {
		MergedAt *string `json:"merged_at"`
	} `json:"pull_request"`
	User      *restUser `json:"user"`
	CreatedAt string    `json:"created_at"`
	Labels    []restLabel
	Assignees []*restUser
	Milestone *struct {
		Title string `json:"title"`
	} `json:"milestone"`
	BodyHTML string `json:"body_html"`
	Comments *int   `json:"comments"`
}

// notFoundOrUpstream maps a failed REST read: 404 when gh says Not Found / HTTP 404.
func notFoundOrUpstream(res execx.Result, notFound, fallback string) error {
	text := strings.TrimSpace(string(res.Stderr))
	if text == "" {
		text = strings.TrimSpace(string(res.Stdout))
	}
	if strings.Contains(text, "Not Found") || strings.Contains(text, "HTTP 404") {
		return errs.NotFound("%s", notFound)
	}
	if text == "" {
		return errs.Upstream("%s", fallback)
	}
	lines := strings.Split(text, "\n")
	return errs.Upstream("%s", strings.TrimSpace(lines[len(lines)-1]))
}

func lastLineOr(res execx.Result, fallback string) string {
	text := strings.TrimSpace(string(res.Stderr))
	if text == "" {
		return fallback
	}
	lines := strings.Split(text, "\n")
	return strings.TrimSpace(lines[len(lines)-1])
}

func splitSlug(slug string) (owner, repo string, err error) {
	o, r, ok := strings.Cut(slug, "/")
	if !ok || !reName.MatchString(o) || !reName.MatchString(r) {
		return "", "", errs.Invalid("bad issue id")
	}
	return o, r, nil
}

// IssuePopup reads an issue and its first 100 comments with GitHub-rendered HTML.
func IssuePopup(ctx context.Context, c Client, slug string, n int) (IssueView, error) {
	owner, repo, err := splitSlug(slug)
	if err != nil || n < 1 {
		return IssueView{}, errs.Invalid("bad issue id")
	}
	base := "repos/" + owner + "/" + repo + "/issues/" + itoa(n)
	var issue restIssue
	res, err := c.JSON(ctx, []string{"api", "-H", htmlHeader, base}, 30*time.Second, &issue)
	if err != nil {
		return IssueView{}, notFoundOrUpstream(res, "Issue not found, or this gh login cannot see the repo.", "gh could not read the issue")
	}
	var comments []restComment
	res, err = c.JSON(ctx, []string{"api", "-H", htmlHeader, base + "/comments?per_page=" + itoa(MaxComments)}, 30*time.Second, &comments)
	if err != nil {
		return IssueView{}, errs.Upstream("%s", lastLineOr(res, "gh could not read the comments"))
	}
	v := IssueView{
		Number: issue.Number, Title: issue.Title, URL: issue.HTMLURL, State: issue.State,
		StateReason: issue.StateReason, IsPR: issue.PullRequest != nil,
		Merged: issue.PullRequest != nil && issue.PullRequest.MergedAt != nil && *issue.PullRequest.MergedAt != "",
		Author: userName(issue.User), CreatedAt: issue.CreatedAt,
		Labels: []LabelView{}, Assignees: []string{}, Comments: []CommentView{},
		BodyHTML: linksOut(issue.BodyHTML), CommentCount: len(comments),
	}
	if issue.Comments != nil {
		v.CommentCount = *issue.Comments
	}
	for _, l := range issue.Labels {
		v.Labels = append(v.Labels, LabelView(l))
	}
	for _, a := range issue.Assignees {
		v.Assignees = append(v.Assignees, userName(a))
	}
	if issue.Milestone != nil {
		t := issue.Milestone.Title
		v.Milestone = &t
	}
	for _, cm := range comments {
		v.Comments = append(v.Comments, CommentView{Author: userName(cm.User), CreatedAt: cm.CreatedAt, BodyHTML: linksOut(cm.BodyHTML)})
	}
	return v, nil
}

// OpenItem is a row of the New-run picker.
type OpenItem struct {
	Number    int      `json:"number"`
	Title     string   `json:"title"`
	Labels    []string `json:"labels"`
	UpdatedAt string   `json:"updated_at"`
	Draft     bool     `json:"draft"`
	URL       string   `json:"url,omitempty"`
}

// OpenItems lists the repo's open issues or PRs (one page of 100), most recently updated first.
func OpenItems(ctx context.Context, c Client, slug, kind string) ([]OpenItem, error) {
	fields := map[string]string{"issue": "number,title,labels,updatedAt,url", "pr": "number,title,labels,updatedAt,url,isDraft"}[kind]
	if fields == "" {
		return nil, errs.Invalid("kind must be issue or pr")
	}
	if !reRepo.MatchString(slug) {
		return nil, errs.Invalid("bad repo")
	}
	var rows []struct {
		Number *int   `json:"number"`
		Title  string `json:"title"`
		Labels []struct {
			Name string `json:"name"`
		} `json:"labels"`
		UpdatedAt string `json:"updatedAt"`
		IsDraft   bool   `json:"isDraft"`
		URL       string `json:"url"`
	}
	res, err := c.JSON(ctx, []string{kind, "list", "--repo", slug, "--state", "open", "--limit", "100", "--json", fields}, 30*time.Second, &rows)
	if err != nil {
		return nil, errs.Upstream("%s", lastLineOr(res, "gh could not list them"))
	}
	items := []OpenItem{}
	for _, r := range rows {
		if r.Number == nil {
			continue
		}
		it := OpenItem{Number: *r.Number, Title: r.Title, Labels: []string{}, UpdatedAt: r.UpdatedAt, Draft: r.IsDraft}
		for _, l := range r.Labels {
			if l.Name != "" {
				it.Labels = append(it.Labels, l.Name)
			}
		}
		if strings.HasPrefix(r.URL, "https://") {
			it.URL = r.URL
		}
		items = append(items, it)
	}
	sort.SliceStable(items, func(i, j int) bool { return items[i].UpdatedAt > items[j].UpdatedAt })
	return items, nil
}

// BranchList is every branch of a repo, the default first.
type BranchList struct {
	Branches []string `json:"branches"`
	Default  string   `json:"default"`
}

// Branches lists a repo's branches: the default first, the rest sorted. Never cached.
func Branches(ctx context.Context, c Client, slug string) (BranchList, error) {
	parts := strings.Split(slug, "/")
	bad := !reRepo.MatchString(slug)
	for _, p := range parts {
		if p == "." || p == ".." {
			bad = true
		}
	}
	if bad {
		return BranchList{}, errs.Invalid("repo must be owner/name")
	}
	d := c.Run(ctx, []string{"repo", "view", slug, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"}, execx.Opts{Timeout: 30 * time.Second})
	def := strings.TrimSpace(string(d.Stdout))
	if d.Code != 0 || def == "" {
		return BranchList{}, errs.Upstream("%s", ghError(d))
	}
	b := c.Run(ctx, []string{"api", "repos/" + slug + "/branches", "--paginate", "--jq", ".[].name"}, execx.Opts{Timeout: 60 * time.Second})
	if b.Code != 0 {
		return BranchList{}, errs.Upstream("%s", ghError(b))
	}
	set := map[string]bool{}
	for _, n := range strings.Fields(string(b.Stdout)) {
		if n != def {
			set[n] = true
		}
	}
	rest := make([]string, 0, len(set))
	for n := range set {
		rest = append(rest, n)
	}
	sort.Strings(rest)
	return BranchList{Branches: append([]string{def}, rest...), Default: def}, nil
}

// ghError is the last line of stderr, else stdout, at most 200 chars; "gh did not answer" if blank.
func ghError(r execx.Result) string {
	for _, b := range [][]byte{r.Stderr, r.Stdout} {
		t := strings.TrimSpace(string(b))
		if t != "" {
			lines := strings.Split(t, "\n")
			return trunc(strings.TrimSpace(lines[len(lines)-1]), 200)
		}
	}
	return "gh did not answer"
}

// ---- PR popup ----

// PRView is the pull request popup.
type PRView struct {
	Number       int          `json:"number"`
	Title        string       `json:"title"`
	URL          string       `json:"url"`
	State        string       `json:"state"` // open | closed | merged | draft
	Conflict     bool         `json:"conflict"`
	Head         string       `json:"head"`
	Base         string       `json:"base"`
	HeadSHA      string       `json:"head_sha"`
	Author       string       `json:"author"`
	CreatedAt    string       `json:"created_at"`
	BodyHTML     string       `json:"body_html"`
	Additions    int          `json:"additions"`
	Deletions    int          `json:"deletions"`
	Files        []PRFile     `json:"files"`
	Commits      []PRCommit   `json:"commits"`
	Conversation []PRConvItem `json:"conversation"`
	Checks       []PRCheck    `json:"checks"`
}

type PRFile struct {
	Path      string  `json:"path"`
	Additions int     `json:"additions"`
	Deletions int     `json:"deletions"`
	Status    string  `json:"status"`
	Patch     *string `json:"patch"`
	PatchCut  bool    `json:"patch_cut,omitempty"`
}

type PRCommit struct {
	SHA     string `json:"sha"`
	Message string `json:"message"`
	Author  string `json:"author"`
}

type PRConvItem struct {
	Kind     string `json:"kind"` // comment | review
	Author   string `json:"author"`
	At       string `json:"at"`
	State    string `json:"state,omitempty"`
	BodyHTML string `json:"body_html"`
}

type PRCheck struct {
	Name   string `json:"name"`
	Bucket string `json:"bucket"` // green | red | pending
	Link   string `json:"link"`
}

var failingConclusions = map[string]bool{"FAILURE": true, "TIMED_OUT": true, "CANCELLED": true, "ACTION_REQUIRED": true, "STARTUP_FAILURE": true, "ERROR": true}

// PRPopup runs the six reads in parallel (40 s each) and shapes them.
func PRPopup(ctx context.Context, c Client, slug string, n int) (PRView, error) {
	owner, repo, err := splitSlug(slug)
	if err != nil || n < 1 {
		return PRView{}, errs.Invalid("bad issue id")
	}
	base := "repos/" + owner + "/" + repo + "/pulls/" + itoa(n)
	calls := [][]string{
		{"api", "-H", htmlHeader, base},
		{"api", base + "/files?per_page=" + itoa(PRPage)},
		{"api", base + "/commits?per_page=" + itoa(PRPage)},
		{"api", "-H", htmlHeader, "repos/" + owner + "/" + repo + "/issues/" + itoa(n) + "/comments?per_page=" + itoa(PRPage)},
		{"api", "-H", htmlHeader, base + "/reviews?per_page=" + itoa(PRPage)},
		{"pr", "view", itoa(n), "-R", slug, "--json", "statusCheckRollup"},
	}
	var (
		pr struct {
			Number    int       `json:"number"`
			Title     string    `json:"title"`
			HTMLURL   string    `json:"html_url"`
			State     string    `json:"state"`
			Draft     bool      `json:"draft"`
			Merged    bool      `json:"merged"`
			MergedAt  *string   `json:"merged_at"`
			User      *restUser `json:"user"`
			CreatedAt string    `json:"created_at"`
			Head      struct {
				Ref string `json:"ref"`
				SHA string `json:"sha"`
			} `json:"head"`
			Base struct {
				Ref string `json:"ref"`
			} `json:"base"`
			MergeableState string `json:"mergeable_state"`
			BodyHTML       string `json:"body_html"`
			Additions      int    `json:"additions"`
			Deletions      int    `json:"deletions"`
		}
		files []struct {
			Filename  string  `json:"filename"`
			Status    string  `json:"status"`
			Additions int     `json:"additions"`
			Deletions int     `json:"deletions"`
			Patch     *string `json:"patch"`
		}
		commits []struct {
			SHA    string    `json:"sha"`
			Author *restUser `json:"author"`
			Commit struct {
				Message string `json:"message"`
				Author  struct {
					Name string `json:"name"`
				} `json:"author"`
			} `json:"commit"`
		}
		comments []restComment
		reviews  []struct {
			User        *restUser `json:"user"`
			State       string    `json:"state"`
			SubmittedAt string    `json:"submitted_at"`
			BodyHTML    string    `json:"body_html"`
		}
		rollup struct {
			StatusCheckRollup []struct {
				Typename   string `json:"__typename"`
				Name       string `json:"name"`
				DetailsURL string `json:"detailsUrl"`
				Status     string `json:"status"`
				Conclusion string `json:"conclusion"`
				Context    string `json:"context"`
				TargetURL  string `json:"targetUrl"`
				State      string `json:"state"`
			} `json:"statusCheckRollup"`
		}
	)
	targets := []any{&pr, &files, &commits, &comments, &reviews, &rollup}
	results := make([]execx.Result, len(calls))
	errsOut := make([]error, len(calls))
	var wg sync.WaitGroup
	for i := range calls {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			results[i], errsOut[i] = c.JSON(ctx, calls[i], 40*time.Second, targets[i])
		}(i)
	}
	wg.Wait()
	if errsOut[0] != nil {
		return PRView{}, notFoundOrUpstream(results[0], "Pull request not found, or this gh login cannot see the repo.", "gh could not read the pull request")
	}
	for i, name := range map[int]string{1: "files", 2: "commits", 3: "comments", 4: "reviews"} {
		if errsOut[i] != nil {
			return PRView{}, errs.Upstream("%s", lastLineOr(results[i], "gh could not read the "+name))
		}
	}
	state := pr.State
	switch {
	case pr.Merged || (pr.MergedAt != nil && *pr.MergedAt != ""):
		state = "merged"
	case pr.Draft && pr.State == "open":
		state = "draft"
	case state == "":
		state = "open"
	}
	v := PRView{
		Number: pr.Number, Title: pr.Title, URL: pr.HTMLURL, State: state, Conflict: pr.MergeableState == "dirty",
		Head: pr.Head.Ref, Base: pr.Base.Ref, HeadSHA: pr.Head.SHA, Author: userName(pr.User), CreatedAt: pr.CreatedAt,
		BodyHTML: linksOut(pr.BodyHTML), Additions: pr.Additions, Deletions: pr.Deletions,
		Files: []PRFile{}, Commits: []PRCommit{}, Conversation: []PRConvItem{}, Checks: []PRCheck{},
	}
	budget := MaxPatchTotal
	for _, f := range files {
		pf := PRFile{Path: f.Filename, Additions: f.Additions, Deletions: f.Deletions, Status: f.Status}
		if f.Patch != nil {
			l := len([]rune(*f.Patch))
			if l > MaxPatch || l > budget {
				pf.PatchCut = true
			} else {
				budget -= l
				p := *f.Patch
				pf.Patch = &p
			}
		}
		v.Files = append(v.Files, pf)
	}
	for _, cm := range commits {
		msg, _, _ := strings.Cut(cm.Commit.Message, "\n")
		author := "ghost"
		switch {
		case cm.Author != nil:
			author = userName(cm.Author)
		case cm.Commit.Author.Name != "":
			author = cm.Commit.Author.Name
		}
		sha := cm.SHA
		if len(sha) > 7 {
			sha = sha[:7]
		}
		v.Commits = append(v.Commits, PRCommit{SHA: sha, Message: msg, Author: author})
	}
	for _, cm := range comments {
		v.Conversation = append(v.Conversation, PRConvItem{Kind: "comment", Author: userName(cm.User), At: cm.CreatedAt, BodyHTML: linksOut(cm.BodyHTML)})
	}
	for _, r := range reviews {
		if r.State == "PENDING" || (r.BodyHTML == "" && r.State == "COMMENTED") {
			continue
		}
		v.Conversation = append(v.Conversation, PRConvItem{Kind: "review", Author: userName(r.User), At: r.SubmittedAt, State: r.State, BodyHTML: linksOut(r.BodyHTML)})
	}
	sort.SliceStable(v.Conversation, func(i, j int) bool { return v.Conversation[i].At < v.Conversation[j].At })
	if errsOut[5] == nil {
		for _, it := range rollup.StatusCheckRollup {
			var name, link, result string
			var done bool
			if it.Typename == "StatusContext" {
				name, link, result = it.Context, it.TargetURL, it.State
				done = result != "PENDING" && result != "EXPECTED"
			} else {
				name, link, result = it.Name, it.DetailsURL, it.Conclusion
				done = it.Status == "COMPLETED"
			}
			bucket := "green"
			switch {
			case !done:
				bucket = "pending"
			case failingConclusions[result]:
				bucket = "red"
			}
			v.Checks = append(v.Checks, PRCheck{Name: name, Bucket: bucket, Link: link})
		}
	}
	return v, nil
}
