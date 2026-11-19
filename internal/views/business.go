package views

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

// BusinessAPI is satisfied by *products.Registry.
type BusinessAPI interface {
	BusinessDocs(product string) ([]products.BusinessDoc, error)
	BusinessGate(product string) products.BusinessGate
}

// ValidationEpic is an open "Business validation: <Module>" epic of the docs repo (labels epic and
// business-validation) with its open children. It is never a Feature row.
type ValidationEpic struct {
	Repo    string         `json:"repo"`
	N       int            `json:"n"`
	Title   string         `json:"title"`
	Module  string         `json:"module"`
	URL     string         `json:"url"`
	Issues  []FeatureIssue `json:"issues"`
	Actions []inbox.Action `json:"actions"`
}

// BusinessView is GET /api/products/{owner}/{name}/business.
type BusinessView struct {
	Docs  []products.BusinessDoc `json:"docs"`
	Gate  products.BusinessGate  `json:"gate"`
	Epics []ValidationEpic       `json:"epics"`
}

const validationPrefix = "business validation:"

// businessDocs lists a product's business docs; nil Deps.Business or an error gives none.
func (s *Service) businessDocs(product string) []products.BusinessDoc {
	if s.d.Business == nil {
		return []products.BusinessDoc{}
	}
	docs, err := s.d.Business.BusinessDocs(product)
	if err != nil || docs == nil {
		return []products.BusinessDoc{}
	}
	return docs
}

// matchBusiness is a feature's business docs in FR-9 order: the doc with the PRD's module and file
// name first, then every other doc whose planned bullets link the PRD, by path.
func matchBusiness(prdPath string, docs []products.BusinessDoc) []string {
	out := []string{}
	same := "docs/business/" + strings.TrimPrefix(prdPath, "docs/prds/")
	var linked []string
	for _, d := range docs {
		if d.Path == same {
			out = append(out, d.Path)
			continue
		}
		for _, p := range d.PRDs {
			if p == prdPath {
				linked = append(linked, d.Path)
				break
			}
		}
	}
	sort.Strings(linked)
	return append(out, linked...)
}

// validationModule is the module of a "Business validation: <Module>" title, lowercased ("other"
// when the title names none).
func validationModule(title string) string {
	t := strings.TrimSpace(title)
	if len(t) < len(validationPrefix) || !strings.EqualFold(t[:len(validationPrefix)], validationPrefix) {
		return "other"
	}
	if m := strings.ToLower(strings.TrimSpace(t[len(validationPrefix):])); m != "" {
		return m
	}
	return "other"
}

// Business builds the Docs page data of one product: its business docs, the cached gate and the
// open business validation epics of its docs repo.
func (s *Service) Business(ctx context.Context, product string) (BusinessView, error) {
	p, ok := s.Product(product)
	if !ok || product == "" {
		return BusinessView{}, errs.NotFound("%s is not a registered product", product)
	}
	out := BusinessView{Docs: s.businessDocs(p.DocsRepo), Epics: []ValidationEpic{}}
	if s.d.Business != nil {
		out.Gate = s.d.Business.BusinessGate(p.DocsRepo)
	} else {
		r := "not checked yet"
		out.Gate = products.BusinessGate{State: "unavailable", Reason: &r}
	}
	if out.Gate.Failures == nil {
		out.Gate.Failures = []string{}
	}
	if s.d.Snapshots == nil {
		return out, nil
	}
	repos := inbox.ProductRepos(p)
	snaps, all, index := s.productIssues(repos)
	prOf := openPRs(repos, snaps)
	var recs []sessions.Record
	if s.d.Sessions != nil {
		recs = s.d.Sessions.List(sessions.Filter{})
	}
	latest := latestByIssue(recs)
	var dispatches []inbox.Dispatch
	if s.d.Dispatch != nil {
		dispatches = s.d.Dispatch.List()
	}
	for _, k := range all {
		is := k.issue
		if !strings.EqualFold(k.repo, p.DocsRepo) || strings.EqualFold(is.State, "CLOSED") ||
			!hasLabel(is.Labels, "epic") || !hasLabel(is.Labels, "business-validation") {
			continue
		}
		key := fmt.Sprintf("%s#%d", k.repo, is.N)
		e := ValidationEpic{Repo: k.repo, N: is.N, Title: is.Title, Module: validationModule(is.Title), URL: inbox.IssueURL(k.repo, is.N),
			Issues: []FeatureIssue{}, Actions: []inbox.Action{}}
		keys := map[string]bool{lower(key): true}
		ready := 0
		for _, kid := range epicChildren(k.repo, is, all, index) {
			fi := s.featureIssue(kid, prOf, latest)
			keys[lower(fi.Key)] = true
			if fi.State == "ready" {
				ready++
			}
			e.Issues = append(e.Issues, fi)
		}
		_, dispatched := epicDispatch(dispatches, key, keys)
		e.Actions = append(e.Actions, epicRunActions(key, dispatched, ready)...)
		out.Epics = append(out.Epics, e)
	}
	sort.Slice(out.Epics, func(i, j int) bool {
		if out.Epics[i].Module != out.Epics[j].Module {
			return out.Epics[i].Module < out.Epics[j].Module
		}
		return out.Epics[i].N < out.Epics[j].N
	})
	return out, nil
}
