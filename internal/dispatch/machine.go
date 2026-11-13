// Package dispatch runs an epic's open child issues (or 1..30 hand-picked issues) as lanes in
// dependency order up to a cap. Each lane is a headless session driving implement-issue ->
// pr-grind -> merge -> after-merge (W§2). machine.go is the pure part: the lane step function,
// scheduling, strand detection, the plan preview and the user's lane actions.
package dispatch

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
)

// Constants of the lane machine (W§2.3).
const (
	NoneGraceSeconds         = 300
	MergeRetrySeconds        = 300
	IdleGraceSeconds         = 180
	LimitBufferSeconds       = 60
	MergeFailsBeforeNeedsYou = 3
	Continue                 = "Continue from where you were stopped."
	Stalled                  = "stopped before a PR"
)

// Msg is a prompt for a lane session. A skill message (Step set) is rendered by the prompt
// registry; Suffix is appended to its text; a plain message has only Plain.
type Msg struct {
	Step, Args, Suffix string
	Plain              string
}

// PRFact is a lane PR as the merge gate sees it.
type PRFact struct {
	N                int
	URL              string
	Draft            bool
	State            string // OPEN | MERGED | CLOSED
	CI               string // success | failure | pending | none
	Conflict         bool
	Approved         bool
	ChangesRequested bool
	ThreadsOpen      int
	SHA              string
}

// GrindFact is the pr-grind state of the lane's PR.
type GrindFact struct {
	State  string // idle | paused | done
	Reason string
	Due    string
}

// Facts are built per tick from the poller snapshot, the grind state files and the session.
type Facts struct {
	IssueOpen    bool
	Refined      bool
	BlockersOpen []string
	PR           *PRFact
	Grind        *GrindFact
	Slack        bool // the grind resolver gave a path and no skip
	Channel      string
	Solo         bool   // the repo is the gh user's own: no approval needed
	Agent        string // working | idle | blocked | gone | unknown | ""
	LimitedUntil float64
	IdleGuard    bool // the idle_guard setting: an idle implementing lane is stalled, not needs-you
}

// Action kinds returned by Step.
const (
	ASend     = "send"
	AMerge    = "merge"
	AClose    = "close"
	AContinue = "continue"
	ANotify   = "notify"
)

// Action is something the tick does after Step.
type Action struct {
	Kind   string
	Msg    Msg    // send
	PR     int    // merge
	SHA    string // merge
	NKind  string // notify: event kind
	NText  string // notify: text
	Reason string
}

// ---- prompts (W§2.4) ----

const (
	laneGrind   = " -- dispatch lane: re-arm the headless way (write next-poll, end the turn; no Monitor, no ScheduleWakeup)"
	skipCIReply = "Skip CI for now, complete the grind, then come back and fix the CI"
)

// SkillCmd is the slash command of a registry step, for prompts that name another skill.
func SkillCmd(step string) string {
	switch step {
	case "implement-issue", "after-merge":
		return "/blubird:implement-issue"
	case "small-change":
		return "/blubird:create-tasks"
	case "pr-grind":
		return "/pr-grind"
	}
	return "/blubird:" + step
}

func implementMsg(n int, base string, pr int, ci string) Msg {
	var notes []string
	if pr > 0 {
		notes = append(notes, fmt.Sprintf("PR #%d is already open for it: continue that PR on its branch, don't start over", pr))
	}
	if base != "" {
		notes = append(notes, "base branch "+base+": branch from it, open the PR into it")
	}
	if ci != "wait" {
		notes = append(notes, "CI mode "+ci+": mark the PR ready after local checks and review pass; do not wait for CI")
	}
	args := strconv.Itoa(n)
	if len(notes) > 0 {
		args += " (" + strings.Join(notes, "; ") + ")"
	}
	return Msg{Step: "implement-issue", Args: args}
}

var reChannel = regexp.MustCompile(`^[A-Za-z0-9_]+$`)
var reReviewer = regexp.MustCompile(`^[A-Za-z0-9-]{1,39}$`)

// grindArgs is ` --channel <id>` when the repo has a Slack channel, else ` --reviewer <login>`.
func grindArgs(channel, reviewer string) string {
	ch, rv := strings.TrimSpace(channel), strings.TrimSpace(reviewer)
	if ch != "" && reChannel.MatchString(ch) {
		return " --channel " + ch
	}
	if ch == "" && reReviewer.MatchString(rv) {
		return " --reviewer " + rv
	}
	return ""
}

