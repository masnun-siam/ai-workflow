package views

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
)

// OpsTarget is one repo an ops step can run on.
type OpsTarget struct {
	Repo string        `json:"repo"`
	Last *SessionBrief `json:"last"`
	Note string        `json:"note"`
}

// OpsRow is one maintenance step (API §4).
type OpsRow struct {
	Step    string         `json:"step"`
	Label   string         `json:"label"`
	Scope   string         `json:"scope"` // each repo | docs repo | any repo
	Summary string         `json:"summary"`
	Targets []OpsTarget    `json:"targets"`
	Actions []inbox.Action `json:"actions"`
}

// Ops is GET /api/ops.
type Ops struct {
	Product string   `json:"product"`
	Rows    []OpsRow `json:"rows"`
}

func scopeOf(st prompts.Step) string {
	switch {
	case st.RunsIn == prompts.InDocs:
		return "docs repo"
	case st.ID == "skill-feedback":
		return "any repo"
	}
	return "each repo"
}

func dayMonth(t time.Time) string { return t.Format("2 Jan") }

// Ops builds one row per step of the ops stage (API §9.1).
func (s *Service) Ops(ctx context.Context, product string) Ops {
	p, ok := s.Product(product)
	out := Ops{Product: product, Rows: []OpsRow{}}
	if !ok || s.d.Prompts == nil {
		return out
	}
	out.Product = p.DocsRepo
	repos := inbox.ProductRepos(p)
	cloned := map[string]bool{lower(p.DocsRepo): true}
	for _, r := range p.Repos {
		cloned[lower(r.Repo)] = r.Cloned
	}
	for _, st := range s.d.Prompts.Steps() {
		if !st.InStage("ops") {
			continue
		}
		scope := scopeOf(st)
		row := OpsRow{Step: st.ID, Label: st.Label, Scope: scope, Targets: []OpsTarget{}, Actions: []inbox.Action{}}
		targets := repos
		if scope != "each repo" {
			targets = []string{p.DocsRepo}
		}
		// the newest run per repo
		last := map[string]sessions.Session{}
		if s.d.Sessions != nil {
			for _, rec := range s.d.Sessions.List(sessions.Filter{Step: st.ID}) {
				ss := s.d.Sessions.Public(rec)
				if ss.Repo == nil {
					continue
				}
				if cur, ok := last[lower(*ss.Repo)]; !ok || ss.StartedAt > cur.StartedAt {
					last[lower(*ss.Repo)] = ss
				}
			}
		}
		ran := 0
		var next string
		var nextAt string
		for _, repo := range targets {
			t := OpsTarget{Repo: repo, Note: "never run"}
			if ss, ok := last[lower(repo)]; ok {
				t.Last = brief(ss)
				t.Note = string(ss.Status)
				if tm, ok := parseTime(ss.StartedAt); ok {
					t.Note += " " + dayMonth(tm.In(s.now().Location()))
				}
				if ss.Cost != nil {
					t.Note += fmt.Sprintf(" · $%.2f", *ss.Cost)
				}
				if ss.Status == sessions.StDone {
					ran++
				}
			}
			if !cloned[lower(repo)] {
				t.Note = "not cloned"
			} else if next == "" || (t.Last == nil && nextAt != "") || (t.Last != nil && nextAt != "" && t.Last.StartedAt < nextAt) {
				// never-run repos win; among run repos the oldest run
				next, nextAt = repo, ""
				if t.Last != nil {
					nextAt = t.Last.StartedAt
				}
			}
			row.Targets = append(row.Targets, t)
		}
		switch {
		case len(targets) > 1:
			row.Summary = fmt.Sprintf("%d/%d repos ran", ran, len(targets))
		case len(row.Targets) == 1 && row.Targets[0].Last != nil:
			row.Summary = "last run: " + row.Targets[0].Note
		default:
			row.Summary = "never run"
		}
		body := func(repo string) map[string]any {
			b := map[string]any{"step": st.ID, "repo": repo}
			if scope != "each repo" {
				b["product"] = p.DocsRepo
			}
			return b
		}
		if next == "" && len(targets) > 0 {
			next = targets[0]
		}
		if next != "" {
			row.Actions = append(row.Actions, inbox.Start("r", "Run", "Started "+st.ID, body(next)).WithPrimary())
		}
		if len(targets) > 1 {
			for i, repo := range targets {
				if i >= 9 {
					break
				}
				row.Actions = append(row.Actions, inbox.Start(strconv.Itoa(i+1), "Run on "+repoName(repo), "Started "+st.ID+" on "+repoName(repo), body(repo)))
			}
		}
		out.Rows = append(out.Rows, row)
	}
	return out
}
