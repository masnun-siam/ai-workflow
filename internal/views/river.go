package views

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Stage ids in pipeline order.
var stageOrder = []struct{ id, name, skills string }{
	{"prd", "PRD", "create-prd · map-prds"},
	{"tasks", "Tasks", "create-tasks"},
	{"refine", "Refine", "refine-issues · reproduce-bug"},
	{"implement", "Implement", "implement-issue · coordinator"},
	{"review", "Review", "pr-review · peer · grind"},
	{"release", "Release", "release-pr · pr-grind"},
	{"notify", "Notify", "release-note"},
}

// Ask is the question a card carries; the UI answers through POST /api/sessions/{id}/answer.
type Ask struct {
	SessionID string          `json:"session_id"`
	Round     *sessions.Round `json:"round"`
}

// Card is one River card (API §4).
type Card struct {
	ID       string         `json:"id"`
	Stage    string         `json:"stage"`
	Title    string         `json:"title"`
	Meta     string         `json:"meta"`
	Tag      string         `json:"tag"`
	Tone     string         `json:"tone"`
	Need     bool           `json:"need"`
	NeedKind *string        `json:"need_kind"`
	Live     bool           `json:"live"`
	Skill    string         `json:"skill"`
	Repo     string         `json:"repo"`
	Log      []string       `json:"log"`
	Ask      *Ask           `json:"ask"`
	Note     *string        `json:"note"`
	Links    inbox.Links    `json:"links"`
	Actions  []inbox.Action `json:"actions"`

	anchors []string
}

// StageView is one River column.
type StageView struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Skills string `json:"skills"`
	Hot    bool   `json:"hot"`
	Cards  []Card `json:"cards"`
}

// River is GET /api/river.
type River struct {
	Product   string      `json:"product"`
	Stale     []string    `json:"stale"`
	FetchedAt *string     `json:"fetched_at"`
	Stages    []StageView `json:"stages"`
}

// Product finds a registered product by its docs repo slug (case-insensitive).
func (s *Service) Product(slug string) (products.Product, bool) {
	if s.d.Products == nil {
		return products.Product{}, false
	}
	ps := s.d.Products.Products()
	if slug == "" {
		if len(ps) == 0 {
			return products.Product{}, false
		}
		return ps[0], true
	}
	for _, p := range ps {
		if strings.EqualFold(p.DocsRepo, slug) {
			return p, true
		}
	}
	return products.Product{}, false
}

type rv struct {
	s        *Service
	ctx      context.Context
	p        products.Product
	repos    []string
	set      map[string]bool
	snaps    map[string]poller.Snapshot
	items    map[string][]inbox.Item // anchor -> non-wait items
	byAnchor map[string]*Card
	cards    []*Card
	grinds   map[string]inbox.GrindStatus
	relPR    map[string]bool // lower(repo)#pr of a release in flight
}

func lower(s string) string { return strings.ToLower(s) }

func hasLabel(labels []string, l string) bool {
	for _, x := range labels {
		if strings.EqualFold(x, l) {
			return true
		}
	}
	return false
}

func (r *rv) add(c *Card, anchors ...string) *Card {
	if c.Log == nil {
		c.Log = []string{}
	}
	if c.Actions == nil {
		c.Actions = []inbox.Action{}
	}
	c.anchors = append(c.anchors, anchors...)
	r.cards = append(r.cards, c)
	for _, a := range anchors {
		if _, dup := r.byAnchor[a]; !dup {
			r.byAnchor[a] = c
		}
	}
	return c
}

func start(key, label, toast, step, repo string, extra map[string]any) inbox.Action {
	body := map[string]any{"step": step, "repo": repo}
	for k, v := range extra {
		body[k] = v
	}
	return inbox.Start(key, label, toast, body)
}

func issueAnchor(repo string, n int) string { return fmt.Sprintf("issue:%s#%d", lower(repo), n) }
func prAnchor(repo string, n int) string    { return fmt.Sprintf("pr:%s#%d", lower(repo), n) }