func grindMsg(prURL, channel string, lane bool, ci, reviewer string) Msg {
	m := Msg{Step: "pr-grind", Args: prURL + grindArgs(channel, reviewer)}
	if lane {
		m.Suffix = laneGrind
		if ci != "wait" {
			m.Suffix += " " + skipCIReply
		}
	}
	return m
}

func qaMsg(epic, branch string) Msg {
	on := ""
	if branch != "" {
		on = " on branch " + branch
	}
	return Msg{Plain: "Final QA for epic " + epic + on + ": run " + SkillCmd("verifier-locally") +
		" against every child issue's acceptance criteria, then test the whole feature end to end in the running app " +
		"with the browser tool. File each bug you find with " + SkillCmd("small-change") +
		" as a child issue of the epic."}
}

func conflictMsg(pr int, base string) Msg {
	b := base
	if b == "" {
		b = "<base>"
	}
	w := base
	if w == "" {
		w = "its base"
	}
	return Msg{Plain: fmt.Sprintf("PR #%d conflicts with %s. Merge origin/%s into the branch, resolve the "+
		"conflicts, re-run the checks, push and wait for CI to be green. Don't mark anything else or merge.", pr, w, b)}
}

func ciFixMsg(pr int) Msg {
	return Msg{Plain: fmt.Sprintf("CI is red on PR #%d. Read the failing job's log, fix it locally, re-run the checks, push and wait for green.", pr)}
}

func followupsMsg(n, pr int) Msg {
	return Msg{Step: "after-merge", Args: fmt.Sprintf("%d (PR #%d for issue #%d is merged: run the 'After the pull request is merged' section, not the implement steps)", n, pr, n)}
}

// LaneBase is the base a lane branches from and opens its PR into.
func LaneBase(l *store.Lane, s store.Settings) string {
	if b := store.Str(s.FeatureBranch); b != "" {
		return b
	}
	if b := store.Str(s.BaseBranch); b != "" {
		return b
	}
	return l.Base
}

// stageMsg is what a fresh session for the lane's current stage is told; ok false when the stage
// needs no session.
func stageMsg(l *store.Lane, s store.Settings, prURL string) (Msg, bool) {
	base := LaneBase(l, s)
	switch l.Stage {
	case store.StImplementing:
		return implementMsg(l.N, base, l.PR, s.CI), true
	case store.StGrinding:
		return grindMsg(prURL, l.Channel, true, s.CI, l.Reviewer), true
	case store.StConflictFix:
		return conflictMsg(l.PR, base), true
	case store.StFollowups:
		return followupsMsg(l.N, l.PR), true
	}
	return Msg{}, false
}

// ---- the lane machine (W§2.3) ----

func grindOn(s store.Settings, f Facts) bool { return s.Grind != "off" && f.Slack }

func mergeBlockers(pr PRFact, solo bool) string {
	switch {
	case pr.Draft:
		return "PR is a draft"
	case pr.Conflict:
		return "PR has a merge conflict"
	case pr.ChangesRequested:
		return "changes requested"
	case pr.ThreadsOpen > 0:
		return "unresolved review threads"
	case !pr.Approved && !solo:
		return "no approving review"
	}
	return ""
}

func noneSince(l store.Lane, pr PRFact, now float64) float64 {
	if l.NoneSHA == pr.SHA && l.NoneSince != 0 {
		return l.NoneSince
	}
	return now
}

// gate is "" when the PR may merge, else why not.
func gate(l store.Lane, f Facts, s store.Settings, now float64) string {
	var pr PRFact
	if f.PR != nil {
		pr = *f.PR
	}
	var g GrindFact
	if f.Grind != nil {
		g = *f.Grind
	}
	switch {
	case (s.CI == "wait" || s.CI == "defer") && pr.CI == "none":
		// checks may not be registered yet; after the grace a repo with no CI merges in either mode
		if now-noneSince(l, pr, now) < NoneGraceSeconds {
			return "CI not registered yet"
		}
	case s.CI == "wait" && pr.CI != "success":
		return "CI is not green"
	case s.CI == "defer" && pr.CI != "success":
		return "waiting for green CI (defer)"
	}
	if why := mergeBlockers(pr, f.Solo || s.SkipApproval); why != "" {
		return why
	}
	if grindOn(s, f) && !(g.State == "done" && strings.Contains(g.Reason, "approved")) {
		return "grind is not done"
	}
	return ""
}

