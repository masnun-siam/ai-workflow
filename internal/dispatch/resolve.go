package dispatch

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
)

// Limits and texts of the resolver and the preview (W§2.6).
const (
	MaxIssues       = 30
	MaxChildPages   = 20
	ghTimeout       = 60 * time.Second
	ghTickTimeout   = 120 * time.Second
	readinessLow    = 2
	readinessMax    = 30
	readinessWork   = 5
	readinessWait   = 8 * time.Second
	NoReviewer      = "no Slack channel or reviewer, its lanes skip grinding"
	readinessQ      = "How clearly does this issue state what to build?"
	maxIssueBodyLen = 20000
)

var readinessLevels = []string{
	"no clear outcome",
	"an outcome, but no acceptance criteria and no approach",
	"an outcome and some acceptance criteria, approach unclear",
	"outcome and acceptance criteria clear, approach partly clear",
	"outcome, acceptance criteria and approach all clear",
}

var (
	reEpic  = regexp.MustCompile(`^(?:([\w.-]+/[\w.-]+)#)?(\d+)$`)
	reIssue = regexp.MustCompile(`^([\w.-]+/[\w.-]+)#(\d+)$`)
)

const childrenQuery = `
query($owner: String!, $name: String!, $n: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $n) {
      title
      subIssues(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          number title %sstate repository { nameWithOwner }
          labels(first: 100) { nodes { name } }
          blockedBy(first: 100) { nodes { number state repository { nameWithOwner } } }
        }
      }
    }
  }
}
`

type gqlNode struct {
	Number     int    `json:"number"`
	Title      string `json:"title"`
	Body       string `json:"body"`
	State      string `json:"state"`
	Repository struct {
		NameWithOwner string `json:"nameWithOwner"`
	} `json:"repository"`
	Labels struct {
		Nodes []struct {
			Name string `json:"name"`
		} `json:"nodes"`
	} `json:"labels"`
	BlockedBy struct {
		Nodes []struct {
			Number     int    `json:"number"`
			State      string `json:"state"`
			Repository struct {
				NameWithOwner string `json:"nameWithOwner"`
			} `json:"repository"`
		} `json:"nodes"`
	} `json:"blockedBy"`
}

// Resolved is an epic or a pick read from GitHub.
type Resolved struct {
	Epic     *string
	Title    string
	Children []Child
	Outside  map[string][]string // lane key -> open blockers outside the set
	Closed   []string            // listed issues that are closed (pick only)
	Issues   []string            // the pick's keys
	Bodies   map[string]string   // only when asked for; never stored in a lane or a record
}

// child converts one node and reports its open blockers outside keys.
func child(x gqlNode, keys map[string]bool) (Child, []string) {
	var deps, ext []string
	for _, b := range x.BlockedBy.Nodes {
		bk := store.Key(b.Repository.NameWithOwner, b.Number)
		if keys[bk] {
			deps = append(deps, bk)
		} else if b.State == "OPEN" {
			ext = append(ext, bk)
		}
	}
	c := Child{Repo: x.Repository.NameWithOwner, N: x.Number, Title: x.Title}
	for _, l := range x.Labels.Nodes {
		c.Refined = c.Refined || l.Name == "refined"
	}
	sort.Strings(deps)
	if deps == nil {
		deps = []string{}
	}
	c.Deps = deps
	return c, ext
}

func children(nodes []gqlNode) ([]Child, map[string][]string, map[string]string) {
	keys := map[string]bool{}
	for _, x := range nodes {
		keys[store.Key(x.Repository.NameWithOwner, x.Number)] = true
	}
	out := []Child{}
	outside := map[string][]string{}
	bodies := map[string]string{}
	for _, x := range nodes {
		c, ext := child(x, keys)
		k := store.Key(c.Repo, c.N)
		if len(ext) > 0 {
			outside[k] = ext
		}
		bodies[k] = x.Body
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].N != out[j].N {
			return out[i].N < out[j].N
		}
		return out[i].Repo < out[j].Repo
	})
	return out, outside, bodies
}

// ParseEpic reads "owner/repo#n" or "n" (the repo of the current directory, via gh).
func (s *Service) ParseEpic(ctx context.Context, text string) (string, int, error) {
	m := reEpic.FindStringSubmatch(strings.TrimSpace(text))
	if m == nil {
		return "", 0, errs.Invalid("epic must be owner/repo#N or N, got %q", text)
	}
	repo := m[1]
	if repo == "" {
		r := s.d.GH.Run(ctx, []string{"repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"}, execx.Opts{Timeout: ghTimeout})
		repo = strings.TrimSpace(string(r.Stdout))
		if r.Code != 0 || repo == "" {
			return "", 0, errs.Invalid("not in a GitHub checkout: give the epic as owner/repo#N")
		}
	}
	n, _ := strconv.Atoi(m[2])
	return repo, n, nil
}

