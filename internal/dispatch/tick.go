package dispatch

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/sessions"
)

// ticker is one tick of one dispatch (W§2.5). The caller holds the dispatch lock around load and run.
type ticker struct {
	s     *Service
	ctx   context.Context
	d     *store.Dispatch
	facts map[string]Facts
	now   float64
	new   []store.Event
}

func (t *ticker) save() {
	if err := store.Save(t.s.d.Home, t.d); err != nil {
		logf("%s: save: %v", t.d.ID, err)
	}
}

func (t *ticker) ev(lane, kind, text string) {
	t.new = append(t.new, t.d.AddEvent(lane, kind, text, t.now))
	switch kind {
	case "needs_you", "held", "awaiting_merge", "finished", "warning", "stalled":
		t.s.notify(t.d, lane, kind, text)
	}
}

// send prompts the lane's session; a lane whose session was closed (before the merge) gets a fresh one.
func (t *ticker) send(x *store.Lane, m Msg) error {
	if x.Handle != nil {
		_, _, text, err := t.s.render(m, x.Repo)
		if err != nil {
			return err
		}
		return t.s.sendSession(t.ctx, x.Handle, text)
	}
	h, err := t.s.startSession(t.ctx, t.d, target{Repo: x.Repo, N: x.N}, m)
	if err != nil {
		return err
	}
	x.Handle = h
	x.Handles = append(x.Handles, *h)
	t.save() // a crash later in the tick must not lose the handle
	return nil
}

func (t *ticker) sendText(x *store.Lane, text string) error { return t.send(x, Msg{Plain: text}) }

// continueLane resumes the lane's own session with the Continue message for its step. The lane's
// stalled check under the dispatch lock already lets only one continue through, so the session's
// own stalled flag is not required: a session that ended without the guard stalls the lane too.
func (t *ticker) continueLane(x *store.Lane) error {
	if x.Handle == nil {
		return errs.Conflict("lane has no session", nil)
	}
	rec, err := t.s.d.Sessions.Get(x.Handle.Session)
	if err != nil {
		return err
	}
	step := rec.Step
	if step == "" {
		step = implementMsg(x.N, "", 0, "").Step
	}
	return t.s.sendSession(t.ctx, x.Handle, sessions.ContinueText(step))
}

func (t *ticker) run() {
	d, s := t.d, t.s
	for _, k := range d.SortedKeys() {
		x := d.Lanes[k]
		outbox := x.Outbox
		x.Outbox = nil
		for _, o := range outbox {
			var err error
			switch {
			case o.Kind == "send":
				err = t.sendText(x, o.Text)
			case o.Kind == "continue":
				err = t.continueLane(x)
			case x.Handle != nil:
				if err = s.closeSession(t.ctx, x.Handle); err == nil {
					x.Handle = nil
				}
			}
			if err != nil {
				x.NeedsYou = fmt.Sprintf("%s failed: %s", o.Kind, errText(err))
				t.ev(k, "needs_you", x.NeedsYou)
			}
		}
		if d.State == store.Cancelled || d.State == store.Done {
			continue
		}
		f := t.facts[k]
		if x.Restart {
			x.Restart = false
			t.restart(k, x, f)
			continue
		}
		f, ok := t.facts[k]
		if !ok { // no fresh facts for this lane (repo not polled yet): never move on a guess
			continue
		}
		sentPrompt := false
		for _, o := range outbox {
			sentPrompt = sentPrompt || o.Kind == "send" || o.Kind == "continue"
		}
		if sentPrompt { // the facts predate that prompt: an idle agent is stale
			continue
		}
		old := x.Stage
		next, acts := Step(*x, f, d.Settings, t.now)
		extra, handle, handles, outb := x.Extra, x.Handle, x.Handles, x.Outbox
		*x = next
		x.Extra, x.Handle, x.Handles, x.Outbox = extra, handle, handles, outb
		if x.Stage != old {
			t.ev(k, "stage", old+" -> "+x.Stage)
		}
		for _, a := range acts {
			t.act(k, x, f, a)
		}
	}
	reqs := d.EndReqs
	d.EndReqs = nil
	for _, action := range reqs {
		if out, err := t.runEnd(action); err != nil {
			t.ev("", "needs_you", fmt.Sprintf("%s failed: %s", action, errText(err)))
		} else {
			t.ev("", "end", out)
		}
	}
	for _, k := range Startable(d, t.facts, t.now) {
		x := d.Lanes[k]
		m := implementMsg(x.N, LaneBase(x, d.Settings), 0, d.Settings.CI)
		h, err := s.startSession(t.ctx, d, target{Repo: x.Repo, N: x.N}, m)
		if err != nil {
			x.Stage, x.SkipReason = store.StSkipped, "start failed: "+errText(err)
			t.ev(k, "needs_you", "start failed: "+errText(err))
			continue
		}
		x.Handle = h
		x.Handles = append(x.Handles, *h)
		x.Stage, x.StartedAt, x.NeedsYou = store.StImplementing, t.now, ""
		t.ev(k, "stage", "queued -> implementing")
		t.save()
	}
	if d.State == store.Running {
		strands := Stranded(d)
		idle := true
		for _, x := range d.Lanes {
			idle = idle && !store.Active(x.Stage)
		}
		for _, k := range d.SortedKeys() {
			x := d.Lanes[k]
			if why, ok := strands[k]; ok {
				if idle && x.NeedsYou != why {
					x.NeedsYou = why
					t.ev(k, "needs_you", why)
				}
			} else if x.Stage == store.StQueued && (strings.HasPrefix(x.NeedsYou, StrandSkipped) || strings.HasPrefix(x.NeedsYou, StrandCycle)) {
				x.NeedsYou = "" // the blocker was retried
			}
		}
	}
	if d.State == store.Running && len(d.Lanes) > 0 {
		all := true
		for _, x := range d.Lanes {
			all = all && (x.Stage == store.StClosed || x.Stage == store.StSkipped)
		}
		if all {
			d.State, d.EndedAt = store.Done, t.now
			t.ev("", "finished", "every lane is closed or skipped")
		}
	}
	t.save()
}