// Step is pure: the lane after this tick and the actions to run. A lane in a non-active stage or
// paused yields itself unchanged.
func Step(lane store.Lane, f Facts, s store.Settings, now float64) (store.Lane, []Action) {
	o := lane
	l := lane
	if !store.Active(o.Stage) || o.Paused {
		return l, nil
	}
	var pr PRFact
	if f.PR != nil {
		pr = *f.PR
	}
	agent := f.Agent
	idleOrNone := agent == "idle" || agent == ""
	base := LaneBase(&o, s)
	free := s.CI != "wait" // defer / ignore: a lane does not wait for CI before the gate
	var acts []Action

	to := func(stage, why string) {
		l.Stage, l.NeedsYou, l.Stalled, l.Held, l.IdleSince, l.MergeError, l.MergeFails = stage, "", "", "", 0, "", 0
		if why != "" {
			acts = append(acts, Action{Kind: ANotify, NKind: stage, NText: why})
		}
	}
	notify := func(kind, text string) { acts = append(acts, Action{Kind: ANotify, NKind: kind, NText: text}) }
	send := func(m Msg) { acts = append(acts, Action{Kind: ASend, Msg: m}) }

	// Claude usage limit: wait, then nudge once the reset has passed
	if lim := f.LimitedUntil; lim > now {
		if o.LimitedUntil != lim {
			l.LimitedUntil = lim
		}
		return l, nil
	}
	if o.LimitedUntil != 0 {
		l.LimitedUntil = 0
		if now >= o.LimitedUntil+LimitBufferSeconds {
			acts = append(acts, Action{Kind: AContinue})
		}
		return l, acts
	}

	if o.Stage != store.StFollowups && pr.State == "MERGED" { // merged here, or by a human at any stage
		to(store.StFollowups, "")
		l.PR = pr.N
		send(followupsMsg(o.N, pr.N))
		return l, acts
	}

	if agent == "gone" && (o.Stage == store.StImplementing || o.Stage == store.StGrinding ||
		o.Stage == store.StConflictFix || o.Stage == store.StFollowups) &&
		!(o.Stage == store.StFollowups && !f.IssueOpen) {
		l.Stalled = "" // a gone session is a real needs-you
		if o.NeedsYou != "the lane session is gone" {
			l.NeedsYou = "the lane session is gone"
			notify("needs_you", "the lane session is gone: retry it")
		}
		return l, acts
	}

	switch o.Stage {
	case store.StImplementing:
		ready := pr.State == "OPEN" && !pr.Draft
		if pr.State == "OPEN" && pr.N != o.PR {
			l.PR = pr.N // tracked as soon as it exists: a retry continues it instead of starting over
		}
		if !free && ready && pr.CI == "failure" && idleOrNone {
			if o.Held != "CI is red" {
				l.Held, l.NeedsYou, l.Stalled, l.IdleSince = "CI is red", "", "", 0
				notify("held", fmt.Sprintf("CI is red on PR #%d", pr.N))
			}
			return l, acts
		}
		if o.Held != "" { // CI re-ran, or the session is back on it
			l.Held = ""
		}
		if ready && (free || pr.CI == "success") {
			if grindOn(s, f) {
				to(store.StGrinding, "")
				send(grindMsg(pr.URL, f.Channel, true, s.CI, ""))
			} else {
				to(store.StMergeGate, "")
			}
			return l, acts
		}
		if f.IdleGuard {
			return stalls(o, l, agent, acts, now)
		}
		return waits(o, l, agent, acts, "stopped without a ready PR", now)

	case store.StGrinding:
		var g GrindFact
		if f.Grind != nil {
			g = *f.Grind
		}
		reason := g.Reason
		if reason == "" {
			reason = "?"
		}
		switch {
		case !grindOn(s, f): // switched off mid-run
			to(store.StMergeGate, "")
		case f.Grind != nil && g.State == "done":
			if strings.Contains(g.Reason, "approved") {
				to(store.StMergeGate, "")
			} else if why := "grind ended: " + reason; o.Held != why {
				l.Held = why
				notify("held", why)
			}
		case f.Grind != nil && g.State == "paused":
			if why := "grind paused: " + reason; o.Held != why {
				l.Held = why
				notify("held", why)
			}
		default:
			if o.Held != "" {
				l.Held = ""
			}
			switch {
			case g.Due != "" && g.Due != o.Nudged && idleOrNone:
				l.Nudged = g.Due
				send(grindMsg(pr.URL, f.Channel, true, s.CI, ""))
			case agent == "blocked" && o.NeedsYou == "":
				l.NeedsYou = "the grind waits on you"
				notify("needs_you", l.NeedsYou)
			case agent != "blocked" && o.NeedsYou != "":
				l.NeedsYou = ""
			}
		}
		return l, acts

	case store.StMergeGate, store.StAwaitingMerge:
		dropMergeError := func() { // a failed attempt that no longer applies
			if o.MergeError != "" {
				l.MergeError, l.MergeFails, l.Held = "", 0, ""
				if strings.HasPrefix(o.NeedsYou, "merge failed") {
					l.NeedsYou = ""
				}
			}
		}
		if pr.Conflict {
			to(store.StConflictFix, "")
			send(conflictMsg(pr.N, base))
			return l, acts
		}
		if pr.CI == "failure" && s.CI == "wait" {
			dropMergeError()
			if o.Held != "CI is red" {
				l.Held = "CI is red"
				notify("held", fmt.Sprintf("CI is red on PR #%d", pr.N))
			}
			return l, acts
		}
		if o.Held != "" && o.MergeError == "" {
			l.Held = ""
		}
		if pr.CI == "failure" && s.CI == "defer" && o.CIFixed != pr.SHA {
			l.CIFixed = pr.SHA // once per red head commit, like `nudged` for a grind round
			send(ciFixMsg(pr.N))
		}
		if pr.CI != "none" {
			l.NoneSince, l.NoneSHA = 0, ""
		} else if o.NoneSHA != pr.SHA || o.NoneSince == 0 {
			l.NoneSince, l.NoneSHA = now, pr.SHA
		}
		why := ""
		if !o.ForceMerge {
			why = gate(o, f, s, now)
		}
		if why != "" {
			dropMergeError()
			if o.Stage == store.StAwaitingMerge {
				to(store.StMergeGate, "")
			}
			l.Gate = why
			return l, acts
		}
		l.Gate = ""
		if o.ForceMerge || (s.AutoMerge && !o.HoldMerge) {
			if pr.SHA == "" { // never merge unpinned
				l.Gate = "head commit unknown"
			} else if o.MergeAt == 0 || now-o.MergeAt >= MergeRetrySeconds {
				l.MergeAt = now
				acts = append(acts, Action{Kind: AMerge, PR: pr.N, SHA: pr.SHA})
			}
		} else if o.Stage != store.StAwaitingMerge {
			to(store.StAwaitingMerge, fmt.Sprintf("PR #%d is ready to merge", pr.N))
		}
		return l, acts

	case store.StConflictFix:
		if !pr.Conflict && (free || pr.CI == "success") && idleOrNone {
			to(store.StMergeGate, "")
			return l, acts
		}
		if pr.Conflict {
			return waits(o, l, agent, acts, "stopped with the conflict unresolved", now)
		}
		return l, acts
	}

	// followups
	if !f.IssueOpen && (agent == "idle" || agent == "gone" || agent == "") {
		to(store.StClosed, "")
		l.EndedAt, l.Gate = now, ""
		acts = append(acts, Action{Kind: AClose})
		return l, acts
	}
	return waits(o, l, agent, acts, "followups stopped with the issue still open", now)
}