// River builds the pipeline for a product. It marks the product's repos viewed.
func (s *Service) River(ctx context.Context, product string) River {
	p, ok := s.Product(product)
	out := River{Product: product, Stale: []string{}}
	if ok {
		out.Product = p.DocsRepo
	}
	r := &rv{s: s, ctx: ctx, p: p, set: map[string]bool{}, snaps: map[string]poller.Snapshot{}, items: map[string][]inbox.Item{},
		byAnchor: map[string]*Card{}, grinds: map[string]inbox.GrindStatus{}, relPR: map[string]bool{}}
	if ok {
		r.repos = inbox.ProductRepos(p)
	}
	for _, repo := range r.repos {
		r.set[lower(repo)] = true
		if s.d.Snapshots != nil {
			s.d.Snapshots.MarkViewed(repo)
			r.snaps[lower(repo)] = s.d.Snapshots.Snapshot(repo)
		}
	}
	var oldest *time.Time
	if s.d.Snapshots != nil {
		for _, repo := range r.repos {
			sn := r.snaps[lower(repo)]
			if !sn.Fresh() {
				out.Stale = append(out.Stale, repo)
			}
			if sn.FetchedAt != nil && (oldest == nil || sn.FetchedAt.Before(*oldest)) {
				t := *sn.FetchedAt
				oldest = &t
			}
		}
	}
	sort.Strings(out.Stale)
	if oldest != nil {
		t := oldest.UTC().Format(time.RFC3339)
		out.FetchedAt = &t
	}
	if s.d.Grinds != nil {
		for _, g := range s.d.Grinds.Index() {
			r.grinds[fmt.Sprintf("%s#%d", lower(g.Repo), g.PR)] = g
		}
	}
	if s.d.Inbox != nil && ok {
		for _, it := range s.d.Inbox.Build(ctx, p.DocsRepo, "").Items {
			if it.Group == inbox.GWait {
				continue
			}
			for _, a := range it.Anchors {
				r.items[a] = append(r.items[a], it)
			}
		}
	}

	if ok {
		r.releases()
		r.prds()
		r.issues()
		r.coordinators()
		r.attachSessions()
	}
	r.finish()

	byStage := map[string][]Card{}
	for _, c := range r.cards {
		byStage[c.Stage] = append(byStage[c.Stage], *c)
	}
	for _, st := range stageOrder {
		cards := byStage[st.id]
		if cards == nil {
			cards = []Card{}
		}
		hot := false
		for _, c := range cards {
			hot = hot || c.Need
		}
		out.Stages = append(out.Stages, StageView{ID: st.id, Name: st.name, Skills: st.skills, Hot: hot, Cards: cards})
	}
	return out
}

// ---- PRDs and epics ----

// PRDs lists a product's PRDs with each PRD's epic filled in (an open issue labelled epic and the
// PRD's prd-<slug> label, in any repo of the product).
func (s *Service) PRDs(product string) ([]products.PRD, error) {
	if s.d.Products == nil {
		return nil, nil
	}
	prds, err := s.d.Products.PRDs(product)
	if err != nil {
		return nil, err
	}
	p, ok := s.Product(product)
	if !ok || s.d.Snapshots == nil {
		return prds, nil
	}
	epics := map[string]string{}
	for _, repo := range inbox.ProductRepos(p) {
		for _, is := range s.d.Snapshots.Snapshot(repo).Data.Issues {
			if !hasLabel(is.Labels, "epic") {
				continue
			}
			for _, l := range is.Labels {
				if strings.HasPrefix(lower(l), "prd-") {
					if _, dup := epics[lower(l)]; !dup {
						epics[lower(l)] = fmt.Sprintf("%s#%d", repo, is.N)
					}
				}
			}
		}
	}
	for i := range prds {
		if k, ok := epics[lower(prds[i].Label)]; ok {
			prds[i].Epic = &k
		}
	}
	return prds, nil
}

func (r *rv) prds() {
	if r.s.d.Products == nil {
		return
	}
	prds, err := r.s.PRDs(r.p.DocsRepo)
	if err != nil {
		return
	}
	docs := r.p.DocsRepo
	for _, d := range prds {
		mod := repoName(docs)
		if d.Module != nil {
			mod = *d.Module
		}
		c := &Card{ID: "prd:" + d.Slug, Stage: "prd", Title: d.Title, Repo: repoName(docs), Skill: "blubird:create-prd", Tone: "c-w"}
		c.Links.PRD = inbox.PRDRoute(docs, d.Path)
		read := inbox.Open("r", "Read PRD", c.Links.PRD)
		switch d.Status {
		case "Draft":
			c.Tag, c.Meta = "draft", "draft · "+mod
			c.Actions = []inbox.Action{start("o", "Continue", "Resumed create-prd", "create-prd", docs, map[string]any{"product": docs, "args": d.Path}), read}
		case "In review":
			c.Tag, c.Meta = "review", "in review · "+mod
			c.Actions = []inbox.Action{
				inbox.Start("e", "Approve + create epic", "Approved; creating the epic", map[string]any{
					"step": "create-prd", "repo": docs, "product": docs, "args": inbox.ApproveArgs(d.Path)}).WithPrimary().WithClears().WithConfirm("Approve this PRD and create its epic?"),
				read}
		case "Approved":
			if d.Epic != nil {
				continue // the epic card carries it
			}
			c.Tag, c.Tone, c.Meta = "approved", "c-q", "approved · "+mod
			c.Skill = "blubird:create-tasks"
			c.Actions = []inbox.Action{start("t", "Create tasks", "Started create-tasks", "create-tasks", docs, map[string]any{"product": docs, "args": d.Path}).WithPrimary(), read}
		default:
			continue
		}
		r.add(c, "prd:"+lower(docs)+":"+d.Path)
	}
}