// ResolveEpic reads the open sub-issues of an epic (one GraphQL call per 100, at most MaxChildPages).
func (s *Service) ResolveEpic(ctx context.Context, epic string, bodies bool) (Resolved, error) {
	repo, n, err := s.ParseEpic(ctx, epic)
	if err != nil {
		return Resolved{}, err
	}
	owner, name := splitSlug(repo)
	bodyField := ""
	if bodies {
		bodyField = "body "
	}
	query := fmt.Sprintf(childrenQuery, bodyField)
	var nodes []gqlNode
	var title string
	after := ""
	for page := 0; ; page++ {
		if page >= MaxChildPages {
			return Resolved{}, errs.Invalid("epic has too many sub-issues")
		}
		vars := map[string]any{"owner": owner, "name": name, "n": n}
		if after != "" {
			vars["after"] = after
		}
		var resp struct {
			Data struct {
				Repository struct {
					Issue *struct {
						Title     string `json:"title"`
						SubIssues struct {
							PageInfo struct {
								HasNextPage bool   `json:"hasNextPage"`
								EndCursor   string `json:"endCursor"`
							} `json:"pageInfo"`
							Nodes []gqlNode `json:"nodes"`
						} `json:"subIssues"`
					} `json:"issue"`
				} `json:"repository"`
			} `json:"data"`
		}
		if _, res, err := s.d.GH.GraphQL(ctx, query, vars, &resp); err != nil {
			return Resolved{}, errs.Upstream("cannot read epic %s#%d: %s", repo, n, trunc(strings.TrimSpace(string(res.Stderr))+" "+err.Error(), 200))
		}
		is := resp.Data.Repository.Issue
		if is == nil {
			return Resolved{}, errs.Invalid("epic not found")
		}
		title = is.Title
		for _, x := range is.SubIssues.Nodes {
			if x.State == "OPEN" {
				nodes = append(nodes, x)
			}
		}
		if !is.SubIssues.PageInfo.HasNextPage {
			break
		}
		after = is.SubIssues.PageInfo.EndCursor
	}
	kids, outside, b := children(nodes)
	epicKey := store.Key(repo, n)
	r := Resolved{Epic: &epicKey, Title: title, Children: kids, Outside: outside}
	if bodies {
		r.Bodies = b
	}
	return r, nil
}

// ParseIssues checks a pick: 1 to 30 "owner/repo#n" strings in one repo.
func ParseIssues(refs []string) (string, []int, error) {
	if len(refs) < 1 || len(refs) > MaxIssues {
		return "", nil, errs.Invalid("pick 1 to %d issues, got %d", MaxIssues, len(refs))
	}
	var repo string
	var nums []int
	for _, ref := range refs {
		m := reIssue.FindStringSubmatch(strings.TrimSpace(ref))
		if m == nil {
			return "", nil, errs.Invalid("issue must be owner/repo#N, got %q", ref)
		}
		if repo != "" && !strings.EqualFold(m[1], repo) {
			return "", nil, errs.Invalid("all issues must be in one repo, got %s and %s", repo, m[1])
		}
		if repo == "" {
			repo = m[1]
		}
		n, _ := strconv.Atoi(m[2])
		nums = append(nums, n)
	}
	return repo, nums, nil
}

func issuesQuery(nums []int, bodies bool) string {
	fields := ""
	if bodies {
		fields = "body "
	}
	fields += "number title state repository { nameWithOwner } labels(first: 100) { nodes { name } } " +
		"blockedBy(first: 100) { nodes { number state repository { nameWithOwner } } }"
	var al []string
	for i, n := range nums {
		al = append(al, fmt.Sprintf("i%d: issue(number: %d) { %s }", i, n, fields))
	}
	return "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { " + strings.Join(al, " ") + " } }"
}