// waits: a blocked session needs the user at once; an idle one only after IdleGraceSeconds, so the
// board can catch up with what it just did (a PR marked ready, an issue closed).
func waits(o, l store.Lane, agent string, acts []Action, idleWhy string, now float64) (store.Lane, []Action) {
	since := now
	if agent == "idle" {
		if o.IdleSince == 0 {
			l.IdleSince = now
		} else {
			since = o.IdleSince
		}
	} else if o.IdleSince != 0 {
		l.IdleSince = 0
	}
	why := ""
	switch {
	case agent == "blocked":
		why = "waiting on you"
	case agent == "idle" && now-since >= IdleGraceSeconds:
		why = idleWhy
	}
	if why != o.NeedsYou {
		l.NeedsYou = why
		if why != "" {
			acts = append(acts, Action{Kind: ANotify, NKind: "needs_you", NText: why})
		}
	}
	return l, acts
}

// stalls is waits for an implementing lane under the idle guard: a blocked session still needs
// the user, but one idle past the grace stopped before a ready PR, which is not a question.
func stalls(o, l store.Lane, agent string, acts []Action, now float64) (store.Lane, []Action) {
	l, acts = waits(o, l, agent, acts, "", now) // the grace clock and "waiting on you", nothing for idle
	l.Stalled = ""
	if agent == "idle" && now-l.IdleSince >= IdleGraceSeconds {
		l.Stalled = Stalled
	}
	return l, acts
}