type found struct {
	repo  string
	issue poller.Issue
}

func (r *rv) allIssues() []found {
	var out []found
	for _, repo := range r.repos {
		for _, is := range r.snaps[lower(repo)].Data.Issues {
			out = append(out, found{repo, is})
		}
	}
	return out
}

func (r *rv) issues() {
	all := r.allIssues()
	index := map[string]found{}
	for _, f := range all {
		index[fmt.Sprintf("%s#%d", lower(f.repo), f.issue.N)] = f
	}
	refined := func(f found) bool { return hasLabel(f.issue.Labels, "refined") }

	// epics
	for _, f := range all {
		is := f.issue
		if !hasLabel(is.Labels, "epic") {
			continue
		}
		var kids []found
		seen := map[string]bool{}
		consider := func(k found) {
			key := fmt.Sprintf("%s#%d", lower(k.repo), k.issue.N)
			if !seen[key] && !hasLabel(k.issue.Labels, "epic") {
				seen[key] = true
				kids = append(kids, k)
			}
		}
		for _, ref := range is.SubIssues {
			if k, ok := index[lower(ref.Repo)+"#"+strconv.Itoa(ref.N)]; ok {
				consider(k)
			}
		}
		for _, k := range all {
			if k.issue.Parent != nil && strings.EqualFold(k.issue.Parent.Repo, f.repo) && k.issue.Parent.N == is.N {
				consider(k)
			}
		}
		unrefined := 0
		for _, k := range kids {
			if !refined(k) {
				unrefined++
			}
		}
		done := len(is.ClosedSubs)
		if unrefined == 0 && (len(kids) > 0 || done > 0) {
			continue
		}
		key := fmt.Sprintf("%s#%d", f.repo, is.N)
		meta := fmt.Sprintf("epic #%d · %d issues", is.N, len(kids))
		if done > 0 {
			meta += fmt.Sprintf(", %d done", done)
		}
		c := &Card{ID: "epic:" + key, Stage: "tasks", Title: strings.TrimSpace(strings.TrimPrefix(is.Title, "Epic:")), Meta: meta,
			Tag: "epic", Tone: "c-q", Skill: "blubird:create-tasks", Repo: repoName(f.repo)}
		c.Links.Issue = inbox.IssueURL(f.repo, is.N)
		if unrefined > 0 {
			c.Actions = append(c.Actions, start("f", fmt.Sprintf("Refine all %d", unrefined), "Started refine-issues "+strconv.Itoa(is.N),
				"refine-issues", f.repo, map[string]any{"issue": is.N, "args": strconv.Itoa(is.N)}).WithPrimary())
		}
		c.Actions = append(c.Actions, inbox.Open("o", "Open epic", c.Links.Issue))
		r.add(c, issueAnchor(f.repo, is.N))
	}

	// PRs first: an issue with a non-draft open PR lives in review
	prOf := map[string]poller.OpenPR{} // issue key -> its first open PR
	for _, repo := range r.repos {
		d := r.snaps[lower(repo)].Data
		for _, p := range d.OpenPRs {
			n := inbox.IssueOfPR(d, p)
			if n > 0 {
				if _, ok := prOf[fmt.Sprintf("%s#%d", lower(repo), n)]; !ok {
					prOf[fmt.Sprintf("%s#%d", lower(repo), n)] = p
				}
			}
			if p.Draft {
				continue
			}
			if r.relPR[fmt.Sprintf("%s#%d", lower(repo), p.N)] {
				continue
			}
			r.prCard(repo, d, p, n)
		}
	}

	// issues
	for _, f := range all {
		is := f.issue
		if hasLabel(is.Labels, "epic") || is.Status == poller.StatusDone {
			continue
		}
		key := fmt.Sprintf("%s#%d", lower(f.repo), is.N)
		pr, hasPR := prOf[key]
		if hasPR && !pr.Draft {
			continue
		}
		var blockers []string
		for _, b := range is.BlockedBy {
			if b.State == "OPEN" {
				blockers = append(blockers, "#"+strconv.Itoa(b.N))
			}
		}
		isRefined := refined(f)
		stage := "implement"
		if !isRefined && is.Status == poller.StatusBacklog && !hasPR {
			stage = "refine"
		}
		c := &Card{ID: "issue:" + fmt.Sprintf("%s#%d", f.repo, is.N), Stage: stage, Title: fmt.Sprintf("#%d %s", is.N, is.Title), Repo: repoName(f.repo), Skill: "—"}
		c.Links.Issue = inbox.IssueURL(f.repo, is.N)
		open := inbox.Open("o", "Open issue", c.Links.Issue)
		anchors := []string{issueAnchor(f.repo, is.N)}
		isBug := hasLabel(is.Labels, "bug")
		owned := r.s.d.Dispatch != nil && r.s.d.Dispatch.Owned(f.repo, is.N, 0)
		switch {
		case stage == "refine":
			c.Tag, c.Meta = "backlog", "Backlog"
			if isBug {
				c.Tag, c.Tone = "bug", "c-b"
			}
			c.Actions = []inbox.Action{start("f", "Refine", "Started refine-issues "+strconv.Itoa(is.N), "refine-issues", f.repo,
				map[string]any{"issue": is.N, "args": strconv.Itoa(is.N)}).WithPrimary()}
			if isBug {
				c.Actions = append(c.Actions, start("b", "Reproduce", "Started reproduce-bug "+strconv.Itoa(is.N), "reproduce-bug", f.repo,
					map[string]any{"issue": is.N, "args": "#" + strconv.Itoa(is.N)}))
			}
		case hasPR:
			anchors = append(anchors, prAnchor(f.repo, pr.N))
			c.Links.PR = pr.URL
			c.Tag, c.Tone = "draft PR", "c-q"
			c.Meta = fmt.Sprintf("draft PR #%d · CI %s", pr.N, ciWord(pr.CI))
			c.Skill = "blubird:implement-issue"
			if pr.CI == "failure" {
				c.Tag, c.Tone = "ci failed", "c-b"
			} else if pr.CI == "pending" {
				c.Tag = "ci"
			}
			c.Actions = []inbox.Action{inbox.Open("p", "Open PR", pr.URL).WithPrimary()}
		case len(blockers) > 0:
			c.Tag, c.Meta = "blocked", "waiting on "+strings.Join(blockers, ", ")
			c.Actions = []inbox.Action{start("i", "Implement", "Started implement-issue "+strconv.Itoa(is.N), "implement-issue", f.repo,
				map[string]any{"issue": is.N, "args": strconv.Itoa(is.N), "guard": true})}
		default:
			c.Tag, c.Tone, c.Meta = "ready", "c-o", "Ready"
			if is.Status == poller.StatusInProgress {
				c.Tag, c.Tone, c.Meta = "in progress", "c-q", "In progress"
			}
			c.Actions = []inbox.Action{start("i", "Implement", "Started implement-issue "+strconv.Itoa(is.N), "implement-issue", f.repo,
				map[string]any{"issue": is.N, "args": strconv.Itoa(is.N), "guard": true}).WithPrimary()}
			c.Actions = append(c.Actions, r.dispatchAction(f.repo, is.N))
		}
		if owned {
			c.Tag, c.Tone, c.Live = "dispatch", "c-q", true
			c.Meta = "owned by a dispatch lane"
			c.Actions = []inbox.Action{open}
		} else {
			c.Actions = append(c.Actions, open)
		}
		if is.Priority != nil && *is.Priority != "" {
			c.Meta += " · " + *is.Priority
		}
		r.add(c, anchors...)
	}
}

