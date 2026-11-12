package release

import (
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/server"
)

// Public builds the API shape of a record, with the grind status and the server-built actions.
func (s *Service) Public(r record) Release {
	out := Release{ID: r.ID, Repo: r.Repo, Head: r.Head, Base: r.Base, Stage: r.Stage, DryRun: r.DryRun,
		PR: r.PR, PRURL: r.PRURL, Thread: r.Thread, CutSession: r.CutSess, NoteSession: r.NoteSess,
		NotePostedAt: r.PostedAt, NotePermalink: r.Permalink, MergedAt: r.MergedAt, Error: r.Error,
		DryRunDir: r.DryRunDir, CreatedAt: r.CreatedAt, UpdatedAt: r.UpdatedAt}
	if r.PR != nil && s.d.Grind != nil && (r.Stage == StGrind || r.Stage == StMerge) {
		if g, ok := s.d.Grind.Get(r.Repo, *r.PR); ok {
			out.Grind = &g
		}
	}
	if r.Stage == StNotify || r.Stage == StDone {
		if t, ok := s.readNote(r.ID); ok {
			out.Note = &t
		}
	}
	out.Actions = s.actions(r, out)
	return out
}

func repoActions(rr ReleaseRepo) []Action {
	if rr.Open != nil {
		return []Action{{Key: "o", Label: "Open release", Open: "#/releases/" + *rr.Open, Primary: true}}
	}
	return []Action{
		{Key: "c", Label: "Cut release", Method: http.MethodPost, Path: "/api/releases", Body: map[string]any{"repo": rr.Repo},
			Toast: "Release started for " + rr.Repo, Primary: true,
			Confirm: "Cut a " + rr.Head + " to " + rr.Base + " release PR for " + rr.Repo + "?"},
		{Key: "d", Label: "Dry run", Method: http.MethodPost, Path: "/api/releases", Body: map[string]any{"repo": rr.Repo, "dry_run": true},
			Toast: "Dry run started for " + rr.Repo},
		{Key: "p", Label: "Partial release", Method: http.MethodPost, Path: "/api/releases", Body: map[string]any{"repo": rr.Repo, "partial": true},
			Toast: "Partial release started for " + rr.Repo},
	}
}

func (s *Service) actions(r record, rel Release) []Action {
	base := "/api/releases/" + r.ID
	a := []Action{}
	session := func(key, label string, id *string) {
		if id != nil {
			a = append(a, Action{Key: key, Label: label, Open: "#/sessions/" + *id})
		}
	}
	skip := func(label string) Action {
		return Action{Key: "s", Label: label, Method: http.MethodPost, Path: base + "/skip", Toast: "Release skipped", Clears: true,
			Confirm: "Skip this release? The PR stays on GitHub."}
	}
	switch r.Stage {
	case StCut:
		session("o", "Open release-pr session", r.CutSess)
		a = append(a, skip("Skip"))
	case StGrind, StMerge:
		running := rel.Grind != nil && rel.Grind.State == "running"
		if !running {
			a = append(a, Action{Key: "g", Label: "Start grind", Method: http.MethodPost, Path: base + "/grind",
				Toast: "Grind started", Primary: r.Stage == StGrind})
		}
		if rel.Grind != nil {
			session("o", "Open grind session", rel.Grind.Session)
		}
		if r.PRURL != nil {
			a = append(a, Action{Key: "p", Label: "Open PR", Open: *r.PRURL, Primary: r.Stage == StMerge})
		}
		a = append(a, skip("Skip"))
	case StNotify:
		if r.PostAttemptedAt == "" {
			drafting := s.live(r.NoteSess)
			if rel.Note == nil || strings.TrimSpace(*rel.Note) == "" {
				if !drafting {
					a = append(a, Action{Key: "n", Label: "Write note", Method: http.MethodPost, Path: base + "/note",
						Toast: "Writing the release note", Primary: true})
				}
			} else {
				a = append(a, Action{Key: "p", Label: "Post to Slack", Method: http.MethodPost, Path: base + "/post",
					Toast: "Release note posted", Primary: !drafting, Clears: true,
					Confirm: "Post this note to " + s.channelLabel() + "? It pings @here and is sent once."},
					Action{Key: "e", Label: "Edit note", Open: "#/releases/" + r.ID + "/note"},
					Action{Key: "n", Label: "Redo draft", Method: http.MethodPost, Path: base + "/note", Toast: "Redrafting the release note",
						Confirm: "Replace the note with a new draft?"})
			}
			session("o", "Open note session", r.NoteSess)
			a = append(a, skip("Skip note"))
		}
	case StFailed:
		a = append(a, Action{Key: "r", Label: "Retry", Method: http.MethodPost, Path: "/api/releases",
			Body: map[string]any{"repo": r.Repo, "dry_run": r.DryRun}, Toast: "Release restarted"})
		session("o", "Open release-pr session", r.CutSess)
	case StDone:
		if r.Permalink != nil {
			a = append(a, Action{Key: "o", Label: "Open Slack message", Open: *r.Permalink})
		}
	case StDryRun:
		session("o", "Open release-pr session", r.CutSess)
	}
	return a
}

