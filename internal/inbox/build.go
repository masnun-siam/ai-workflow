package inbox

import (
	"context"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Builder derives the inbox. Build is pure over its inputs (plus the urgency cache of jev).
type Builder struct {
	d   Deps
	urg *scorer
}

// New returns a Builder.
func New(d Deps) *Builder {
	b := &Builder{d: d}
	b.urg = newScorer(b)
	return b
}

func (b *Builder) now() time.Time {
	if b.d.Now != nil {
		return b.d.Now()
	}
	return time.Now()
}

// view is the state one Build works from.
type view struct {
	ctx      context.Context
	reg      map[string]string // lower-case slug -> registered spelling
	scope    []string          // repos whose snapshots are consulted
	scopeSet map[string]bool
	filtered bool // a repo or product filter applies to the final list
	auth     gh.Auth
	grinds   map[string]GrindStatus // lower(repo)#pr
	snaps    map[string]poller.Snapshot
	products []products.Product
}

func (v *view) slug(s string) string {
	if r, ok := v.reg[strings.ToLower(s)]; ok {
		return r
	}
	return s
}

func lower(s string) string { return strings.ToLower(s) }

func grindKey(repo string, pr int) string { return fmt.Sprintf("%s#%d", lower(repo), pr) }

// ProductRepos is the docs repo plus the code repos of a product.
func ProductRepos(p products.Product) []string {
	out := []string{p.DocsRepo}
	for _, r := range p.Repos {
		if r.Repo != "" && !strings.EqualFold(r.Repo, p.DocsRepo) {
			out = append(out, r.Repo)
		}
	}
	return out
}

func (b *Builder) collect(ctx context.Context, product, repo string) *view {
	v := &view{ctx: ctx, reg: map[string]string{}, scopeSet: map[string]bool{}, snaps: map[string]poller.Snapshot{}, grinds: map[string]GrindStatus{}}
	if b.d.Products != nil {
		v.products = b.d.Products.Products()
		for _, r := range b.d.Products.Repos() {
			v.reg[lower(r.Slug)] = r.Slug
		}
		for _, p := range v.products {
			for _, s := range ProductRepos(p) {
				if _, ok := v.reg[lower(s)]; !ok {
					v.reg[lower(s)] = s
				}
			}
		}
	}
	add := func(s string) {
		if s == "" || strings.HasPrefix(lower(s), "local/") || v.scopeSet[lower(s)] {
			return
		}
		v.scopeSet[lower(s)] = true
		v.scope = append(v.scope, v.slug(s))
	}
	switch {
	case repo != "":
		add(repo)
		v.filtered = true
	case product != "":
		for _, p := range v.products {
			if strings.EqualFold(p.DocsRepo, product) {
				for _, s := range ProductRepos(p) {
					add(s)
				}
			}
		}
		v.filtered = true
	default:
		if b.d.Snapshots != nil {
			for _, s := range b.d.Snapshots.Watched() {
				add(s)
			}
		}
		for _, p := range v.products {
			for _, s := range ProductRepos(p) {
				add(s)
			}
		}
	}
	if b.d.GH != nil {
		v.auth = b.d.GH.Get(ctx)
	} else {
		v.auth = gh.Auth{OK: true}
	}
	if b.d.Grinds != nil {
		for _, g := range b.d.Grinds.Index() {
			v.grinds[grindKey(g.Repo, g.PR)] = g
		}
	}
	if b.d.Snapshots != nil {
		for _, s := range v.scope {
			v.snaps[lower(s)] = b.d.Snapshots.Snapshot(s)
		}
	}
	return v
}

// Build returns the ranked inbox. product (a docs repo slug) and repo filter the list; items
// without a repo (gh sign-in, blubird, away) always stay.
func (b *Builder) Build(ctx context.Context, product, repo string) List {
	v := b.collect(ctx, product, repo)
	var items []Item
	items = append(items, b.setupItems(v)...)
	items = append(items, b.sessionItems(v)...)
	items = append(items, b.prdItems(v)...)
	items = append(items, b.panelItems(v)...)
	items = append(items, b.prItems(v)...)
	items = append(items, b.grindItems(v)...)
	items = append(items, b.cleanupItems(v)...)
	items = append(items, b.releaseItems(v)...)
	items = append(items, b.dispatchItems(v)...)
	items = append(items, b.awayItems(v)...)

	out := items[:0]
	for _, it := range items {
		if v.filtered && it.Repo != nil && !v.scopeSet[lower(*it.Repo)] {
			continue
		}
		out = append(out, it)
	}
	for i := range out {
		out[i].Urgency = b.urg.of(out[i])
		if out[i].Actions == nil {
			out[i].Actions = []Action{}
		}
	}
	Rank(out)

	stale := []string{}
	if b.d.Snapshots != nil {
		for _, s := range v.scope {
			if !v.snaps[lower(s)].Fresh() {
				stale = append(stale, s)
			}
		}
	}
	sort.Strings(stale)
	n := 0
	for _, it := range out {
		if it.Group != GWait {
			n++
		}
	}
	if out == nil {
		out = []Item{}
	}
	return List{Items: out, Stale: stale, Count: n}
}

// ---- setup / block ----

func (b *Builder) setupItems(v *view) []Item {
	var out []Item
	if !v.auth.OK {
		it := Item{Key: "gh_auth", Group: GBlock, Type: TGHAuth, Kind: "Auth", Title: "GitHub CLI is not signed in",
			Detail: []string{v.auth.Error, "Run `gh auth login` in a terminal, then check again."}}
		it.Actions = []Action{Post("r", "Check again", "/api/refresh", "Checking GitHub", map[string]any{}).WithPrimary()}
		out = append(out, it)
	}
	if b.d.Blubird != nil {
		if st := b.d.Blubird.Status(); !st.Installed {
			it := Item{Key: "blubird_missing", Group: GBlock, Type: TBlubirdMissing, Kind: "Setup", Title: "The blubird plugin is not installed",
				Detail: []string{"Workflow steps from blubird cannot start until it is installed."}}
			if st.Error != "" {
				it.Detail = append(it.Detail, st.Error)
			}
			if st.Busy != "" {
				it.Detail = append(it.Detail, "Now "+st.Busy+".")
			}
			it.Actions = []Action{Post("i", "Install blubird", "/api/blubird/install", "Installing blubird", nil).WithPrimary()}
			out = append(out, it)
		}
	}
	if b.d.Products != nil {
		for _, r := range b.d.Products.Repos() {
			if strings.HasPrefix(lower(r.Slug), "local/") {
				repo := r.Slug
				it := Item{Key: "unpublished:" + r.Slug, Group: GSetup, Type: TRepoUnpublished, Kind: "Setup", Title: r.Slug + " is not on GitHub",
					Repo: &repo, Detail: []string{r.Path}}
				it.Actions = []Action{Open("p", "Publish to GitHub", "#/settings?pane=products&publish="+repo).WithPrimary()}
				out = append(out, it)
			}
		}
	}
	return out
}

// ---- sessions ----

func questionText(r *sessions.Round) string {
	var parts []string
	for _, q := range r.Questions {
		if q.Question != "" {
			parts = append(parts, q.Question)
		}
	}
	return strings.Join(parts, "\n")
}

func (b *Builder) sessionItems(v *view) []Item {
	if b.d.Sessions == nil {
		return nil
	}
	recs := b.d.Sessions.List(sessions.Filter{})
	// newest start per (command, checkout): a failure is only news while nothing newer ran
	newest := map[string]string{}
	skey := func(r sessions.Record) string {
		w := r.CwdPath
		if w == "" {
			w = r.Repo
		}
		return r.Command + "\x00" + lower(w)
	}
	for _, r := range recs {
		if k := skey(r); r.StartedAt > newest[k] {
			newest[k] = r.StartedAt
		}
	}
	var out []Item
	for _, r := range recs {
		if r.Role == "away-answerer" {
			continue
		}
		switch {
		case r.Status == sessions.StWaiting && r.PendingQuestion != nil && r.PendingQuestion.Status == "pending":
			out = append(out, b.questionItem(v, r))
		case r.Status == sessions.StFailed:
			if r.PanelRole == "lens" || r.Dismissed || r.StartedAt < newest[skey(r)] {
				continue
			}
			if it, ok := b.failedItem(v, r); ok {
				out = append(out, it)
			}
		case r.Status == sessions.StDone && r.Stalled != "":
			// a dispatch lane's session is covered by the lane's own stalled row
			if r.Dismissed || r.Kind == "lane" {
				continue
			}
			if it, ok := b.stalledItem(v, r); ok {
				out = append(out, it)
			}
		case r.Status == sessions.StLimited:
			out = append(out, b.limitedItem(v, r))
		case r.Status == sessions.StQueued:
			out = append(out, b.queuedItem(v, r))
		}
	}
	return out
}

func sessionLinks(s sessions.Session) (Links, []string) {
	l := Links{Session: SessionRoute(s.ID)}
	anchors := []string{"session:" + s.ID}
	if s.Link != nil {
		slug := s.Link.Owner + "/" + s.Link.Repo
		l.Issue = IssueURL(slug, s.Link.Issue)
		anchors = append(anchors, fmt.Sprintf("issue:%s#%d", lower(slug), s.Link.Issue))
	}
	return l, anchors
}

func (b *Builder) sessionBase(v *view, r sessions.Record) (Item, sessions.Session) {
	s := b.d.Sessions.Public(r)
	it := Item{Title: s.Title, SessionID: r.ID}
	if s.Repo != nil {
		it.Repo = sp(v.slug(*s.Repo))
	}
	it.Links, it.Anchors = sessionLinks(s)
	return it, s
}

func (b *Builder) questionItem(v *view, r sessions.Record) Item {
	it, _ := b.sessionBase(v, r)
	it.Key, it.Group, it.Type, it.Kind = "question:"+r.ID, GAnswer, TQuestion, "Question"
	it.At = sp(r.StartedAt)
	it.Round = r.PendingQuestion
	it.text = questionText(r.PendingQuestion)
	for _, q := range r.PendingQuestion.Questions {
		it.Detail = append(it.Detail, q.Question)
	}
	if r.PendingQuestion.Held {
		it.Detail = append(it.Detail, "Held while you were away.")
	}
	it.Actions = []Action{
		Open("o", "Answer", SessionRoute(r.ID)).WithPrimary(),
		Post("x", "Stop", "/api/sessions/"+r.ID+"/stop", "Stopped", nil).WithConfirm("Stop this session?"),
	}
	return it
}

func (b *Builder) failedItem(v *view, r sessions.Record) (Item, bool) {
	it, s := b.sessionBase(v, r)
	if r.Link != nil && it.Repo != nil && b.owned(*it.Repo, r.Link.Issue, 0) {
		return it, false
	}
	it.Key, it.Group, it.Type, it.Kind = "failed:"+r.ID, GFix, TSessionFailed, "Failed"
	if r.EndedAt != "" {
		it.At = sp(r.EndedAt)
	} else {
		it.At = sp(r.StartedAt)
	}
	it.text = r.Error
	if r.Error != "" {
		it.Detail = []string{r.Error}
	}
	if s.Step != nil {
		it.Detail = append(it.Detail, "step "+*s.Step)
	}
	it.Actions = []Action{
		Post("f", "Rerun", "/api/sessions/"+r.ID+"/rerun", "Started again", nil).WithPrimary(),
		Open("o", "Open session", SessionRoute(r.ID)),
		Post("d", "Dismiss", "/api/sessions/"+r.ID+"/dismiss", "Dismissed", nil).WithClears(),
	}
	return it, true
}

func (b *Builder) stalledItem(v *view, r sessions.Record) (Item, bool) {
	it, s := b.sessionBase(v, r)
	if r.Link != nil && it.Repo != nil && b.owned(*it.Repo, r.Link.Issue, 0) {
		return it, false
	}
	it.Key, it.Group, it.Type, it.Kind = "stalled:"+r.ID, GFix, TSessionStalled, "Stalled"
	if r.EndedAt != "" {
		it.At = sp(r.EndedAt)
	} else {
		it.At = sp(r.StartedAt)
	}
	it.text = r.Stalled
	it.Detail = []string{"Stalled: " + r.Stalled}
	if s.Step != nil {
		it.Detail = append(it.Detail, "step "+*s.Step)
	}
	it.Actions = []Action{
		Post("c", "Continue", "/api/sessions/"+r.ID+"/continue", "Continuing", nil).WithPrimary().WithClears(),
		Open("o", "Open session", SessionRoute(r.ID)),
		Post("d", "Dismiss", "/api/sessions/"+r.ID+"/dismiss", "Dismissed", nil).WithClears(),
	}
	return it, true
}

func (b *Builder) limitedItem(v *view, r sessions.Record) Item {
	it, s := b.sessionBase(v, r)
	it.Key, it.Group, it.Type, it.Kind = "limited:"+r.ID, GWait, TLimited, "Limited"
	it.At = sp(r.StartedAt)
	it.Detail = []string{"account " + s.Account}
	if r.LimitResetsAt > 0 {
		it.Detail = append(it.Detail, "resets "+time.Unix(r.LimitResetsAt, 0).UTC().Format(time.RFC3339))
	}
	if r.AutoResume != nil && *r.AutoResume && !r.Hold {
		it.Detail = append(it.Detail, "resumes by itself")
	}
	it.Actions = []Action{
		Open("o", "Open session", SessionRoute(r.ID)).WithPrimary(),
		Post("x", "Stop", "/api/sessions/"+r.ID+"/stop", "Stopped", nil).WithConfirm("Stop this session?"),
	}
	return it
}

func (b *Builder) queuedItem(v *view, r sessions.Record) Item {
	it, _ := b.sessionBase(v, r)
	it.Key, it.Group, it.Type, it.Kind = "queued:"+r.ID, GWait, TQueued, "Queued"
	it.At = sp(r.StartedAt)
	if r.Note != "" {
		it.Detail = []string{r.Note}
	}
	it.Actions = []Action{
		Post("s", "Start now", "/api/sessions/"+r.ID+"/start-now", "Started", nil).WithPrimary(),
		Open("o", "Open session", SessionRoute(r.ID)),
	}
	return it
}

// ---- PRDs and review panels ----

// ApproveArgs is the create-prd argument that approves a reviewed PRD (API §9.1).
func ApproveArgs(path string) string {
	return path + " — the team has reviewed it; approve it"
}

func approveAction(key, docs, path string) Action {
	return Start(key, "Approve + create epic", "Approved; creating the epic", map[string]any{
		"step": "create-prd", "repo": docs, "product": docs, "args": ApproveArgs(path),
	}).WithPrimary().WithClears().WithConfirm("Approve this PRD and create its epic?")
}

func (b *Builder) prdItems(v *view) []Item {
	if b.d.Products == nil {
		return nil
	}
	var out []Item
	for _, p := range v.products {
		if !v.scopeSet[lower(p.DocsRepo)] {
			continue
		}
		prds, err := b.d.Products.PRDs(p.DocsRepo)
		if err != nil {
			continue
		}
		for _, d := range prds {
			if d.Status != "In review" {
				continue
			}
			docs := v.slug(p.DocsRepo)
			it := Item{Key: "prd_approval:" + docs + ":" + d.Path, Group: GDecide, Type: TPRDApproval, Kind: "Approval",
				Title: d.Title, Repo: &docs, Detail: []string{d.Path + " is in review"},
				Anchors: []string{"prd:" + lower(docs) + ":" + d.Path}}
			it.Links.PRD = PRDRoute(docs, d.Path)
			it.Actions = []Action{approveAction("e", docs, d.Path), Open("o", "Read PRD", it.Links.PRD)}
			out = append(out, it)
		}
	}
	return out
}

func (b *Builder) prdStatus(artifact string) string {
	if b.d.PRDStatus != nil {
		return b.d.PRDStatus(artifact)
	}
	f, err := os.Open(artifact)
	if err != nil {
		return ""
	}
	defer f.Close()
	buf := make([]byte, 4000)
	n, _ := f.Read(buf)
	st, _, _ := products.ParsePRD(string(buf[:n]), "")
	return st
}

func panelTime(id string) *string {
	// p-YYYYMMDDTHHMMSSZ-xxxxxx
	if len(id) < 18 {
		return nil
	}
	t, err := time.Parse("20060102T150405Z", id[2:18])
	if err != nil {
		return nil
	}
	return sp(t.UTC().Format(time.RFC3339))
}

func (b *Builder) panelItems(v *view) []Item {
	if b.d.Panels == nil {
		return nil
	}
	newest := map[string]Panel{}
	for _, p := range b.d.Panels.List() {
		if cur, ok := newest[p.Artifact]; !ok || p.ID > cur.ID {
			newest[p.Artifact] = p
		}
	}
	var out []Item
	for _, p := range newest {
		i := strings.Index(p.Artifact, "docs/prds/")
		if i < 0 || (p.State != "cap reached" && p.State != "approved") {
			continue
		}
		if b.prdStatus(p.Artifact) == "Approved" {
			continue
		}
		path := p.Artifact[i:]
		repo := v.slug(p.Repo)
		it := Item{Group: GDecide, Repo: &repo, At: panelTime(p.ID), Title: path,
			Anchors: []string{"prd:" + lower(repo) + ":" + path}}
		it.Links.PRD = PRDRoute(repo, path)
		if p.State == "cap reached" {
			it.Key, it.Type, it.Kind = "review_cap:"+p.ID, TReviewCap, "Review cap"
			it.Detail = []string{fmt.Sprintf("%d of %d lenses approve at round %d", p.Status.Approved, p.Status.Total, p.Round)}
			it.Actions = []Action{
				Post("m", "Two more rounds", "/api/review/"+p.ID+"/rounds", "Added two rounds", map[string]any{"add": 2}).WithPrimary(),
				Open("o", "Read PRD", it.Links.PRD),
			}
		} else {
			it.Key, it.Type, it.Kind = "review_approved:"+p.ID, TReviewApproved, "Approved"
			it.Detail = []string{"Every lens approves."}
			it.Actions = []Action{
				approveAction("e", repo, path),
				Open("o", "Read PRD", it.Links.PRD),
			}
		}
		out = append(out, it)
	}
	return out
}

// ---- pull requests ----

const conflictText = "A pull request has a merge conflict with its base branch."

// IssueOfPR is the issue an open PR is for: the first ref that is an open issue, else the first.
func IssueOfPR(d poller.Data, p poller.OpenPR) int {
	for _, n := range p.Refs {
		for _, is := range d.Issues {
			if is.N == n {
				return n
			}
		}
	}
	if len(p.Refs) > 0 {
		return p.Refs[0]
	}
	return 0
}

func (b *Builder) grindOn(repo string, issue int) bool {
	return b.d.Settings != nil && b.d.Settings.GrindOn(repo, issue)
}

func (b *Builder) owned(repo string, issue, pr int) bool {
	return b.d.Dispatch != nil && b.d.Dispatch.Owned(repo, issue, pr)
}

func owner(repo string) string {
	o, _, _ := strings.Cut(repo, "/")
	return o
}

// GrindFactOf maps a grind status to the merge gate's view of it (approved counts as done).
func GrindFactOf(g GrindStatus, ok bool) *poller.GrindFact {
	if !ok {
		return nil
	}
	st := g.State
	if st == "approved" {
		st = "done"
	}
	return &poller.GrindFact{State: st}
}

func (b *Builder) prItems(v *view) []Item {
	var out []Item
	for _, repo := range v.scope {
		snap := v.snaps[lower(repo)]
		if !snap.Fresh() {
			continue
		}
		for _, p := range snap.Data.OpenPRs {
			issue := IssueOfPR(snap.Data, p)
			if b.owned(repo, issue, p.N) {
				continue
			}
			anchors := []string{fmt.Sprintf("pr:%s#%d", lower(repo), p.N)}
			if issue > 0 {
				anchors = append(anchors, fmt.Sprintf("issue:%s#%d", lower(repo), issue))
			}
			base := Item{Repo: sp(repo), Title: fmt.Sprintf("PR #%d %s", p.N, p.Title), Anchors: anchors}
			base.Links.PR = p.URL
			if issue > 0 {
				base.Links.Issue = IssueURL(repo, issue)
			}
			if p.Conflict {
				it := base
				it.Key, it.Group, it.Type, it.Kind = fmt.Sprintf("pr_conflict:%s#%d", repo, p.N), GFix, TPRConflict, "Conflict"
				it.text = conflictText
				it.Detail = []string{conflictText}
				it.Actions = []Action{
					Open("o", "Open PR", p.URL).WithPrimary(),
					Start("f", "Fix with pr-review", "Started pr-review --fix", map[string]any{
						"step": "pr-review", "repo": repo, "issue": issue, "args": p.URL + " --fix", "guard": true}),
				}
				out = append(out, it)
				continue
			}
			g, ok := v.grinds[grindKey(repo, p.N)]
			pc := p
			if !poller.MergeReady(&pc, GrindFactOf(g, ok), b.grindOn(repo, issue), v.auth.Solo(owner(repo))) {
				continue
			}
			it := base
			it.Key, it.Group, it.Type, it.Kind = fmt.Sprintf("pr_ready:%s#%d", repo, p.N), GDecide, TPRReady, "PR ready"
			if p.Reviewer != nil {
				it.Detail = append(it.Detail, "approved by "+*p.Reviewer)
			}
			it.Detail = append(it.Detail, fmt.Sprintf("%d checks green", p.Checks))
			it.Actions = []Action{
				Post("m", "Merge", fmt.Sprintf("/api/pulls/%s/%d/merge", repo, p.N), fmt.Sprintf("Merged PR #%d", p.N),
					map[string]any{"sha": p.SHA}).WithPrimary().WithClears().WithConfirm(fmt.Sprintf("Merge PR #%d?", p.N)),
				Open("o", "Open PR", p.URL),
			}
			out = append(out, it)
		}
	}
	return out
}

func (b *Builder) grindItems(v *view) []Item {
	var out []Item
	for _, g := range v.grinds {
		if g.State != "paused" {
			continue
		}
		repo := v.slug(g.Repo)
		if v.filtered && !v.scopeSet[lower(repo)] {
			continue
		}
		stamp, reason := "", ""
		if g.Reason != nil {
			stamp, reason = SplitReason(*g.Reason)
		}
		issue := 0
		url := PRURL(repo, g.PR)
		if snap, ok := v.snaps[lower(repo)]; ok && snap.Fresh() {
			var found *poller.OpenPR
			for i := range snap.Data.OpenPRs {
				if snap.Data.OpenPRs[i].N == g.PR {
					found = &snap.Data.OpenPRs[i]
				}
			}
			if found == nil {
				continue // the PR is gone: the pause is moot
			}
			issue = IssueOfPR(snap.Data, *found)
			url = found.URL
		}
		if b.owned(repo, issue, g.PR) {
			continue
		}
		it := Item{Key: fmt.Sprintf("grind:%s#%d", repo, g.PR), Group: GFix, Type: TGrindPaused, Kind: "Grind paused",
			Title: fmt.Sprintf("Grind paused on PR #%d", g.PR), Repo: &repo, text: reason,
			Anchors: []string{fmt.Sprintf("pr:%s#%d", lower(repo), g.PR)}}
		it.Links.PR = url
		if issue > 0 {
			it.Links.Issue = IssueURL(repo, issue)
			it.Anchors = append(it.Anchors, fmt.Sprintf("issue:%s#%d", lower(repo), issue))
		}
		switch {
		case stamp != "":
			it.At = sp(stamp)
		case g.Updated != nil:
			it.At = g.Updated
		}
		if reason != "" {
			it.Detail = append(it.Detail, reason)
		}
		it.Detail = append(it.Detail, fmt.Sprintf("round %d", g.Rounds))
		it.Actions = []Action{
			Post("g", "Resume grind", "/api/grinds", "Grind started", map[string]any{"repo": repo, "pr": g.PR}).WithPrimary(),
			Open("o", "Open PR", url),
			Post("s", "Stop grind", fmt.Sprintf("/api/grinds/%s/%d/stop", repo, g.PR), "Grind stopped", nil).WithClears(),
		}
		out = append(out, it)
	}
	return out
}

func (b *Builder) cleanupItems(v *view) []Item {
	if b.d.Cleanup == nil {
		return nil
	}
	var out []Item
	for _, repo := range v.scope {
		flags := b.d.Cleanup.Flags(repo)
		for n, f := range flags {
			it := Item{Key: fmt.Sprintf("cleanup:%s#%d", repo, n), Group: GFix, Type: TNeedsCleanup, Kind: "Cleanup",
				Title: fmt.Sprintf("#%d is merged but its worktree has loose work", n), Repo: sp(repo),
				Anchors: []string{fmt.Sprintf("issue:%s#%d", lower(repo), n)}}
			it.Links.Issue = IssueURL(repo, n)
			it.Detail = append(it.Detail, capDetail("uncommitted: ", f.Uncommitted)...)
			it.Detail = append(it.Detail, capDetail("unpushed: ", f.Unpushed)...)
			it.Actions = []Action{
				Post("c", "Clean up", fmt.Sprintf("/api/repos/%s/cleanup", repo), fmt.Sprintf("Cleaned up #%d", n),
					map[string]any{"issue": n, "confirm": true}).WithPrimary().WithClears().
					WithConfirm("Remove the worktree and branch, including the loose work listed?"),
				Open("o", "Open issue", it.Links.Issue),
			}
			out = append(out, it)
		}
	}
	return out
}

// ---- releases ----

func (b *Builder) releaseItems(v *view) []Item {
	if b.d.Releases == nil {
		return nil
	}
	var out []Item
	for _, r := range b.d.Releases.List("") {
		if r.Stage != "notify" || r.DryRun || r.Note == nil || strings.TrimSpace(*r.Note) == "" || r.NotePosted != nil {
			continue
		}
		repo := v.slug(r.Repo)
		title := "Release note for " + repo
		if r.PR != nil {
			title = fmt.Sprintf("Release note for %s #%d", repo, *r.PR)
		}
		it := Item{Key: "release_note:" + r.ID, Group: GDecide, Type: TReleaseNote, Kind: "Release", Title: title,
			Repo: &repo, At: sp(r.UpdatedAt), Note: *r.Note, Anchors: []string{"release:" + r.ID}}
		if r.PRURL != nil {
			it.Links.PR = *r.PRURL
		}
		if r.Error != nil && *r.Error != "" {
			it.Detail = []string{*r.Error}
		}
		it.Actions = []Action{
			Post("p", "Post note", "/api/releases/"+r.ID+"/post", "Posted once", nil).WithPrimary().WithClears().WithConfirm("Post this release note? It is sent once."),
			Open("e", "Edit note", "#/releases/"+r.ID),
			Post("x", "Skip", "/api/releases/"+r.ID+"/skip", "Skipped", nil).WithClears(),
		}
		out = append(out, it)
	}
	return out
}

// ---- dispatch ----

func (b *Builder) dispatchItems(v *view) []Item {
	if b.d.Dispatch == nil {
		return nil
	}
	now := b.now()
	var out []Item
	for _, d := range b.d.Dispatch.List() {
		route := "#/dispatch/" + d.ID
		anchors := func(l Lane) []string {
			a := []string{"dispatch:" + d.ID, fmt.Sprintf("issue:%s#%d", lower(l.Repo), l.N)}
			if l.PR != nil {
				a = append(a, fmt.Sprintf("pr:%s#%d", lower(l.Repo), *l.PR))
			}
			return a
		}
		if d.State == "done" {
			if d.SeenDone || d.EndedAt == nil || now.Sub(time.Unix(*d.EndedAt, 0)) > 7*24*time.Hour {
				continue
			}
			it := Item{Key: "dispatch:" + d.ID + ":done", Group: GDecide, Type: TDispatchDone, Kind: "Dispatch",
				Title: d.Title + " is done", At: sp(time.Unix(*d.EndedAt, 0).UTC().Format(time.RFC3339)),
				Anchors: []string{"dispatch:" + d.ID}}
			if d.Settings.FeatureBranch != nil {
				it.Detail = []string{"feature branch " + *d.Settings.FeatureBranch}
			}
			it.Actions = []Action{
				Post("s", "Mark seen", "/api/dispatches/"+d.ID+"/seen", "Marked seen", map[string]any{}).WithPrimary().WithClears(),
				Open("o", "Open dispatch", route),
			}
			out = append(out, it)
			continue
		}
		if d.State != "running" && d.State != "paused" {
			continue
		}
		for _, l := range d.Lanes {
			repo := v.slug(l.Repo)
			base := func(suffix, group, typ string) Item {
				return Item{Key: "dispatch:" + d.ID + ":" + l.Key + ":" + suffix, Group: group, Type: typ, Kind: "Dispatch",
					Title: fmt.Sprintf("#%d %s", l.N, l.Title), Repo: &repo, Anchors: anchors(l)}
			}
			lane := func(action string) map[string]any { return map[string]any{"lane": l.Key, "action": action} }
			lanePath := "/api/dispatches/" + d.ID + "/lane"
			if l.NeedsYou != nil && *l.NeedsYou != "" {
				it := base("needs", GAnswer, TDispatchNeeds)
				it.Detail = []string{*l.NeedsYou}
				it.Actions = []Action{Open("o", "Open dispatch", route).WithPrimary()}
				out = append(out, it)
			}
			if l.Stalled != nil && *l.Stalled != "" { // idle guard: stopped before a ready PR, not a question
				it := base("stalled", GFix, TDispatchStalled)
				it.Detail = []string{"Stalled: " + *l.Stalled}
				it.Actions = []Action{
					Post("r", "Retry", lanePath, "Retrying the lane", lane("retry")).WithPrimary(),
					Open("o", "Open dispatch", route),
				}
				out = append(out, it)
			}
			if l.Held != nil && *l.Held != "" {
				it := base("held", GFix, TDispatchHeld)
				it.Detail = []string{*l.Held}
				it.Actions = []Action{
					Post("r", "Retry", lanePath, "Retrying the lane", lane("retry")).WithPrimary(),
					Post("s", "Skip", lanePath, "Lane skipped", lane("skip")).WithConfirm("Skip this lane?").WithClears(),
					Open("o", "Open dispatch", route),
				}
				out = append(out, it)
			}
			if l.Stage == "awaiting_merge" {
				it := base("merge", GDecide, TDispatchMerge)
				if l.PR != nil {
					it.Detail = []string{fmt.Sprintf("PR #%d is ready to merge", *l.PR)}
					it.Links.PR = PRURL(repo, *l.PR)
				}
				it.Actions = []Action{
					Post("m", "Merge", lanePath, "Merging", lane("merge")).WithPrimary().WithClears().WithConfirm("Merge this lane's PR?"),
					Open("o", "Open dispatch", route),
				}
				out = append(out, it)
			}
			if l.LimitedUntil != nil && *l.LimitedUntil > now.Unix() {
				it := base("limited", GWait, TDispatchLimited)
				it.Detail = []string{"Claude usage limit", "resets " + time.Unix(*l.LimitedUntil, 0).UTC().Format(time.RFC3339)}
				it.Actions = []Action{Open("o", "Open dispatch", route).WithPrimary()}
				out = append(out, it)
			}
		}
	}
	return out
}

// ---- away ----

func (b *Builder) awayItems(v *view) []Item {
	if b.d.Away == nil {
		return nil
	}
	a := b.d.Away.Public()
	if a.Summary == nil {
		return nil
	}
	title := "Away mode ended"
	if a.Summary.Held > 0 {
		title = fmt.Sprintf("Away mode ended with %d held for you", a.Summary.Held)
	}
	it := Item{Key: "away_summary", Group: GDecide, Type: TAwaySummary, Kind: "Away", Title: title,
		At: sp(time.Unix(a.Summary.Ended, 0).UTC().Format(time.RFC3339)), Anchors: []string{"away"}}
	it.Actions = []Action{Post("d", "Dismiss summary", "/api/away/dismiss", "Dismissed", nil).WithPrimary().WithClears()}
	return []Item{it}
}

// maxLooseDetail bounds the per-item detail lines: a worktree with a build cache can hold tens of
// thousands of files, which made /api/inbox megabytes large.
const maxLooseDetail = 12

func capDetail(prefix string, lines []string) []string {
	out := make([]string, 0, maxLooseDetail+1)
	for i, s := range lines {
		if i == maxLooseDetail {
			out = append(out, fmt.Sprintf("%s… and %d more", prefix, len(lines)-maxLooseDetail))
			break
		}
		out = append(out, prefix+s)
	}
	return out
}