// dispatchAction adds the issue to a running dispatch, or starts one.
func (r *rv) dispatchAction(repo string, n int) inbox.Action {
	key := fmt.Sprintf("%s#%d", repo, n)
	if r.s.d.Dispatch != nil {
		for _, d := range r.s.d.Dispatch.List() {
			if d.State == "running" || d.State == "paused" {
				return inbox.Post("d", "Add to dispatch", "/api/dispatches/"+d.ID+"/lanes", "Added to dispatch",
					map[string]any{"issues": []string{key}})
			}
		}
	}
	return inbox.Post("d", "Dispatch", "/api/dispatches", "Dispatch started", map[string]any{"issues": []string{key}})
}

func ciWord(ci string) string {
	switch ci {
	case "success":
		return "green"
	case "failure":
		return "red"
	case "pending":
		return "running"
	}
	return "none"
}

func (r *rv) prCard(repo string, d poller.Data, p poller.OpenPR, issue int) {
	title := p.Title
	if issue > 0 {
		for _, is := range d.Issues {
			if is.N == issue {
				title = fmt.Sprintf("#%d %s", issue, is.Title)
			}
		}
	}
	c := &Card{ID: "pr:" + fmt.Sprintf("%s#%d", repo, p.N), Stage: "review", Title: title, Repo: repoName(repo), Skill: "blubird:pr-review", Tag: "review", Tone: "c-w"}
	c.Links.PR = p.URL
	anchors := []string{prAnchor(repo, p.N)}
	if issue > 0 {
		c.Links.Issue = inbox.IssueURL(repo, issue)
		anchors = append(anchors, issueAnchor(repo, issue))
	}
	meta := fmt.Sprintf("PR #%d · CI %s", p.N, ciWord(p.CI))
	if p.ThreadsOpen > 0 {
		meta += fmt.Sprintf(" · %d open threads", p.ThreadsOpen)
	}
	if p.ChangesRequested {
		meta += " · changes requested"
	}
	c.Meta = meta
	g, hasGrind := r.grinds[fmt.Sprintf("%s#%d", lower(repo), p.N)]
	c.Actions = []inbox.Action{inbox.Open("o", "Open PR", p.URL)}
	switch {
	case p.Conflict:
		c.Tag, c.Tone = "conflict", "c-b"
	case hasGrind && g.State == "paused":
		c.Tag, c.Tone, c.Skill = "grind paused", "c-w", "pr-grind"
	case hasGrind && (g.State == "running" || g.State == "idle"):
		c.Tag, c.Tone, c.Live, c.Skill = fmt.Sprintf("grind r%d", g.Rounds), "c-o", true, "pr-grind"
		c.Meta += fmt.Sprintf(" · grind round %d", g.Rounds)
	case p.CI == "failure":
		c.Tag, c.Tone = "ci failed", "c-b"
	case p.CI == "pending":
		c.Tag, c.Tone = "ci", "c-q"
	}
	if p.ThreadsOpen > 0 || p.ChangesRequested {
		c.Actions = append(c.Actions, start("x", "Fix comments", "Started pr-review --fix", "pr-review", repo,
			map[string]any{"issue": issue, "args": p.URL + " --fix", "guard": true}))
	} else if !c.Live {
		c.Actions = append(c.Actions, start("v", "Review", "Started pr-review", "pr-review", repo,
			map[string]any{"issue": issue, "args": p.URL, "guard": true}))
	}
	if !hasGrind || g.State == "done" || g.State == "approved" || g.State == "none" {
		c.Actions = append(c.Actions, inbox.Post("g", "Grind", "/api/grinds", "Started pr-grind on #"+strconv.Itoa(p.N), map[string]any{"repo": repo, "pr": p.N}))
	}
	r.add(c, anchors...)
}

