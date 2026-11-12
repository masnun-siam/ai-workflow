package views

import (
	"context"
	"fmt"
	"net/url"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Features is the old aiw Features view: one row per PRD with its epic, the epic's issues, the
// peer-review panel, the dispatch, the sessions and a server-built next step.

type FeaturePR struct {
	N        int    `json:"n"`
	URL      string `json:"url"`
	Draft    bool   `json:"draft"`
	CI       string `json:"ci"`
	Review   string `json:"review"`
	Conflict bool   `json:"conflict"`
	SHA      string `json:"sha"`
}

// FeatureIssue is one child of the epic. State: unrefined | blocked | ready | in_progress | waiting |
// failed | in_review | mergeable | conflict | ci_failed | dispatch.
type FeatureIssue struct {
	Key      string         `json:"key"`
	Repo     string         `json:"repo"`
	N        int            `json:"n"`
	Title    string         `json:"title"`
	URL      string         `json:"url"`
	State    string         `json:"state"`
	Refined  bool           `json:"refined"`
	Bug      bool           `json:"bug"`
	Blockers []string       `json:"blockers"`
	Priority *string        `json:"priority"`
	PR       *FeaturePR     `json:"pr"`
	Session  *string        `json:"session"`
	Actions  []inbox.Action `json:"actions"`
}

type FeatureEpic struct {
	Key   string `json:"key"`
	Repo  string `json:"repo"`
	N     int    `json:"n"`
	Title string `json:"title"`
	URL   string `json:"url"`
}

type FeatureDispatch struct {
	ID     string `json:"id"`
	State  string `json:"state"`
	Lanes  int    `json:"lanes"`
	Closed int    `json:"closed"`
	Needs  int    `json:"needs"`
}

type FeatureSession struct {
	ID        string  `json:"id"`
	Status    string  `json:"status"`
	Skill     string  `json:"skill"`
	Title     string  `json:"title"`
	StartedAt string  `json:"started_at"`
	Cost      float64 `json:"cost"`
}

type FeatureCounts struct {
	Open      int `json:"open"`
	Unrefined int `json:"unrefined"`
	Ready     int `json:"ready"`
	Review    int `json:"review"`
	Mergeable int `json:"mergeable"`
	Done      int `json:"done"`
}

type Feature struct {
	Product  string           `json:"product"`
	Slug     string           `json:"slug"`
	Title    string           `json:"title"`
	Status   string           `json:"status"` // PRD status
	Path     string           `json:"path"`
	Module   *string          `json:"module"`
	PRDRoute string           `json:"prd_route"`
	Stage    string           `json:"stage"` // draft | review | approved | tasks | building | shipped
	Bay      string           `json:"bay"`   // you | go | running | shipped
	Next     string           `json:"next"`  // one line: what happens next
	Epic     *FeatureEpic     `json:"epic"`
	Issues   []FeatureIssue   `json:"issues"`
	Done     []FeatureEpicSub `json:"done"`
	Counts   FeatureCounts    `json:"counts"`
	Panel    *inbox.Panel     `json:"panel"`
	Dispatch *FeatureDispatch `json:"dispatch"`
	Live     int              `json:"live"`
	Sessions []FeatureSession `json:"sessions"`
	Actions  []inbox.Action   `json:"actions"` // next-step buttons, primary first
}

type FeatureEpicSub struct {
	Key   string `json:"key"`
	N     int    `json:"n"`
	Title string `json:"title"`
	URL   string `json:"url"`
}

type FeatureList struct {
	Product  string    `json:"product"`
	Stale    []string  `json:"stale"`
	Features []Feature `json:"features"`
}

// FeatureRoute is the UI route of one feature.
func FeatureRoute(product, slug, tab string) string {
	r := "#/features/" + url.PathEscape(slug) + "?product=" + product
	if tab != "" {
		r += "&tab=" + tab
	}
	return r
}

// Features builds the list for one product ("" = the first).
func (s *Service) Features(ctx context.Context, product string) FeatureList {
	p, ok := s.Product(product)
	out := FeatureList{Product: product, Stale: []string{}, Features: []Feature{}}
	if !ok {
		return out
	}
	out.Product = p.DocsRepo
	prds, err := s.PRDs(p.DocsRepo)
	if err != nil {
		return out
	}
	repos := inbox.ProductRepos(p)
	snaps := map[string]poller.Snapshot{}
	index := map[string]found{}
	var all []found
	if s.d.Snapshots != nil {
		for _, repo := range repos {
			sn := s.d.Snapshots.Snapshot(repo)
			snaps[lower(repo)] = sn
			if !sn.Fresh() {
				out.Stale = append(out.Stale, repo)
			}
			for _, is := range sn.Data.Issues {
				f := found{repo, is}
				all = append(all, f)
				index[fmt.Sprintf("%s#%d", lower(repo), is.N)] = f
			}
		}
	}
	// open PR per issue
	prOf := map[string]poller.OpenPR{}
	for _, repo := range repos {
		d := snaps[lower(repo)].Data
		for _, pr := range d.OpenPRs {
			if n := inbox.IssueOfPR(d, pr); n > 0 {
				k := fmt.Sprintf("%s#%d", lower(repo), n)
				if _, dup := prOf[k]; !dup {
					prOf[k] = pr
				}
			}
		}
	}
	// newest panel per artifact
	panels := map[string]inbox.Panel{}
	if s.d.Panels != nil {
		for _, pn := range s.d.Panels.List() {
			if cur, ok := panels[pn.Artifact]; !ok || pn.ID > cur.ID {
				panels[pn.Artifact] = pn
			}
		}
	}
	var recs []sessions.Record
	if s.d.Sessions != nil {
		recs = s.d.Sessions.List(sessions.Filter{})
	}
	var dispatches []inbox.Dispatch
	if s.d.Dispatch != nil {
		dispatches = s.d.Dispatch.List()
	}
	for _, d := range prds {
		out.Features = append(out.Features, s.feature(p, d, all, index, prOf, panels, recs, dispatches))
	}
	sort.SliceStable(out.Features, func(i, j int) bool { return bayRank[out.Features[i].Bay] < bayRank[out.Features[j].Bay] })
	return out
}

var bayRank = map[string]int{"you": 0, "go": 1, "running": 2, "shipped": 3}

func (s *Service) feature(p products.Product, d products.PRD, all []found, index map[string]found, prOf map[string]poller.OpenPR,
	panels map[string]inbox.Panel, recs []sessions.Record, dispatches []inbox.Dispatch) Feature {
	docs := p.DocsRepo
	f := Feature{Product: docs, Slug: d.Slug, Title: d.Title, Status: d.Status, Path: d.Path, Module: d.Module,
		PRDRoute: inbox.PRDRoute(docs, d.Path), Issues: []FeatureIssue{}, Done: []FeatureEpicSub{}, Sessions: []FeatureSession{}, Actions: []inbox.Action{}}
	if pn, ok := panels[filepath.Join(p.Path, filepath.FromSlash(d.Path))]; ok {
		f.Panel = &pn
	}

	// the epic and its children
	var epicIssue *poller.Issue
	if d.Epic != nil {
		if e, ok := index[lower(*d.Epic)]; ok {
			is := e.issue
			epicIssue = &is
			f.Epic = &FeatureEpic{Key: *d.Epic, Repo: e.repo, N: is.N, Title: strings.TrimSpace(strings.TrimPrefix(is.Title, "Epic:")), URL: inbox.IssueURL(e.repo, is.N)}
		}
	}
	issueKeys := map[string]bool{}
	if f.Epic != nil {
		seen := map[string]bool{}
		var kids []found
		add := func(k found) {
			key := fmt.Sprintf("%s#%d", lower(k.repo), k.issue.N)
			if !seen[key] && !hasLabel(k.issue.Labels, "epic") {
				seen[key] = true
				kids = append(kids, k)
			}
		}
		for _, ref := range epicIssue.SubIssues {
			if k, ok := index[lower(ref.Repo)+"#"+strconv.Itoa(ref.N)]; ok {
				add(k)
			}
		}
		for _, k := range all {
			if k.issue.Parent != nil && strings.EqualFold(k.issue.Parent.Repo, f.Epic.Repo) && k.issue.Parent.N == f.Epic.N {
				add(k)
			}
		}
		sort.Slice(kids, func(i, j int) bool { return kids[i].issue.N < kids[j].issue.N })
		latest := latestByIssue(recs)
		for _, k := range kids {
			fi := s.featureIssue(k, prOf, latest)
			issueKeys[lower(fi.Key)] = true
			f.Issues = append(f.Issues, fi)
		}
		for _, c := range epicIssue.ClosedSubs {
			f.Done = append(f.Done, FeatureEpicSub{Key: c.Ref.String(), N: c.N, Title: c.Title, URL: inbox.IssueURL(c.Repo, c.N)})
		}
		issueKeys[lower(f.Epic.Key)] = true
	}
	for _, i := range f.Issues {
		f.Counts.Open++
		switch i.State {
		case "unrefined":
			f.Counts.Unrefined++
		case "ready":
			f.Counts.Ready++
		case "in_review", "conflict", "ci_failed":
			f.Counts.Review++
		case "mergeable":
			f.Counts.Mergeable++
		}
	}
	f.Counts.Done = len(f.Done)

	// dispatch on this epic, or owning its issues
	for _, dp := range dispatches {
		if dp.State != "running" && dp.State != "paused" {
			continue
		}
		mine := f.Epic != nil && dp.Epic != nil && strings.EqualFold(*dp.Epic, f.Epic.Key)
		for _, l := range dp.Lanes {
			mine = mine || issueKeys[lower(l.Key)]
		}
		if !mine {
			continue
		}
		fd := &FeatureDispatch{ID: dp.ID, State: dp.State, Lanes: len(dp.Lanes)}
		for _, l := range dp.Lanes {
			if l.Stage == "closed" {
				fd.Closed++
			}
			if l.NeedsYou != nil {
				fd.Needs++
			}
		}
		f.Dispatch = fd
		break
	}

	// sessions about the PRD or the epic's issues
	for _, rec := range recs {
		if rec.PanelRole == "lens" {
			continue
		}
		mine := rec.Link != nil && issueKeys[lower(fmt.Sprintf("%s/%s#%d", rec.Link.Owner, rec.Link.Repo, rec.Link.Issue))]
		mine = mine || (rec.Args != "" && strings.Contains(rec.Args, d.Path))
		if f.Panel != nil && f.Panel.RootSession != nil && *f.Panel.RootSession == rec.ID {
			mine = true
		}
		if !mine {
			continue
		}
		pub := s.d.Sessions.Public(rec)
		cost := 0.0
		if pub.Cost != nil {
			cost = *pub.Cost
		}
		f.Sessions = append(f.Sessions, FeatureSession{ID: pub.ID, Status: string(rec.Status), Skill: skillName(pub), Title: pub.Title, StartedAt: pub.StartedAt, Cost: cost})
		if rec.Status.Live() {
			f.Live++
		}
	}
	sort.Slice(f.Sessions, func(i, j int) bool { return f.Sessions[i].StartedAt > f.Sessions[j].StartedAt })
	if len(f.Sessions) > 30 {
		f.Sessions = f.Sessions[:30]
	}

	s.nextStep(&f, docs)
	return f
}

// latestByIssue maps "owner/name#n" (lowercase) to its newest session record.
func latestByIssue(recs []sessions.Record) map[string]sessions.Record {
	out := map[string]sessions.Record{}
	for _, r := range recs {
		if r.Link == nil || r.PanelRole == "lens" {
			continue
		}
		k := lower(fmt.Sprintf("%s/%s#%d", r.Link.Owner, r.Link.Repo, r.Link.Issue))
		if cur, ok := out[k]; !ok || r.ID > cur.ID {
			out[k] = r
		}
	}
	return out
}

func (s *Service) featureIssue(k found, prOf map[string]poller.OpenPR, latest map[string]sessions.Record) FeatureIssue {
	is := k.issue
	key := fmt.Sprintf("%s#%d", k.repo, is.N)
	fi := FeatureIssue{Key: key, Repo: k.repo, N: is.N, Title: is.Title, URL: inbox.IssueURL(k.repo, is.N), Refined: hasLabel(is.Labels, "refined"),
		Bug: hasLabel(is.Labels, "bug"), Blockers: []string{}, Priority: is.Priority, Actions: []inbox.Action{}}
	for _, b := range is.BlockedBy {
		if b.State == "OPEN" {
			fi.Blockers = append(fi.Blockers, "#"+strconv.Itoa(b.N))
		}
	}
	n := strconv.Itoa(is.N)
	if pr, ok := prOf[lower(key)]; ok {
		fi.PR = &FeaturePR{N: pr.N, URL: pr.URL, Draft: pr.Draft, CI: pr.CI, Review: pr.Review, Conflict: pr.Conflict, SHA: pr.SHA}
	}
	if rec, ok := latest[lower(key)]; ok {
		id := rec.ID
		fi.Session = &id
	}
	rec, hasRec := latest[lower(key)]
	owned := s.d.Dispatch != nil && s.d.Dispatch.Owned(k.repo, is.N, 0)
	implement := start("i", "Start", "Started implement-issue "+n, "implement-issue", k.repo, map[string]any{"issue": is.N, "args": n, "guard": true})
	switch {
	case owned:
		fi.State = "dispatch"
	case hasRec && rec.Status == sessions.StWaiting:
		fi.State = "waiting"
		fi.Actions = append(fi.Actions, inbox.Open("a", "Answer", inbox.SessionRoute(rec.ID)).WithPrimary())
	case hasRec && rec.Status.Live():
		fi.State = "in_progress"
		fi.Actions = append(fi.Actions, inbox.Open("w", "Watch", inbox.SessionRoute(rec.ID)))
	case fi.PR != nil && !fi.PR.Draft && fi.PR.Conflict:
		fi.State = "conflict"
		fi.Actions = append(fi.Actions, start("r", "Resolve", "Started implement-issue "+n, "implement-issue", k.repo,
			map[string]any{"issue": is.N, "args": fmt.Sprintf("%d (PR #%d has merge conflicts with its base: resolve them and push)", is.N, fi.PR.N)}))
	case fi.PR != nil && !fi.PR.Draft && fi.PR.CI == "failure":
		fi.State = "ci_failed"
		fi.Actions = append(fi.Actions, inbox.Open("p", "Open PR", fi.PR.URL))
	case fi.PR != nil && !fi.PR.Draft && fi.PR.Review == "approved" && fi.PR.CI != "pending" && fi.PR.SHA != "":
		fi.State = "mergeable"
		fi.Actions = append(fi.Actions, mergeAction(k.repo, fi.PR.N, fi.PR.SHA))
	case fi.PR != nil && !fi.PR.Draft:
		fi.State = "in_review"
		fi.Actions = append(fi.Actions, inbox.Open("p", "Open PR", fi.PR.URL))
	case hasRec && rec.Status == sessions.StFailed:
		fi.State = "failed"
		fi.Actions = append(fi.Actions, inbox.Post("r", "Retry", "/api/sessions/"+rec.ID+"/rerun", "Retrying", nil).WithPrimary())
	case !fi.Refined && fi.PR == nil:
		fi.State = "unrefined"
		fi.Actions = append(fi.Actions, start("e", "Refine", "Started refine-issues "+n, "refine-issues", k.repo, map[string]any{"issue": is.N, "args": n}))
	case len(fi.Blockers) > 0:
		fi.State = "blocked"
	default:
		fi.State = "ready"
		fi.Actions = append(fi.Actions, implement.WithPrimary())
	}
	return fi
}

func mergeAction(repo string, pr int, sha string) inbox.Action {
	owner, name, _ := strings.Cut(repo, "/")
	return inbox.Post("m", fmt.Sprintf("Merge #%d", pr), fmt.Sprintf("/api/pulls/%s/%s/%d/merge", owner, name, pr), fmt.Sprintf("Merged #%d", pr),
		map[string]any{"sha": sha}).WithConfirm(fmt.Sprintf("Merge PR #%d into its base now?", pr))
}

// nextStep fills Stage, Bay, Next and Actions (old aiw nextStep.ts).
func (s *Service) nextStep(f *Feature, docs string) {
	tab := func(t string) string { return FeatureRoute(docs, f.Slug, t) }
	approve := inbox.Start("p", "Approve PRD", "Approved; creating the epic", map[string]any{
		"step": "create-prd", "repo": docs, "product": docs, "args": inbox.ApproveArgs(f.Path)}).WithConfirm("Approve this PRD and create its epic?")
	add := func(a ...inbox.Action) { f.Actions = append(f.Actions, a...) }
	switch {
	case f.Status == "Done" || (f.Epic == nil && f.Status == "Approved" && f.Counts.Done > 0):
		f.Stage, f.Bay, f.Next = "shipped", "shipped", "Shipped."
	case f.Status == "Draft" || f.Status == "In review":
		f.Stage = "draft"
		if f.Status == "In review" || f.Panel != nil {
			f.Stage = "review"
		}
		switch {
		case f.Panel != nil && f.Panel.State == "running":
			f.Bay, f.Next = "running", fmt.Sprintf("Peer review round %d of %d: %d of %d lenses approve.", f.Panel.Round, f.Panel.MaxRounds, f.Panel.Status.Approved, f.Panel.Status.Total)
			add(inbox.Open("v", "Watch review", tab("review")))
		case f.Panel != nil && f.Panel.State == "cap reached":
			f.Bay, f.Next = "you", "Peer review hit its round cap. Decide: more rounds, or approve anyway."
			add(inbox.Post("r", "Run 2 more rounds", "/api/review/"+f.Panel.ID+"/rounds", "Added 2 rounds", map[string]any{"add": 2}).WithPrimary(),
				withLabel(approve, "Approve anyway"))
		case f.Panel != nil && f.Panel.State == "approved":
			f.Bay, f.Next = "you", "Every lens approves. Approve the PRD to file its epic."
			add(approve.WithPrimary())
		case f.Status == "In review":
			f.Bay, f.Next = "you", "In review. Approve it, or run a peer review first."
			add(approve.WithPrimary(), inbox.Open("v", "Start peer review", tab("review")))
		case f.Live > 0:
			f.Bay, f.Next = "running", "The PRD interview is running."
		default:
			f.Bay, f.Next = "go", "Draft. Run a peer review, or approve it as it is."
			add(inbox.Open("v", "Start peer review", tab("review")).WithPrimary(), withLabel(approve, "Approve without review"))
		}
	case f.Epic == nil:
		f.Stage, f.Bay, f.Next = "approved", "go", "Approved. Create the tasks: the epic and its issues."
		add(start("t", "Create tasks", "Started create-tasks", "create-tasks", docs, map[string]any{"product": docs, "args": f.Path}).WithPrimary())
	case f.Counts.Open == 0 && f.Counts.Done == 0:
		f.Stage, f.Bay, f.Next = "tasks", "go", "The epic has no issues yet."
		add(start("t", "Create tasks", "Started create-tasks", "create-tasks", docs, map[string]any{"product": docs, "args": f.Path}).WithPrimary())
	case f.Counts.Open == 0:
		f.Stage, f.Bay, f.Next = "shipped", "go", fmt.Sprintf("All %d issues are done. Close the epic.", f.Counts.Done)
		owner, name, _ := strings.Cut(f.Epic.Repo, "/")
		add(inbox.Post("c", "Close epic", fmt.Sprintf("/api/epics/%s/%s/%d/close", owner, name, f.Epic.N), "Epic closed", map[string]any{}).
			WithPrimary().WithConfirm(fmt.Sprintf("Close epic #%d and any open issues under it?", f.Epic.N)))
	case f.Counts.Unrefined > 0:
		f.Stage = "tasks"
		if f.Live > 0 {
			f.Bay, f.Next = "running", fmt.Sprintf("Refining: %d of %d issues still unrefined.", f.Counts.Unrefined, f.Counts.Open)
		} else {
			f.Bay, f.Next = "go", fmt.Sprintf("%d of %d issues need refining before they can run.", f.Counts.Unrefined, f.Counts.Open)
		}
		add(start("e", fmt.Sprintf("Refine %d", f.Counts.Unrefined), "Started refine-issues", "refine-issues", f.Epic.Repo,
			map[string]any{"issue": f.Epic.N, "args": strconv.Itoa(f.Epic.N)}).WithPrimary())
	default:
		f.Stage = "building"
		for _, i := range f.Issues {
			if i.State == "mergeable" {
				add(mergeAction(i.Repo, i.PR.N, i.PR.SHA))
			}
		}
		waiting := 0
		for _, i := range f.Issues {
			if i.State == "waiting" || i.State == "failed" || i.State == "conflict" || i.State == "ci_failed" {
				waiting++
			}
		}
		switch {
		case f.Counts.Mergeable > 0 || waiting > 0 || (f.Dispatch != nil && f.Dispatch.Needs > 0):
			f.Bay = "you"
			parts := []string{}
			if f.Counts.Mergeable > 0 {
				parts = append(parts, fmt.Sprintf("%d ready to merge", f.Counts.Mergeable))
			}
			if waiting > 0 {
				parts = append(parts, fmt.Sprintf("%d need you", waiting))
			}
			if f.Dispatch != nil && f.Dispatch.Needs > 0 {
				parts = append(parts, fmt.Sprintf("%d dispatch lanes need you", f.Dispatch.Needs))
			}
			f.Next = strings.Join(parts, " · ") + "."
		case f.Dispatch != nil || f.Live > 0:
			f.Bay = "running"
			f.Next = fmt.Sprintf("Building: %d open, %d done.", f.Counts.Open, f.Counts.Done)
		case f.Counts.Ready > 0:
			f.Bay = "go"
			f.Next = fmt.Sprintf("%d issues are ready. Run the epic as a dispatch.", f.Counts.Ready)
		default:
			f.Bay = "running"
			f.Next = fmt.Sprintf("%d open, %d in review, %d done.", f.Counts.Open, f.Counts.Review, f.Counts.Done)
		}
		if f.Dispatch != nil {
			add(inbox.Open("d", "Open dispatch", "#/dispatches"))
		} else if f.Counts.Ready > 0 {
			add(inbox.Open("d", "Run epic", "#/dispatches?new="+url.QueryEscape(f.Epic.Key)).WithPrimary())
		}
	}
	add(inbox.Open("r", "Read PRD", f.PRDRoute))
}

func withLabel(a inbox.Action, l string) inbox.Action { a.Label = l; a.Primary = false; return a }