func (s *Service) channelLabel() string {
	n := s.d.Settings.Get().ReleaseNote
	if n.ChannelName != "" {
		return "#" + n.ChannelName
	}
	return "the release-note channel"
}

// ---- routes ----

type cutBody struct {
	Repo    string `json:"repo"`
	DryRun  bool   `json:"dry_run"`
	Partial bool   `json:"partial"`
	Head    string `json:"head"`
	Base    string `json:"base"`
}

type noteBody struct {
	Text string `json:"text"`
}

// Routes is API §5.6.
func Routes(s *Service) []server.Route {
	id := func(r *http.Request) string { return r.PathValue("id") }
	act := func(f func(r *http.Request, id string) (Release, error)) http.Handler {
		return server.Handle(func(r *http.Request) (int, any, error) {
			v, err := f(r, id(r))
			if err != nil {
				return 0, nil, err
			}
			return http.StatusOK, v, nil
		})
	}
	return []server.Route{
		{Pattern: "GET /api/releases", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			p := r.URL.Query().Get("product")
			return http.StatusOK, map[string]any{"repos": s.Repos(p), "releases": s.List(p)}, nil
		})},
		{Pattern: "GET /api/releases/{id}", Handler: act(func(r *http.Request, id string) (Release, error) { return s.Get(id) })},
		{Pattern: "POST /api/releases", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var b cutBody
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			v, err := s.CutWith(r.Context(), b.Repo, CutOpts{DryRun: b.DryRun, Partial: b.Partial, Head: b.Head, Base: b.Base})
			if err != nil {
				return 0, nil, err
			}
			return http.StatusCreated, v, nil
		})},
		{Pattern: "POST /api/releases/{id}/grind", Handler: act(func(r *http.Request, id string) (Release, error) { return s.Grind(r.Context(), id) })},
		{Pattern: "POST /api/releases/{id}/note", Handler: act(func(r *http.Request, id string) (Release, error) { return s.DraftNote(r.Context(), id) })},
		{Pattern: "PUT /api/releases/{id}/note", Handler: act(func(r *http.Request, id string) (Release, error) {
			var b noteBody
			if err := server.Decode(r, &b); err != nil {
				return Release{}, err
			}
			return s.SaveNote(id, b.Text)
		})},
		{Pattern: "POST /api/releases/{id}/post", Handler: act(func(r *http.Request, id string) (Release, error) { return s.Post(r.Context(), id) })},
		{Pattern: "POST /api/releases/{id}/skip", Handler: act(func(r *http.Request, id string) (Release, error) { return s.Skip(id) })},
	}
}