// ---- releases ----

func (r *rv) releases() {
	if r.s.d.Releases == nil {
		return
	}
	d := r.s.d
	channel := "Slack"
	if d.NoteChannel != nil {
		if c := d.NoteChannel(); c != "" {
			channel = "#" + strings.TrimPrefix(c, "#")
		}
	}
	open := map[string]bool{}
	for _, rl := range d.Releases.List(r.p.DocsRepo) {
		repo := rl.Repo
		if rl.PR != nil && rl.Stage != "done" && rl.Stage != "skipped" {
			r.relPR[fmt.Sprintf("%s#%d", lower(repo), *rl.PR)] = true
		}
		switch rl.Stage {
		case "cut", "grind", "merge":
			open[lower(repo)] = true
			c := &Card{ID: "release:" + rl.ID, Stage: "release", Title: repoName(repo) + " release", Repo: repoName(repo),
				Skill: "release-pr", Tag: rl.Stage, Tone: "c-q", Live: rl.Stage != "merge"}
			title := fmt.Sprintf("%s → %s", rl.Head, rl.Base)
			c.Meta = title
			if rl.PR != nil {
				c.Title = fmt.Sprintf("Release PR #%d", *rl.PR)
				c.Meta = fmt.Sprintf("%s · %s", title, rl.Stage)
			}
			if rl.PRURL != nil {
				c.Links.PR = *rl.PRURL
				c.Actions = append(c.Actions, inbox.Open("o", "Open PR", *rl.PRURL))
			}
			if rl.Stage == "grind" || (rl.Stage == "cut" && rl.PR != nil) {
				c.Skill = "pr-grind"
				c.Actions = append(c.Actions, inbox.Post("g", "Grind", "/api/releases/"+rl.ID+"/grind", "Started pr-grind", nil))
			}
			if rl.Error != nil && *rl.Error != "" {
				c.Tone = "c-b"
				c.Log = append(c.Log, *rl.Error)
			}
			anchors := []string{"release:" + rl.ID}
			for _, sid := range []*string{rl.CutSession} {
				if sid != nil {
					anchors = append(anchors, "session:"+*sid)
					c.Links.Session = inbox.SessionRoute(*sid)
				}
			}
			c.Actions = append(c.Actions, inbox.Post("x", "Skip", "/api/releases/"+rl.ID+"/skip", "Skipped", nil).WithClears())
			r.add(c, anchors...)
		case "notify":
			if rl.DryRun || rl.NotePosted != nil {
				continue
			}
			c := &Card{ID: "release:" + rl.ID, Stage: "notify", Title: repoName(repo) + " release note", Repo: repoName(repo), Skill: "release-note",
				Tag: "notify", Tone: "c-w", Meta: "merged · note for " + channel}
			if rl.PR != nil {
				c.Title = fmt.Sprintf("Release #%d", *rl.PR)
			}
			if rl.PRURL != nil {
				c.Links.PR = *rl.PRURL
			}
			anchors := []string{"release:" + rl.ID}
			if rl.NoteSession != nil {
				anchors = append(anchors, "session:"+*rl.NoteSession)
				c.Links.Session = inbox.SessionRoute(*rl.NoteSession)
			}
			if rl.Note != nil && strings.TrimSpace(*rl.Note) != "" {
				c.Actions = []inbox.Action{
					inbox.Post("p", "Post to "+channel, "/api/releases/"+rl.ID+"/post", "Posted once to "+channel, nil).WithPrimary().WithClears().WithConfirm("Post this release note? It is sent once."),
					inbox.Open("e", "Edit note", "#/releases/"+rl.ID),
					inbox.Post("x", "Skip", "/api/releases/"+rl.ID+"/skip", "Skipped", nil).WithClears(),
				}
			} else {
				c.Tag, c.Meta, c.Live = "drafting", "drafting the note", rl.NoteSession != nil
				c.Actions = []inbox.Action{
					inbox.Post("n", "Draft note", "/api/releases/"+rl.ID+"/note", "Drafting the release note", nil).WithPrimary(),
					inbox.Post("x", "Skip", "/api/releases/"+rl.ID+"/skip", "Skipped", nil).WithClears(),
				}
			}
			if rl.Error != nil && *rl.Error != "" {
				c.Tone = "c-b"
				c.Log = append(c.Log, *rl.Error)
			}
			r.add(c, anchors...)
		}
	}
	for _, rr := range d.Releases.Repos(r.p.DocsRepo) {
		if rr.Open != nil || open[lower(rr.Repo)] || rr.Ahead == nil || *rr.Ahead <= 0 {
			continue
		}
		c := &Card{ID: "repo:" + rr.Repo, Stage: "release", Title: repoName(rr.Repo), Repo: repoName(rr.Repo), Skill: "release-pr", Tag: "release",
			Meta: fmt.Sprintf("%d commits ahead on %s", *rr.Ahead, rr.Head)}
		if rr.PRsWaiting != nil {
			c.Meta = fmt.Sprintf("%d PRs on %s", *rr.PRsWaiting, rr.Head)
		}
		c.Actions = []inbox.Action{
			inbox.Post("r", "Cut release", "/api/releases", "Started release-pr in "+repoName(rr.Repo), map[string]any{"repo": rr.Repo}).WithPrimary(),
			inbox.Post("y", "Dry run", "/api/releases", "release-pr --dry-run", map[string]any{"repo": rr.Repo, "dry_run": true}),
		}
		r.add(c, "repo:"+lower(rr.Repo))
	}
}