// ---- scheduling (W§2.5) ----

// Startable lists queued lanes whose blockers are all closed, by issue number, up to the free
// slots. Only a running dispatch starts lanes, never during a usage limit, and never on a guess:
// a lane needs facts.
func Startable(d *store.Dispatch, facts map[string]Facts, now float64) []string {
	if d.State != store.Running {
		return nil
	}
	free := d.Settings.Max
	for _, x := range d.Lanes {
		if x.LimitedUntil > now {
			return nil
		}
		if store.Active(x.Stage) {
			free--
		}
	}
	var out []string
	for _, k := range d.SortedKeys() {
		if free <= 0 {
			break
		}
		x := d.Lanes[k]
		if x.Stage != store.StQueued || x.Paused {
			continue
		}
		blocked := false
		for _, b := range x.Deps {
			if y, ok := d.Lanes[b]; ok && y.Stage != store.StClosed {
				blocked = true
			}
		}
		if blocked {
			continue
		}
		f, ok := facts[k]
		if !ok { // never launch on a guess: wait for the repo's first fresh poll
			continue
		}
		outside := false
		for _, b := range f.BlockersOpen {
			if _, in := d.Lanes[b]; !in {
				outside = true
			}
		}
		if outside { // a blocker outside this dispatch is still open
			continue
		}
		out = append(out, k)
		free--
	}
	return out
}

// Strand reason prefixes.
const (
	StrandSkipped = "blocked by skipped #"
	StrandCycle   = "dependency cycle"
)

// Stranded maps queued, unpaused lanes that can never start to why: a skipped blocker upstream, or
// a cycle. A dep outside the dispatch, or one that is active, paused or limited, is only waiting.
func Stranded(d *store.Dispatch) map[string]string {
	var why func(k string, path map[string]bool) string
	why = func(k string, path map[string]bool) string {
		if path[k] {
			return StrandCycle
		}
		for _, b := range d.Lanes[k].Deps {
			y, ok := d.Lanes[b]
			if !ok {
				continue
			}
			switch y.Stage {
			case store.StSkipped:
				return StrandSkipped + strconv.Itoa(y.N)
			case store.StQueued:
				np := map[string]bool{k: true}
				for p := range path {
					np[p] = true
				}
				if r := why(b, np); r != "" {
					return r
				}
			}
		}
		return ""
	}
	out := map[string]string{}
	for k, x := range d.Lanes {
		if x.Stage == store.StQueued && !x.Paused {
			if r := why(k, map[string]bool{}); r != "" {
				out[k] = r
			}
		}
	}
	return out
}

// SnapInfo is what Diagnose needs of a poll snapshot.
type SnapInfo struct {
	Stale bool
	Error string
	Known bool // false: the repo is not checked
}

// Problem is one line of `dispatch doctor`.
type Problem struct {
	Lane    string `json:"lane"`
	Problem string `json:"problem"`
}

// Diagnose says why a live dispatch cannot move. Pure. A done or cancelled dispatch has none.
func Diagnose(d *store.Dispatch, snaps map[string]SnapInfo) []Problem {
	if d.State == store.Done || d.State == store.Cancelled {
		return nil
	}
	strand := Stranded(d)
	var out []Problem
	keys := d.SortedKeys()
	for _, k := range keys {
		if r, ok := strand[k]; ok {
			out = append(out, Problem{k, r})
		}
	}
	live := map[string]bool{}
	for _, x := range d.Lanes {
		if x.Stage != store.StClosed && x.Stage != store.StSkipped {
			live[x.Repo] = true
		}
	}
	var repos []string
	for r := range live {
		repos = append(repos, r)
	}
	sort.Strings(repos)
	for _, r := range repos {
		s, ok := snaps[r]
		if !ok || !s.Known {
			continue
		}
		if s.Stale || s.Error != "" {
			e := s.Error
			if e == "" {
				e = "not fetched yet"
			}
			out = append(out, Problem{"", fmt.Sprintf("stale poll snapshot for %s: %s", r, e)})
		}
	}
	for _, k := range keys {
		x := d.Lanes[k]
		for _, f := range [][2]string{{"needs you", x.NeedsYou}, {"held", x.Held}} {
			if f[1] != "" && f[1] != strand[k] {
				out = append(out, Problem{k, f[0] + ": " + f[1]})
			}
		}
	}
	return out
}