// ResolveIssues reads a pick of issues in one repo. Closed ones go to Closed.
func (s *Service) ResolveIssues(ctx context.Context, refs []string, bodies bool) (Resolved, error) {
	repo, nums, err := ParseIssues(refs)
	if err != nil {
		return Resolved{}, err
	}
	owner, name := splitSlug(repo)
	var resp struct {
		Data struct {
			Repository map[string]json.RawMessage `json:"repository"`
		} `json:"data"`
	}
	if _, res, err := s.d.GH.GraphQL(ctx, issuesQuery(nums, bodies), map[string]any{"owner": owner, "name": name}, &resp); err != nil {
		return Resolved{}, errs.Upstream("cannot read issues in %s: %s", repo, trunc(strings.TrimSpace(string(res.Stderr))+" "+err.Error(), 200))
	}
	var open []gqlNode
	var closed []string
	for i, n := range nums {
		raw := resp.Data.Repository[fmt.Sprintf("i%d", i)]
		var x gqlNode
		if len(raw) == 0 || string(raw) == "null" || json.Unmarshal(raw, &x) != nil || x.Number == 0 {
			return Resolved{}, errs.Invalid("issue %s#%d not found", repo, n)
		}
		if x.State == "OPEN" {
			open = append(open, x)
		} else {
			closed = append(closed, store.Key(x.Repository.NameWithOwner, x.Number))
		}
	}
	kids, outside, b := children(open)
	keys := make([]string, 0, len(kids))
	for _, c := range kids {
		keys = append(keys, store.Key(c.Repo, c.N))
	}
	sort.Strings(closed)
	r := Resolved{Title: IssuesTitle(keys), Children: kids, Outside: outside, Closed: closed, Issues: keys}
	if bodies {
		r.Bodies = b
	}
	return r, nil
}

// branchSHA is the head of branch on repo, "" when it does not exist (or gh failed: fail safe).
func (s *Service) branchSHA(ctx context.Context, repo, branch string) string {
	r := s.d.GH.Run(ctx, []string{"api", "repos/" + repo + "/git/ref/heads/" + branch, "-q", ".object.sha"}, execx.Opts{Timeout: ghTimeout})
	if r.Code != 0 {
		return ""
	}
	return strings.TrimSpace(string(r.Stdout))
}

// MissingBase names each repo where base does not exist; nil when no base is set.
func (s *Service) MissingBase(ctx context.Context, repos []string, base string) []string {
	if base == "" {
		return nil
	}
	rs := append([]string(nil), repos...)
	sort.Strings(rs)
	var out []string
	for _, r := range rs {
		if s.branchSHA(ctx, r, base) == "" {
			out = append(out, r+": base branch "+base+" does not exist")
		}
	}
	return out
}