// ---- coordinators ----

func (r *rv) coordinators() {
	if r.s.d.Dispatch == nil {
		return
	}
	for _, co := range r.s.d.Dispatch.Coordinators() {
		if !co.Live || !r.set[lower(co.Repo)] {
			continue
		}
		c := &Card{ID: "coord:" + co.Run, Stage: "implement", Title: "Coordinator · " + co.Source, Repo: repoName(co.Repo), Skill: "blubird:project-coordinator",
			Tag: "running", Tone: "c-q", Live: true, Meta: co.Repo}
		if co.Destination != "" {
			c.Meta += " → " + co.Destination
		}
		for _, q := range co.Queue {
			c.Log = append(c.Log, fmt.Sprintf("#%d %s", q.Issue, q.State))
		}
		if len(c.Log) == 0 {
			c.Log = lastN(co.Events, 8)
		}
		c.Log = lastN(c.Log, 8)
		anchors := []string{"coord:" + co.Run}
		if co.Session != nil {
			anchors = append(anchors, "session:"+*co.Session)
			c.Links.Session = inbox.SessionRoute(*co.Session)
			c.Actions = append(c.Actions, inbox.Open("o", "Open session", c.Links.Session))
		}
		c.Actions = append(c.Actions, inbox.Post("x", "Stop refilling", "/api/coordinators/"+co.Run+"/stop", "Coordinator will not refill", nil).WithConfirm("Stop this coordinator?"))
		r.add(c, anchors...)
	}
}