func (t *ticker) restart(k string, x *store.Lane, f Facts) {
	var err error
	if x.Handle != nil {
		err = t.s.closeSession(t.ctx, x.Handle)
	}
	if err == nil {
		prURL := ""
		if f.PR != nil {
			prURL = f.PR.URL
		}
		sl := *x // the lane never records its channel: the resolver's answer is the freshest one
		if sl.Channel == "" {
			sl.Channel = f.Channel
		}
		if m, ok := stageMsg(&sl, t.d.Settings, prURL); ok {
			var h *store.Handle
			if h, err = t.s.startSession(t.ctx, t.d, target{Repo: x.Repo, N: x.N}, m); err == nil {
				x.Handle = h
				x.Handles = append(x.Handles, *h)
				t.save()
			}
		} else {
			x.Handle = nil
		}
	}
	if err != nil {
		x.NeedsYou = "restart failed: " + errText(err)
		t.ev(k, "needs_you", x.NeedsYou)
		return
	}
	t.ev(k, "lane", "restarted in "+x.Stage)
}

// act runs one action of Step. A failure never stops the other lanes.
func (t *ticker) act(k string, x *store.Lane, f Facts, a Action) {
	var err error
	switch a.Kind {
	case ASend:
		err = t.send(x, a.Msg)
	case AContinue:
		if x.Handle != nil {
			err = t.s.sendSession(t.ctx, x.Handle, Continue)
		}
	case AClose:
		if x.Handle != nil {
			err = t.s.closeSession(t.ctx, x.Handle)
		}
	case AMerge:
		t.merge(k, x, f, a)
	case ANotify:
		t.ev(k, a.NKind, a.NText)
	}
	if err != nil {
		x.NeedsYou = fmt.Sprintf("%s failed: %s", a.Kind, errText(err))
		t.ev(k, "needs_you", x.NeedsYou)
	}
}