// Child is one resolved issue of an epic or pick.
type Child struct {
	Repo    string   `json:"repo"`
	N       int      `json:"n"`
	Title   string   `json:"title"`
	Refined bool     `json:"refined"`
	Deps    []string `json:"deps"`
	Base    string   `json:"base,omitempty"`
}

// SyncLanes adds new children as lanes; a "needs refine" lane is queued once refined. It returns
// the added keys. A done dispatch that gains work flips to paused.
func SyncLanes(d *store.Dispatch, children []Child, now float64) []string {
	var added []string
	wasDone := d.State == store.Done
	addedWork := false
	for _, c := range children {
		k := store.Key(c.Repo, c.N)
		x := d.Lanes[k]
		if x == nil {
			l := &store.Lane{Repo: c.Repo, N: c.N, Title: c.Title, Deps: append([]string{}, c.Deps...), Base: c.Base,
				Stage: store.StQueued}
			if !c.Refined {
				l.Stage, l.SkipReason = store.StSkipped, "needs refine"
			}
			if d.Lanes == nil {
				d.Lanes = map[string]*store.Lane{}
			}
			d.Lanes[k] = l
			added = append(added, k)
			continue
		}
		// a re-read lists only blockers still open: keep the ones already known, or the graph loses its shape
		set := map[string]bool{}
		for _, b := range x.Deps {
			set[b] = true
		}
		for _, b := range c.Deps {
			set[b] = true
		}
		x.Deps = x.Deps[:0:0]
		for b := range set {
			x.Deps = append(x.Deps, b)
		}
		sort.Strings(x.Deps)
		if x.Stage == store.StSkipped && x.SkipReason == "needs refine" && c.Refined {
			x.Stage, x.SkipReason = store.StQueued, ""
			addedWork = true
		}
	}
	if wasDone && (len(added) > 0 || addedWork) { // QA filed new children: pause until the user refines them and resumes
		d.State, d.EndedAt = store.Paused, 0
		d.AddEvent("", "paused", "new issues joined: refine them, then resume", now)
	}
	return added
}

// Plan is the preview of a dispatch (waves and warnings).
type Plan struct {
	Waves    [][]string
	Warnings []string
}

// MakePlan groups refined lanes into waves (Kahn layers) and warns about the rest. No side effects.
func MakePlan(children []Child) Plan {
	lanes := map[string]Child{}
	for _, c := range children {
		lanes[store.Key(c.Repo, c.N)] = c
	}
	keys := make([]string, 0, len(lanes))
	for k := range lanes {
		keys = append(keys, k)
	}
	sortKeys := func(ks []string) {
		sort.Slice(ks, func(i, j int) bool {
			if lanes[ks[i]].N != lanes[ks[j]].N {
				return lanes[ks[i]].N < lanes[ks[j]].N
			}
			return ks[i] < ks[j]
		})
	}
	sortKeys(keys)
	p := Plan{Waves: [][]string{}, Warnings: []string{}}
	left := map[string]bool{}
	for _, k := range keys {
		if !lanes[k].Refined {
			p.Warnings = append(p.Warnings, k+": needs refine")
		} else {
			left[k] = true
		}
	}
	done := map[string]bool{}
	for len(left) > 0 {
		var wave []string
		for k := range left {
			ok := true
			for _, b := range lanes[k].Deps {
				if _, in := lanes[b]; in && !done[b] {
					ok = false
				}
			}
			if ok {
				wave = append(wave, k)
			}
		}
		if len(wave) == 0 {
			var rest []string
			for k := range left {
				rest = append(rest, k)
			}
			sort.Strings(rest)
			p.Warnings = append(p.Warnings, "dependency cycle or blocked by an unrefined issue: "+strings.Join(rest, ", "))
			break
		}
		sortKeys(wave)
		p.Waves = append(p.Waves, wave)
		for _, k := range wave {
			done[k] = true
			delete(left, k)
		}
	}
	return p
}