func lastN(s []string, n int) []string {
	if len(s) > n {
		s = s[len(s)-n:]
	}
	return append([]string(nil), s...)
}

// ---- sessions ----

var riverStages = map[string]bool{"prd": true, "tasks": true, "refine": true, "implement": true, "review": true, "release": true, "notify": true}

func stageOf(st prompts.Step) (string, bool) {
	for _, g := range strings.Split(st.Stage, ",") {
		if riverStages[strings.TrimSpace(g)] {
			return strings.TrimSpace(g), true
		}
	}
	return "", false
}

func skillName(s sessions.Session) string {
	if s.Skill != nil {
		return *s.Skill
	}
	return "—"
}

func (r *rv) attachSessions() {
	d := r.s.d
	if d.Sessions == nil {
		return
	}
	wanted := map[string]bool{} // sessions with an inbox item
	for _, its := range r.items {
		for _, it := range its {
			if it.SessionID != "" {
				wanted[it.SessionID] = true
			}
		}
	}
	for _, rec := range d.Sessions.List(sessions.Filter{}) {
		if rec.PanelRole == "lens" || (!rec.Status.Live() && !wanted[rec.ID]) {
			continue
		}
		s := d.Sessions.Public(rec)
		if s.Repo != nil && !r.set[lower(*s.Repo)] {
			continue
		}
		if s.Repo == nil && (rec.Link == nil || !r.set[lower(rec.Link.Owner+"/"+rec.Link.Repo)]) {
			continue
		}
		var stage string
		if s.Step != nil && d.Prompts != nil {
			if st, ok := d.Prompts.Step(*s.Step); ok {
				stage, _ = stageOf(st)
			}
		}
		if stage == "" {
			continue
		}
		var target *Card
		if rec.Link != nil {
			target = r.byAnchor[issueAnchor(rec.Link.Owner+"/"+rec.Link.Repo, rec.Link.Issue)]
		}
		if target == nil && rec.Args != "" {
			for _, c := range r.cards {
				for _, a := range c.anchors {
					if strings.HasPrefix(a, "prd:") {
						if i := strings.LastIndexByte(a, ':'); i > 0 && strings.Contains(rec.Args, a[i+1:]) {
							target = c
						}
					}
				}
			}
		}
		if target == nil {
			target = r.byAnchor["session:"+s.ID]
		}
		if target != nil {
			target.anchors = append(target.anchors, "session:"+s.ID)
			r.byAnchor["session:"+s.ID] = target
			if rec.Status.Live() {
				target.Live = true
				if target.Skill == "—" || target.Skill == "" {
					target.Skill = skillName(s)
				}
				target.Log = append(target.Log, r.sessionLog(rec, s)...)
			}
			if target.Links.Session == "" {
				target.Links.Session = inbox.SessionRoute(s.ID)
				target.Actions = append(target.Actions, inbox.Open("s", "Open session", target.Links.Session))
			}
			continue
		}
		c := &Card{ID: "session:" + s.ID, Stage: stage, Title: s.Title, Repo: "", Skill: skillName(s), Live: rec.Status.Live(), Tag: string(rec.Status),
			Meta: r.sessionMeta(rec, s), Log: r.sessionLog(rec, s)}
		if s.Repo != nil {
			c.Repo = repoName(*s.Repo)
		}
		c.Links.Session = inbox.SessionRoute(s.ID)
		switch rec.Status {
		case sessions.StFailed:
			c.Tone = "c-b"
		case sessions.StRunning, sessions.StStarting, sessions.StWaiting:
			c.Tone = "c-q"
		default:
			c.Tone = "c-w"
		}
		c.Actions = []inbox.Action{inbox.Open("o", "Open session", c.Links.Session)}
		if rec.Status.Live() {
			c.Actions = append(c.Actions, inbox.Post("x", "Stop", "/api/sessions/"+s.ID+"/stop", "Stopped", nil).WithConfirm("Stop this session?"))
		}
		r.add(c, "session:"+s.ID)
	}
}

func (r *rv) sessionMeta(rec sessions.Record, s sessions.Session) string {
	parts := []string{string(rec.Status)}
	if s.DurationS != nil {
		parts = append(parts, fmtDur(*s.DurationS))
	}
	if s.Cost != nil {
		parts = append(parts, fmt.Sprintf("$%.2f", *s.Cost))
	}
	return strings.Join(parts, " · ")
}