func (t *ticker) merge(k string, x *store.Lane, f Facts, a Action) {
	d := t.d
	ok, msg := t.s.merge(t.ctx, x.Repo, a.PR, a.SHA)
	x.ForceMerge = false
	low := strings.ToLower(msg)
	switch {
	case ok:
		x.MergeError, x.MergeFails, x.Held = "", 0, ""
		if strings.HasPrefix(x.NeedsYou, "merge failed") {
			x.NeedsYou = ""
		}
		t.ev(k, "merged", fmt.Sprintf("merged PR #%d", a.PR))
		if d.Settings.CI == "ignore" && f.PR != nil && (f.PR.CI == "failure" || f.PR.CI == "pending") {
			if f.PR.CI == "failure" {
				t.ev(k, "warning", "merged with red CI")
			} else {
				t.ev(k, "warning", "merged with CI pending")
			}
		}
	case strings.Contains(low, "conflict"): // the board had not seen the conflict yet: fix it in the lane
		x.Stage, x.MergeAt = store.StConflictFix, 0
		if err := t.send(x, conflictMsg(a.PR, LaneBase(x, d.Settings))); err != nil {
			x.NeedsYou = "merge failed: " + errText(err)
			t.ev(k, "needs_you", x.NeedsYou)
			return
		}
		t.ev(k, "stage", "merge_gate -> conflict_fix (GitHub refused the merge: conflicts)")
	case strings.Contains(low, "not up to date"): // branch protection wants base merged in: GitHub does it
		r := t.s.d.GH.Run(t.ctx, []string{"pr", "update-branch", strconv.Itoa(a.PR), "-R", x.Repo}, execx.Opts{Timeout: ghTickTimeout})
		if r.Code == 0 { // new head commit: the gate waits for its CI, then merges again
			t.ev(k, "lane", fmt.Sprintf("PR #%d was behind its base: merged the base into it", a.PR))
			return
		}
		x.Stage, x.MergeAt = store.StConflictFix, 0
		if err := t.send(x, conflictMsg(a.PR, LaneBase(x, d.Settings))); err != nil {
			x.NeedsYou = "merge failed: " + errText(err)
			t.ev(k, "needs_you", x.NeedsYou)
			return
		}
		t.ev(k, "stage", "merge_gate -> conflict_fix (could not update the branch from its base)")
	default:
		x.MergeFails++
		x.Held = "merge failed: " + msg
		if x.MergeError != msg { // the same text again is not news
			x.MergeError = msg
			t.ev(k, "held", x.Held)
		}
		if x.MergeFails >= MergeFailsBeforeNeedsYou && x.NeedsYou == "" {
			x.NeedsYou = fmt.Sprintf("merge failed %d times: %s", x.MergeFails, msg)
			t.ev(k, "needs_you", x.NeedsYou)
		}
	}
}

// runEnd runs one end action (W§2.5) and says what happened.
func (t *ticker) runEnd(action string) (string, error) {
	d, s := t.d, t.s
	if d.Epic == nil {
		return "", fmt.Errorf("%s needs an epic", action)
	}
	epicRepo, epicN, _ := strings.Cut(*d.Epic, "#")
	n, _ := strconv.Atoi(epicN)
	fb := store.Str(d.Settings.FeatureBranch)
	switch action {
	case "open-pr":
		repos := map[string]bool{}
		for _, x := range d.Lanes {
			repos[x.Repo] = true
		}
		var rs, out []string
		for r := range repos {
			rs = append(rs, r)
		}
		sort.Strings(rs)
		for _, repo := range rs {
			if u, ok := d.FinalPRs[repo]; ok { // opened by an earlier try that failed on a later repo
				out = append(out, u)
				continue
			}
			base := store.Str(d.Settings.BaseBranch)
			if base == "" {
				base = s.defaultBranch(t.ctx, repo)
			}
			if base == "" {
				base = "master"
			}
			r := s.d.GH.Run(t.ctx, []string{"pr", "create", "-R", repo, "--base", base, "--head", fb,
				"--title", fmt.Sprintf("Epic #%s: merge %s", epicN, fb),
				"--body", fmt.Sprintf("Every child of %s is merged into `%s`.", *d.Epic, fb)}, execx.Opts{Timeout: ghTickTimeout})
			if r.Code != 0 {
				msg := strings.TrimSpace(string(r.Stderr))
				if msg == "" {
					msg = strings.TrimSpace(string(r.Stdout))
				}
				return "", fmt.Errorf("gh pr create on %s failed: %s", repo, trunc(msg, 200))
			}
			lines := strings.Split(strings.TrimSpace(string(r.Stdout)), "\n")
			url := strings.TrimSpace(lines[len(lines)-1])
			if d.FinalPRs == nil {
				d.FinalPRs = map[string]string{}
			}
			d.FinalPRs[repo] = url
			out = append(out, url)
		}
		return "opened " + strings.Join(out, ", "), nil
	case "qa":
		h, err := s.startSession(t.ctx, d, target{Repo: epicRepo, N: n, Label: "qa-" + epicN}, qaMsg(*d.Epic, fb))
		if err != nil {
			return "", err
		}
		d.QA = h
		return "QA session started", nil
	}
	var repos, urls []string
	for r := range d.FinalPRs {
		repos = append(repos, r)
	}
	sort.Strings(repos)
	for _, repo := range repos {
		url := d.FinalPRs[repo]
		num, _ := strconv.Atoi(url[strings.LastIndex(url, "/")+1:])
		h, err := s.startSession(t.ctx, d, target{Repo: repo, N: num, Label: "grind-" + repo[strings.LastIndex(repo, "/")+1:]},
			grindMsg(url, "", false, "wait", ""))
		if err != nil {
			return "", err
		}
		if d.FinalGr == nil {
			d.FinalGr = map[string]store.Handle{}
		}
		d.FinalGr[repo] = *h
		urls = append(urls, url)
	}
	return "grind started on " + strings.Join(urls, ", "), nil
}