// ---- user actions (W§2.5) ----

// Lane actions.
var LaneActions = []string{"pause", "resume", "retry", "skip", "merge", "hold", "unhold", "send", "unblock"}

// Settled reports a lane that will do nothing more: closed, or skipped.
func Settled(x *store.Lane) bool { return x.Stage == store.StClosed || x.Stage == store.StSkipped }

// SkippedDeps lists the lane's blockers in this dispatch that were skipped: they never close, so the
// lane waits on them for good until they are retried or the lane is unblocked.
func SkippedDeps(d *store.Dispatch, x *store.Lane) []string {
	var out []string
	for _, b := range x.Deps {
		if y, ok := d.Lanes[b]; ok && y.Stage == store.StSkipped {
			out = append(out, b)
		}
	}
	return out
}

// EndActions are the end-of-dispatch actions.
var EndActions = []string{"open-pr", "qa", "grind-pr"}

func hasOutbox(l *store.Lane, kind string) bool {
	for _, o := range l.Outbox {
		if o.Kind == kind {
			return true
		}
	}
	return false
}

func queueClose(l *store.Lane) {
	if !hasOutbox(l, "close") {
		l.Outbox = append(l.Outbox, store.OutboxItem{Kind: "close"})
	}
}

// ApplyLaneAction is the user's action on one lane. Session effects go through the lane's outbox;
// the tick runs them. The caller holds the dispatch lock and saves.
func ApplyLaneAction(d *store.Dispatch, key, action, text string, now float64) error {
	x := d.Lanes[key]
	if x == nil {
		return errs.Invalid("no lane %s", key)
	}
	switch action {
	case "pause":
		x.Paused = true
	case "resume":
		x.Paused = false
		if x.PausedBy != "" { // Pause > Now closed its session
			x.PausedBy = ""
			x.Restart = true
		}
	case "skip":
		if store.Active(x.Stage) && x.Handle != nil {
			x.Outbox = append(x.Outbox, store.OutboxItem{Kind: "close"})
		}
		x.Stage, x.SkipReason, x.PausedBy = store.StSkipped, "skipped by you", ""
		// a skipped lane is settled: nothing about it waits on you any more
		x.NeedsYou, x.Stalled, x.Held, x.Gate, x.MergeError, x.MergeFails, x.IdleSince, x.ForceMerge = "", "", "", "", "", 0, 0, false
		if x.EndedAt == 0 {
			x.EndedAt = now
		}
	case "retry": // clear held/needs; a fresh session for the lane's stage at the next tick
		red := x.Held == "CI is red"
		x.Held, x.NeedsYou, x.Stalled, x.Paused, x.PausedBy, x.MergeError, x.MergeFails = "", "", "", false, "", "", 0
		switch {
		case x.Stage == store.StSkipped || (x.Stage == store.StImplementing && x.PR == 0):
			if x.Handle != nil {
				x.Outbox = append(x.Outbox, store.OutboxItem{Kind: "close"})
			}
			x.Stage, x.SkipReason, x.Handle, x.EndedAt = store.StQueued, "", nil, 0
		case red && x.Handle != nil: // a retry of red CI means: fix it, in the session that wrote the PR
			x.Outbox = append(x.Outbox, store.OutboxItem{Kind: "send", Text: ciFixMsg(x.PR).Plain})
		case store.Active(x.Stage):
			x.Restart = true
		}
	case "merge":
		x.ForceMerge = true
	case "hold", "unhold":
		x.HoldMerge = action == "hold"
	case "unblock": // stop waiting on blockers you skipped; the lane may start without them
		skipped := SkippedDeps(d, x)
		if len(skipped) == 0 {
			return errs.Invalid("lane %s waits on no skipped issue", key)
		}
		drop := map[string]bool{}
		for _, b := range skipped {
			drop[b] = true
		}
		var keep []string
		for _, b := range x.Deps {
			if !drop[b] {
				keep = append(keep, b)
			}
		}
		x.Deps = keep
		x.Unblocked = append(x.Unblocked, skipped...)
	case "send":
		if strings.TrimSpace(text) == "" || len([]rune(text)) > 2000 {
			return errs.Invalid("send needs a message of 1 to 2000 characters")
		}
		if x.Handle == nil {
			return errs.Invalid("lane %s has no session to send to", key)
		}
		x.Outbox = append(x.Outbox, store.OutboxItem{Kind: "send", Text: strings.TrimSpace(text)})
	default:
		return errs.Invalid("action must be one of %s", strings.Join(LaneActions, ", "))
	}
	d.AddEvent(key, "lane", action, now)
	return nil
}