func fmtDur(sec int64) string {
	switch {
	case sec < 90:
		return fmt.Sprintf("%ds", sec)
	case sec < 5400:
		return fmt.Sprintf("%dm", sec/60)
	}
	return fmt.Sprintf("%dh%02d", sec/3600, sec%3600/60)
}

func (r *rv) sessionLog(rec sessions.Record, s sessions.Session) []string {
	var out []string
	if r.s.d.Log != nil {
		for _, l := range r.s.d.Log(rec.ID) {
			if strings.TrimSpace(l) != "" {
				out = append(out, l)
			}
		}
	}
	if len(out) == 0 {
		out = append(out, r.sessionMeta(rec, s))
	}
	if rec.Note != "" {
		out = append(out, rec.Note)
	}
	if rec.Error != "" {
		out = append(out, firstLine(rec.Error))
	}
	if rec.PendingQuestion != nil {
		out = append(out, "Waiting for your answer")
	}
	return lastN(out, 8)
}

func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[:i]
	}
	if len(s) > 200 {
		s = s[:200]
	}
	return s
}

// ---- need, ask, ordering ----

func needKind(t string) string {
	switch t {
	case inbox.TQuestion:
		return "Question"
	case inbox.TPRDApproval, inbox.TReviewApproved:
		return "Approval"
	case inbox.TSessionFailed:
		return "Failed"
	case inbox.TReleaseNote:
		return "Release"
	}
	return "Decide"
}

var needRank = map[string]int{inbox.TQuestion: 0, inbox.TSessionFailed: 1, inbox.TReleaseNote: 2, inbox.TPRDApproval: 3}

// mergeActions puts the item's actions first, then the card's own whose key is free.
func mergeActions(item, own []inbox.Action) []inbox.Action {
	out := append([]inbox.Action(nil), item...)
	used := map[string]bool{}
	same := map[string]bool{}
	for i, a := range out {
		used[a.Key] = true
		for _, o := range own {
			if a.Path != "" && o.Method == a.Method && o.Path == a.Path && fmt.Sprint(o.Body) == fmt.Sprint(a.Body) {
				// the card's wording is richer (it knows the channel): keep the item's key
				k := a.Key
				out[i] = o
				out[i].Key = k
				same[o.Key+o.Path] = true
			}
		}
	}
	for _, a := range own {
		if used[a.Key] || same[a.Key+a.Path] {
			continue
		}
		used[a.Key] = true
		out = append(out, a)
	}
	return out
}

func (r *rv) finish() {
	for i, c := range r.cards {
		var hits []inbox.Item
		seen := map[string]bool{}
		for _, a := range c.anchors {
			for _, it := range r.items[a] {
				if !seen[it.Key] {
					seen[it.Key] = true
					hits = append(hits, it)
				}
			}
		}
		if len(hits) > 0 {
			sort.SliceStable(hits, func(a, b int) bool {
				ra, oka := needRank[hits[a].Type]
				rb, okb := needRank[hits[b].Type]
				if !oka {
					ra = 9
				}
				if !okb {
					rb = 9
				}
				return ra < rb
			})
			top := hits[0]
			c.Need = true
			k := needKind(top.Type)
			c.NeedKind = &k
			var itemActs []inbox.Action
			for _, h := range hits {
				if h.Type == inbox.TQuestion && h.Round != nil && c.Ask == nil {
					c.Ask = &Ask{SessionID: h.SessionID, Round: h.Round}
				}
				if h.Type == inbox.TReleaseNote && c.Note == nil {
					n := h.Note
					c.Note = &n
				}
				if h.Type == inbox.TSessionFailed && h.SessionID != "" && c.Links.Session == "" {
					c.Links.Session = inbox.SessionRoute(h.SessionID)
				}
				if h.Key == top.Key {
					itemActs = append(itemActs, h.Actions...)
				}
			}
			c.Actions = mergeActions(itemActs, c.Actions)
		}
		_ = i
	}
	// order: need, then live, then discovery order
	idx := map[*Card]int{}
	for i, c := range r.cards {
		idx[c] = i
	}
	sort.SliceStable(r.cards, func(a, b int) bool {
		x, y := r.cards[a], r.cards[b]
		if x.Need != y.Need {
			return x.Need
		}
		if x.Live != y.Live {
			return x.Live
		}
		return idx[x] < idx[y]
	})
	for _, c := range r.cards {
		c.Log = lastN(c.Log, 8)
	}
}
