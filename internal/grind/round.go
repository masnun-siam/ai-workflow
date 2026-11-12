package grind

import (
	"regexp"
	"sort"
	"strings"
)

// GHUser is a GitHub account as the REST API reports it; the whole object can be null.
type GHUser struct {
	Login string `json:"login"`
	Type  string `json:"type"`
}

// Review is one entry of pulls/{n}/reviews.
type Review struct {
	ID          int64   `json:"id"`
	User        *GHUser `json:"user"`
	State       string  `json:"state"`
	Body        string  `json:"body"`
	CommitID    string  `json:"commit_id"`
	SubmittedAt string  `json:"submitted_at"`
}

// Comment is one entry of pulls/{n}/comments (inline) or issues/{n}/comments.
type Comment struct {
	ID         int64   `json:"id"`
	User       *GHUser `json:"user"`
	Path       string  `json:"path"`
	Line       *int    `json:"line"`
	OrigLine   *int    `json:"original_line"`
	Body       string  `json:"body"`
	InReplyTo  *int64  `json:"in_reply_to_id"`
	ReviewID   *int64  `json:"pull_request_review_id"`
	CreatedAt  string  `json:"created_at"`
	CommitHash string  `json:"commit_id"`
}

// RoundInput is everything one evaluation reads.
type RoundInput struct {
	Last     string // last-seen: only newer things count
	Head     string // current head SHA
	Author   string // PR author login
	Set      []string
	Known    []string // known_bots
	Unlogged []string // slack ids still waiting for a login
	Learned  []string // `id=login` pairings made so far
	Seen     []string // fingerprints recorded in earlier rounds
	Reviews  []Review
	Comments []Comment
	Issue    []Comment
}

// ReviewOut is one selected review of a round.
type ReviewOut struct {
	ID          int64  `json:"id"`
	Reviewer    string `json:"reviewer"`
	State       string `json:"state"`
	SubmittedAt string `json:"submitted_at"`
	Blocker     int    `json:"blocker"`
	ShouldFix   int    `json:"should_fix"`
	Comments    int    `json:"comments"`
}

// Finding is one inline comment of a selected review.
type Finding struct {
	ID       int64  `json:"id"`
	FP       string `json:"fp"`
	Path     string `json:"path"`
	Line     *int   `json:"line"`
	Body     string `json:"body"`
	Author   string `json:"author"`
	ReviewID int64  `json:"review_id"`
	New      bool   `json:"new"`
	Seen     int    `json:"seen"`
}

// Pairing is one login learned for a Slack id.
type Pairing struct{ SlackID, Login string }

// RoundResult is the evaluation of the current review state.
type RoundResult struct {
	Landed      bool
	SubmittedAt string
	Reviews     []ReviewOut
	Blocker     int
	ShouldFix   int
	Approved    bool
	Clean       bool
	Findings    []Finding
	ThirdParty  []string
	Learned     []Pairing // pairings to record
	LearnedAny  []string  // logins learned with no Slack id to pair (legacy: no reviewer known yet)
}

var (
	blockerRE   = regexp.MustCompile(`(?i)([0-9]+) blocker`)
	shouldFixRE = regexp.MustCompile(`(?i)([0-9]+) should-fix`)
	spaceRE     = regexp.MustCompile(`\s+`)
)

func lc(s string) string { return strings.ToLower(s) }

func count(re *regexp.Regexp, body string) int {
	if m := re.FindStringSubmatch(body); m != nil {
		return atoi(m[1])
	}
	return 0
}

func login(u *GHUser) string {
	if u == nil {
		return ""
	}
	return u.Login
}

// inSet matches a login against the reviewer set, ignoring case; `copilot` also matches
// copilot-pull-request-reviewer[bot].
func inSet(set []string, l string) bool {
	l = lc(l)
	for _, s := range set {
		s = lc(s)
		if s == l || (s == "copilot" && strings.HasPrefix(l, "copilot-pull-request-reviewer")) {
			return true
		}
	}
	return false
}

func (in RoundInput) isBot(u *GHUser) bool {
	if u == nil {
		return false
	}
	l := lc(u.Login)
	if u.Type == "Bot" || strings.HasSuffix(l, "[bot]") {
		return true
	}
	for _, k := range in.Known {
		if lc(k) == l {
			return true
		}
	}
	return false
}

// fingerprint is `path:line` plus the first 80 normalised characters of the body.
func fingerprint(c Comment) string {
	line := "null"
	switch {
	case c.Line != nil:
		line = itoa(*c.Line)
	case c.OrigLine != nil:
		line = itoa(*c.OrigLine)
	}
	body := strings.TrimPrefix(spaceRE.ReplaceAllString(lc(c.Body), " "), " ")
	if r := []rune(body); len(r) > 80 {
		body = string(r[:80])
	}
	return c.Path + ":" + line + " " + body
}

