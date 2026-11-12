package gh

import (
	"context"
	"net/http"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps are the routes' collaborators. The poller imports gh, so it is reached through functions.
type Deps struct {
	Client Client
	// Repoll runs a full poll of a repo after a GitHub write. Optional.
	Repoll func(ctx context.Context, slug string)
	// OpenChildren lists the open child issues (same repo) of an epic from the poller snapshot.
	OpenChildren func(slug string, epic int) []int
}

func issueID(r *http.Request) (slug string, n int, err error) {
	slug, err = server.Slug(r)
	if err != nil || !ValidIssueID(r.PathValue("owner"), r.PathValue("name"), r.PathValue("n")) {
		return "", 0, errs.Invalid("bad issue id")
	}
	n, err = server.PathInt(r, "n")
	if err != nil {
		return "", 0, errs.Invalid("bad issue id")
	}
	return slug, n, nil
}

// Routes: popups, picker, branches, comment, state, merge and epic close (API §5.3).
func Routes(d Deps) []server.Route {
	c := d.Client
	repoll := func(r *http.Request, slug string) {
		if d.Repoll != nil {
			d.Repoll(r.Context(), slug)
		}
	}
	h := server.Handle
	return []server.Route{
		{Pattern: "GET /api/repos/{owner}/{name}/open", Handler: h(func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, err
			}
			items, err := OpenItems(r.Context(), c, slug, r.URL.Query().Get("kind"))
			if err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"items": items}, nil
		})},
		{Pattern: "GET /api/repos/{owner}/{name}/branches", Handler: h(func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, err
			}
			b, err := Branches(r.Context(), c, slug)
			return 0, b, err
		})},
		{Pattern: "GET /api/issues/{owner}/{name}/{n}", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			v, err := IssuePopup(r.Context(), c, slug, n)
			return 0, v, err
		})},
		{Pattern: "GET /api/pulls/{owner}/{name}/{n}", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			v, err := PRPopup(r.Context(), c, slug, n)
			return 0, v, err
		})},
		{Pattern: "POST /api/issues/{owner}/{name}/{n}/comment", Handler: h(commentHandler(c))},
		{Pattern: "POST /api/pulls/{owner}/{name}/{n}/comment", Handler: h(commentHandler(c))},
		{Pattern: "POST /api/issues/{owner}/{name}/{n}/state", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			var body struct {
				State  string `json:"state"`
				Reason string `json:"reason"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if err := SetIssueState(r.Context(), c, slug, n, body.State, body.Reason); err != nil {
				return 0, nil, err
			}
			repoll(r, slug)
			return 0, map[string]any{"ok": true, "state": body.State}, nil
		})},
		{Pattern: "POST /api/pulls/{owner}/{name}/{n}/state", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			var body struct {
				State string `json:"state"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if err := SetPRState(r.Context(), c, slug, n, body.State); err != nil {
				return 0, nil, err
			}
			repoll(r, slug)
			return 0, map[string]any{"ok": true, "state": body.State}, nil
		})},
		{Pattern: "POST /api/pulls/{owner}/{name}/{n}/merge", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			var body struct {
				SHA string `json:"sha"`
			}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			if err := MergePR(r.Context(), c, slug, n, body.SHA); err != nil {
				return 0, nil, err
			}
			repoll(r, slug)
			return 0, map[string]any{"ok": true}, nil
		})},
		{Pattern: "POST /api/epics/{owner}/{name}/{n}/close", Handler: h(func(r *http.Request) (int, any, error) {
			slug, n, err := issueID(r)
			if err != nil {
				return 0, nil, err
			}
			var body struct{}
			if err := server.Decode(r, &body); err != nil {
				return 0, nil, err
			}
			var kids []int
			if d.OpenChildren != nil {
				kids = d.OpenChildren(slug, n)
			}
			closed, err := CloseEpic(r.Context(), c, slug, n, kids)
			repoll(r, slug)
			if err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"ok": true, "closed": closed}, nil
		})},
	}
}

func commentHandler(c Client) server.HandlerFunc {
	return func(r *http.Request) (int, any, error) {
		slug, n, err := issueID(r)
		if err != nil {
			return 0, nil, err
		}
		var body struct {
			Text string `json:"text"`
		}
		if err := server.Decode(r, &body); err != nil {
			return 0, nil, err
		}
		url, err := Comment(r.Context(), c, slug, n, body.Text)
		if err != nil {
			return 0, nil, err
		}
		return 0, map[string]any{"ok": true, "url": url}, nil
	}
}