// RetryFailed retries every lane that failed to start, needs you or is held, and returns their
// keys. Lanes skipped by you, needing a refine, closed or healthy are left alone.
func RetryFailed(d *store.Dispatch, now float64) []string {
	var failed []string
	for _, k := range d.SortedKeys() {
		x := d.Lanes[k]
		if (x.Stage == store.StSkipped && strings.HasPrefix(x.SkipReason, "start failed")) || x.NeedsYou != "" || x.Held != "" {
			failed = append(failed, k)
		}
	}
	for _, k := range failed {
		_ = ApplyLaneAction(d, k, "retry", "", now)
	}
	return failed
}

func issuesN(n int) string {
	if n == 1 {
		return "1 issue"
	}
	return fmt.Sprintf("%d issues", n)
}

// SetState moves the whole dispatch (running, paused, cancelled). now: on paused, also stop the
// sessions of the running lanes.
func SetState(d *store.Dispatch, state string, stopNow bool, now float64) error {
	if state != store.Running && state != store.Paused && state != store.Cancelled {
		return errs.Invalid("state must be running, paused or cancelled")
	}
	d.State = state
	text := "dispatch " + state
	switch {
	case state == store.Cancelled:
		d.EndedAt = now
		for _, x := range d.Lanes { // the user's paused lanes too
			if store.Active(x.Stage) && x.Handle != nil {
				queueClose(x)
			}
		}
	case state == store.Paused && stopNow:
		n := 0
		for _, x := range d.Lanes {
			if store.Active(x.Stage) && !x.Paused {
				x.Paused, x.PausedBy, x.NeedsYou, x.LimitedUntil = true, "dispatch", "", 0
				if x.Handle != nil {
					x.Outbox = append(x.Outbox, store.OutboxItem{Kind: "close"})
				}
				n++
			}
		}
		if n > 0 {
			text = "dispatch paused now: " + issuesN(n) + " stopped"
		}
	case state == store.Running:
		n := 0
		for _, x := range d.Lanes {
			if x.PausedBy == "dispatch" {
				x.Paused, x.PausedBy, x.Restart = false, "", true
				n++
			}
		}
		if n > 0 {
			text = "dispatch running: " + issuesN(n) + " restarted"
		}
	}
	d.AddEvent("", state, text, now)
	return nil
}

// RequestEnd queues an end action for the next tick. Never automatic; refused for a list of issues.
func RequestEnd(d *store.Dispatch, action string, now float64) error {
	ok := false
	for _, a := range EndActions {
		ok = ok || a == action
	}
	if !ok {
		return errs.Invalid("end action must be one of %s", strings.Join(EndActions, ", "))
	}
	if len(d.Issues) > 0 || d.Epic == nil {
		return errs.Invalid("%s needs an epic: not available for a list of issues", action)
	}
	if action == "open-pr" && store.Str(d.Settings.FeatureBranch) == "" {
		return errs.Invalid("open-pr needs a feature branch")
	}
	if action == "grind-pr" && len(d.FinalPRs) == 0 {
		return errs.Invalid("grind-pr needs the PR from open-pr first")
	}
	d.EndReqs = append(d.EndReqs, action)
	d.AddEvent("", "end", "requested "+action, now)
	return nil
}

// IssuesTitle names a dispatch of hand-picked issues.
func IssuesTitle(keys []string) string {
	nums := make([]int, 0, len(keys))
	for _, k := range keys {
		_, n, _ := strings.Cut(k, "#")
		v, _ := strconv.Atoi(n)
		nums = append(nums, v)
	}
	sort.Ints(nums)
	var parts []string
	for i, n := range nums {
		if i == 3 {
			break
		}
		parts = append(parts, "#"+strconv.Itoa(n))
	}
	t := "Small changes: " + strings.Join(parts, ", ")
	if len(nums) > 3 {
		t += fmt.Sprintf(" +%d more", len(nums)-3)
	}
	return t
}
