package views

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Changes is the old aiw Small changes view: open issues that belong to no epic, across every
// registered repo (or one), with the same states and row actions as a feature's issues.
type Changes struct {
	Stale   []string         `json:"stale"`
	Issues  []FeatureIssue   `json:"issues"`
	Pending []FeatureSession `json:"pending"` // small-change runs still filing their issue
}

// Changes builds the list; repo "" means every registered repo.
func (s *Service) Changes(ctx context.Context, repo string) Changes {
	out := Changes{Stale: []string{}, Issues: []FeatureIssue{}, Pending: []FeatureSession{}}
	if s.d.Snapshots == nil || s.d.Products == nil {
		return out
	}
	seen := map[string]bool{}
	var repos []string
	for _, r := range s.d.Products.Repos() {
		if strings.HasPrefix(r.Slug, "local/") || seen[lower(r.Slug)] || (repo != "" && !strings.EqualFold(r.Slug, repo)) {
			continue
		}
		seen[lower(r.Slug)] = true
		repos = append(repos, r.Slug)
	}
	sort.Strings(repos)
	var recs []sessions.Record
	if s.d.Sessions != nil {
		recs = s.d.Sessions.List(sessions.Filter{})
	}
	latest := latestByIssue(recs)
	for _, r := range repos {
		sn := s.d.Snapshots.Snapshot(r)
		if !sn.Fresh() {
			out.Stale = append(out.Stale, r)
		}
		epics := map[int]bool{}
		for _, is := range sn.Data.Issues {
			if hasLabel(is.Labels, "epic") {
				epics[is.N] = true
			}
		}
		prOf := map[string]poller.OpenPR{}
		for _, pr := range sn.Data.OpenPRs {
			if n := inbox.IssueOfPR(sn.Data, pr); n > 0 {
				k := fmt.Sprintf("%s#%d", lower(r), n)
				if _, dup := prOf[k]; !dup {
					prOf[k] = pr
				}
			}
		}
		for _, is := range sn.Data.Issues {
			if hasLabel(is.Labels, "epic") || is.Status == poller.StatusDone {
				continue
			}
			if is.Parent != nil && (!strings.EqualFold(is.Parent.Repo, r) || epics[is.Parent.N]) {
				continue // a child of an epic: it is on a feature
			}
			out.Issues = append(out.Issues, s.featureIssue(found{r, is}, prOf, latest))
		}
	}
	for _, rec := range recs {
		if rec.Step != "small-change" || !rec.Status.Live() {
			continue
		}
		pub := s.d.Sessions.Public(rec)
		if repo != "" && (pub.Repo == nil || !strings.EqualFold(*pub.Repo, repo)) {
			continue
		}
		out.Pending = append(out.Pending, FeatureSession{ID: pub.ID, Status: string(rec.Status), Skill: skillName(pub), Title: pub.Title, StartedAt: pub.StartedAt})
	}
	return out
}