func (s *Service) defaultBranch(ctx context.Context, repo string) string {
	r := s.d.GH.Run(ctx, []string{"repo", "view", repo, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"}, execx.Opts{Timeout: ghTimeout})
	return strings.TrimSpace(string(r.Stdout))
}

// EnsureFeatureBranch cuts branch from base (else the default branch) on GitHub when missing.
func (s *Service) EnsureFeatureBranch(ctx context.Context, repo, branch, base string) (bool, error) {
	if s.d.GH.Run(ctx, []string{"api", "repos/" + repo + "/git/ref/heads/" + branch}, execx.Opts{Timeout: ghTimeout}).Code == 0 {
		return false, nil
	}
	var sha string
	if base != "" {
		sha = s.branchSHA(ctx, repo, base)
	} else {
		def := s.defaultBranch(ctx, repo)
		r := s.d.GH.Run(ctx, []string{"api", "repos/" + repo + "/commits/" + def, "-q", ".sha"}, execx.Opts{Timeout: ghTimeout})
		sha = strings.TrimSpace(string(r.Stdout))
	}
	r := s.d.GH.Run(ctx, []string{"api", "repos/" + repo + "/git/refs", "-f", "ref=refs/heads/" + branch, "-f", "sha=" + sha}, execx.Opts{Timeout: ghTimeout})
	if r.Code != 0 || sha == "" {
		msg := strings.TrimSpace(string(r.Stderr))
		if msg == "" {
			msg = strings.TrimSpace(string(r.Stdout))
		}
		return false, errs.Upstream("cannot create %s on %s: %s", branch, repo, trunc(msg, 200))
	}
	return true, nil
}

// ---- preview ----

// PlanLane is a lane of the preview.
type PlanLane struct {
	Key       string   `json:"key"`
	Title     string   `json:"title"`
	Refined   bool     `json:"refined"`
	Deps      []string `json:"deps"`
	Readiness *int     `json:"readiness"`
}

// PlanView is the body of POST /api/dispatches/plan and the output of `setu dispatch plan`.
type PlanView struct {
	Epic     *string        `json:"epic"`
	Issues   []string       `json:"issues,omitempty"`
	Title    string         `json:"title"`
	Settings store.Settings `json:"settings"`
	Lanes    []PlanLane     `json:"lanes"`
	Waves    [][]string     `json:"waves"`
	Warnings []string       `json:"warnings"`
}

func (s *Service) readiness(ctx context.Context, kids []Child, bodies map[string]string) (map[string]int, []string) {
	if s.d.Jev == nil || s.d.Jev.Status() != "ok" {
		return nil, nil
	}
	var refined, scored []string
	for _, c := range kids {
		if c.Refined {
			refined = append(refined, store.Key(c.Repo, c.N))
		}
	}
	for _, k := range refined {
		if _, ok := bodies[k]; ok && len(scored) < readinessMax {
			scored = append(scored, k)
		}
	}
	unavailable := map[string]bool{}
	in := map[string]bool{}
	for _, k := range scored {
		in[k] = true
	}
	for _, k := range refined {
		if !in[k] {
			unavailable[k] = true
		}
	}
	type res struct {
		k     string
		score int
		ok    bool
	}
	ch := make(chan res, len(scored))
	sem := make(chan struct{}, readinessWork)
	cctx, cancel := context.WithTimeout(ctx, readinessWait)
	defer cancel()
	var wg sync.WaitGroup
	for _, k := range scored {
		wg.Add(1)
		go func(k string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			body := bodies[k]
			if len(body) > maxIssueBodyLen {
				body = body[:maxIssueBodyLen]
			}
			a := s.d.Jev.Ask(cctx, "readiness", "score", readinessQ, body, nil, readinessLevels)
			if a.Status != "ok" {
				ch <- res{k: k}
				return
			}
			sc := int(a.Score+0.5) + 1
			if sc < 1 {
				sc = 1
			}
			if sc > 5 {
				sc = 5
			}
			ch <- res{k, sc, true}
		}(k)
	}
	scores := map[string]int{}
	got := 0
	timer := time.NewTimer(readinessWait)
	defer timer.Stop()
collect:
	for got < len(scored) {
		select {
		case r := <-ch:
			got++
			if r.ok {
				scores[r.k] = r.score
			} else {
				unavailable[r.k] = true
			}
		case <-timer.C:
			break collect
		}
	}
	for _, k := range scored {
		if _, ok := scores[k]; !ok {
			unavailable[k] = true
		}
	}
	var lines []string
	for _, k := range refined {
		if sc, ok := scores[k]; ok && sc <= readinessLow {
			lines = append(lines, fmt.Sprintf("%s: may be underspecified (jev %d/5)", k, sc))
		}
	}
	if len(unavailable) > 0 {
		var u []string
		for k := range unavailable {
			u = append(u, k)
		}
		sort.Strings(u)
		lines = append(lines, "Readiness unavailable for "+strings.Join(u, ", "))
	}
	return scores, lines
}

// Preview builds the plan of a resolved epic or pick. It changes nothing.
func (s *Service) Preview(ctx context.Context, r Resolved, st store.Settings) PlanView {
	p := MakePlan(r.Children)
	var repos []string
	seen := map[string]bool{}
	for _, c := range r.Children {
		if !seen[c.Repo] {
			seen[c.Repo] = true
			repos = append(repos, c.Repo)
		}
	}
	sort.Strings(repos)
	where := "the pick"
	if r.Epic != nil {
		where = "the epic"
	}
	var okeys []string
	for k := range r.Outside {
		okeys = append(okeys, k)
	}
	sort.Strings(okeys)
	for _, k := range okeys {
		p.Warnings = append(p.Warnings, fmt.Sprintf("%s: blocked by open %s outside %s", k, strings.Join(r.Outside[k], ", "), where))
	}
	for _, k := range r.Closed {
		p.Warnings = append(p.Warnings, k+": closed, left out")
	}
	for _, repo := range repos {
		if s.d.Grind == nil || st.Grind == "off" {
			continue
		}
		g := s.d.Grind(repo)
		if g.Skip != "" || g.Path == "" {
			why := g.Skip
			if why == "" {
				why = NoReviewer
			}
			p.Warnings = append(p.Warnings, repo+": "+why)
		}
	}
	p.Warnings = append(p.Warnings, s.MissingBase(ctx, repos, store.Str(st.BaseBranch))...)
	var scores map[string]int
	if r.Bodies != nil {
		sc, lines := s.readiness(ctx, r.Children, r.Bodies)
		scores = sc
		p.Warnings = append(p.Warnings, lines...)
	}
	v := PlanView{Epic: r.Epic, Title: r.Title, Settings: st, Waves: p.Waves, Warnings: p.Warnings, Lanes: []PlanLane{}}
	if r.Epic == nil {
		v.Issues = r.Issues
	}
	for _, c := range r.Children {
		k := store.Key(c.Repo, c.N)
		pl := PlanLane{Key: k, Title: c.Title, Refined: c.Refined, Deps: c.Deps}
		if sc, ok := scores[k]; ok {
			pl.Readiness = &sc
		}
		v.Lanes = append(v.Lanes, pl)
	}
	return v
}