// Evaluate ports round.jq: per reviewer the newest review on the current head (one that carries
// comments beats a comment-less one), findings = their top-level inline comments, approval and
// clean-bot detection, third-party commenters, and reviewer learning.
func Evaluate(in RoundInput) RoundResult {
	var res RoundResult
	au := lc(in.Author)
	set := append([]string(nil), in.Set...)

	// Learning: Slack ids that still have no login learn the first human reviewer; with no reviewer
	// known at all, the first human reviewer is added to the set.
	resolved := map[string]bool{}
	for _, p := range in.Learned {
		id, _, _ := strings.Cut(p, "=")
		resolved[id] = true
	}
	var open []string
	for _, id := range in.Unlogged {
		if !resolved[id] {
			open = append(open, id)
		}
	}
	if len(open) > 0 || len(set) == 0 {
		cands := []Review{}
		for _, r := range in.Reviews {
			if r.SubmittedAt > in.Last && lc(login(r.User)) != au && r.User != nil && !in.isBot(r.User) && !inSet(set, r.User.Login) {
				cands = append(cands, r)
			}
		}
		sort.SliceStable(cands, func(i, j int) bool { return cands[i].SubmittedAt < cands[j].SubmittedAt })
		seen := map[string]bool{}
		for _, r := range cands {
			l := lc(r.User.Login)
			if seen[l] {
				continue
			}
			seen[l] = true
			if len(open) > 0 {
				res.Learned = append(res.Learned, Pairing{open[0], r.User.Login})
				open = open[1:]
			} else if len(set) == 0 && len(res.LearnedAny) == 0 {
				res.LearnedAny = append(res.LearnedAny, r.User.Login)
			} else {
				break
			}
			set = append(set, r.User.Login)
		}
	}

	ncom := map[int64]int{}
	for _, c := range in.Comments {
		if c.InReplyTo == nil && c.ReviewID != nil {
			ncom[*c.ReviewID]++
		}
	}
	type cand struct {
		r         Review
		n         int
		bot       bool
		blocker   int
		shouldFix int
	}
	best := map[string]cand{}
	for _, r := range in.Reviews {
		l := lc(login(r.User))
		if !(r.SubmittedAt > in.Last && r.CommitID == in.Head && r.State != "PENDING") || l == au {
			continue
		}
		bot := in.isBot(r.User)
		if !bot && !inSet(set, l) {
			continue
		}
		c := cand{r: r, n: ncom[r.ID], bot: bot, blocker: count(blockerRE, r.Body), shouldFix: count(shouldFixRE, r.Body)}
		if !(c.n > 0 || r.State == "APPROVED" || r.State == "CHANGES_REQUESTED" || bot) {
			continue
		}
		old, ok := best[l]
		rank := func(x cand) int {
			if x.n > 0 {
				return 1
			}
			return 0
		}
		if !ok || rank(c) > rank(old) || (rank(c) == rank(old) && c.r.SubmittedAt >= old.r.SubmittedAt) {
			best[l] = c
		}
	}
	sel := make([]cand, 0, len(best))
	for _, c := range best {
		sel = append(sel, c)
	}
	sort.Slice(sel, func(i, j int) bool {
		if sel[i].r.SubmittedAt != sel[j].r.SubmittedAt {
			return sel[i].r.SubmittedAt < sel[j].r.SubmittedAt
		}
		return sel[i].r.ID < sel[j].r.ID
	})
	ids := map[int64]bool{}
	for _, c := range sel {
		ids[c.r.ID] = true
		res.Reviews = append(res.Reviews, ReviewOut{ID: c.r.ID, Reviewer: login(c.r.User), State: c.r.State,
			SubmittedAt: c.r.SubmittedAt, Blocker: c.blocker, ShouldFix: c.shouldFix, Comments: c.n})
		res.Blocker += c.blocker
		res.ShouldFix += c.shouldFix
		if c.r.State == "APPROVED" {
			res.Approved = true
		}
		if c.bot && c.n == 0 && c.r.State != "CHANGES_REQUESTED" && c.blocker == 0 && c.shouldFix == 0 {
			res.Clean = true
		}
		if c.r.SubmittedAt > res.SubmittedAt {
			res.SubmittedAt = c.r.SubmittedAt
		}
	}
	res.Landed = len(sel) > 0
	seenCount := map[string]int{}
	for _, s := range in.Seen {
		seenCount[s]++
	}
	for _, c := range in.Comments {
		if c.InReplyTo != nil || c.ReviewID == nil || !ids[*c.ReviewID] {
			continue
		}
		fp := fingerprint(c)
		line := c.Line
		if line == nil {
			line = c.OrigLine
		}
		res.Findings = append(res.Findings, Finding{ID: c.ID, FP: fp, Path: c.Path, Line: line, Body: c.Body,
			Author: login(c.User), ReviewID: *c.ReviewID, Seen: seenCount[fp], New: seenCount[fp] == 0})
	}

	// third-party humans: anyone not the author, not a bot and not in the set, since the last round
	tp := map[string]bool{}
	note := func(u *GHUser, t string) {
		if t > in.Last && u != nil && lc(u.Login) != au && !in.isBot(u) && !inSet(set, u.Login) {
			tp[u.Login] = true
		}
	}
	for _, r := range in.Reviews {
		note(r.User, r.SubmittedAt)
	}
	for _, c := range in.Comments {
		note(c.User, c.CreatedAt)
	}
	for _, c := range in.Issue {
		note(c.User, c.CreatedAt)
	}
	for l := range tp {
		res.ThirdParty = append(res.ThirdParty, l)
	}
	sort.Strings(res.ThirdParty)
	return res
}
