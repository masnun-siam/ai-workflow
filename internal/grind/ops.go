package grind

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
)

var listSplitRE = regexp.MustCompile(`[,\s]+`)

func splitList(s string) []string {
	var out []string
	for _, p := range listSplitRE.Split(strings.TrimSpace(s), -1) {
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

// addList adds values to a comma separated header key, deduped ignoring case, order kept.
func addList(d *Doc, key string, vals ...string) {
	cur := splitList(d.Get(key))
	for _, v := range vals {
		if v == "" {
			continue
		}
		dup := false
		for _, c := range cur {
			if strings.EqualFold(c, v) {
				dup = true
			}
		}
		if !dup {
			cur = append(cur, v)
		}
	}
	if len(cur) > 0 {
		d.Set(key, strings.Join(cur, ","))
	}
}

// refreshReviewer rewrites `reviewer:`: UNRESOLVED while an unlogged Slack id has no `learned:` line,
// else the first login of `reviewers:`.
func refreshReviewer(d *Doc) {
	resolved := map[string]bool{}
	for _, l := range d.All("learned") {
		id, _, _ := strings.Cut(l, "=")
		resolved[id] = true
	}
	for _, id := range splitList(d.Get("unlogged")) {
		if !resolved[id] {
			d.Set("reviewer", "UNRESOLVED")
			return
		}
	}
	if rs := splitList(d.Get("reviewers")); len(rs) > 0 {
		d.Set("reviewer", rs[0])
	} else if d.Get("reviewer") == "" {
		d.Set("reviewer", "UNRESOLVED")
	}
}

func (r *runner) limits() (l struct{ MaxRounds, Poll, MaxWait, MaxIdle, Stuck, CITimeout, CIPoll int }) {
	g := r.st.Get().GrindLimits
	l.MaxRounds, l.Poll, l.MaxWait, l.MaxIdle, l.Stuck, l.CITimeout, l.CIPoll = g.MaxRounds, g.PollInterval, g.MaxWait, g.MaxIdleWaits, g.StuckSeen, g.CITimeout, g.CIPoll
	return
}

// guardActive returns 40 for a done grind and 41 for a paused one, after printing why.
func (r *runner) guardActive(d *Doc) int {
	if v := d.Get("done"); v != "" {
		return r.die(ExitDone, "already done: %s", v)
	}
	if v := d.Get("paused"); v != "" {
		return r.die(ExitPaused, "paused: %s; fix the cause, then re-run: setu grind start <pr>", v)
	}
	return 0
}

// needState loads the state of k or reports exit 64.
func (r *runner) needState(k Key) (*Doc, int) {
	d, err := r.files.Read(k)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, r.die(cli.ExitUsage, "no state for %s; run: setu grind start %s", k.URL(), k.URL())
		}
		return nil, r.die(ExitExternal, "cannot read the state of %s: %v", k.URL(), err)
	}
	return d, 0
}

// post sends a terminal message to the grind's Slack thread, mentioning the owner. It never
// mentions the bot. A GitHub-path grind has no thread, and a failed post only warns.
func (r *runner) post(ctx context.Context, d *Doc, text string) {
	thread := d.Get("thread")
	ts := ThreadTS(thread)
	if !threadRE.MatchString(thread) || ts == "" {
		return
	}
	ch := d.Get("channel")
	if ch == "" {
		ch = ThreadChannel(thread)
	}
	if ch == "" {
		return
	}
	if uid := LoadChannels(r.h).OwnerUID; uid != "" {
		text = "<@" + uid + "> " + text
	}
	if _, _, err := r.slack.Send(ctx, ch, text, ts); err != nil {
		r.warn("could not post to the thread: %v", err)
	}
}

func resumeHint(k Key, d *Doc) string {
	if t := d.Get("thread"); threadRE.MatchString(t) {
		return t
	}
	return k.URL()
}

func (r *runner) doPause(ctx context.Context, k Key, reason string, post bool) error {
	reason = oneLine(reason)
	var snap *Doc
	err := r.files.Update(k, r.now(), func(d *Doc) error {
		d.Set("paused", stamp(r.now())+" - "+reason)
		snap = parseDoc(d.bytes())
		return nil
	})
	if err != nil {
		return err
	}
	if post && snap != nil {
		r.post(ctx, snap, fmt.Sprintf("grind paused: %s. %s. To resume: fix the cause, then re-run /pr-grind %s", reason, k.URL(), resumeHint(k, snap)))
	}
	return nil
}

// rail pauses the grind, posts the reason and returns the rail's exit code.
func (r *runner) rail(ctx context.Context, k Key, code int, format string, a ...any) int {
	msg := fmt.Sprintf(format, a...)
	r.warn("rail: %s", msg)
	if err := r.doPause(ctx, k, msg, true); err != nil {
		r.warn("could not record the pause: %v", err)
	}
	return code
}

// ---------- start ----------

func validReviewerFlag(s string) bool {
	return strings.EqualFold(s, "copilot") || reLogin.MatchString(s)
}

func without(list []string, drop string) []string {
	out := []string{}
	for _, s := range list {
		if !strings.EqualFold(s, drop) {
			out = append(out, s)
		}
	}
	return out
}

func (r *runner) start(ctx context.Context, args []string) int {
	p, err := parseArgs(args, []string{"--thread", "--channel", "--reviewer", "--mode"}, nil)
	if err != nil {
		return r.usage("start: %v", err)
	}
	if len(p.pos) != 1 {
		return r.usage("start: expected one <pr> argument")
	}
	mode := ""
	if p.has["--mode"] {
		if mode = ModeOf(p.flags["--mode"]); mode == "" {
			return r.usage("--mode must be deep or simple")
		}
	}
	reviewerFlag, channelFlag, threadFlag := p.flags["--reviewer"], p.flags["--channel"], p.flags["--thread"]
	if reviewerFlag != "" && !validReviewerFlag(reviewerFlag) {
		return r.usage("--reviewer must be a GitHub login or copilot")
	}
	if threadFlag != "" && !reSlackURL.MatchString(threadFlag) {
		return r.usage("--thread must be a Slack thread url")
	}
	k, threadArg, err := r.resolveRef(ctx, p.pos[0], true)
	if err != nil {
		return r.usage("cannot resolve a PR from %s: %v", p.pos[0], err)
	}
	if threadFlag == "" {
		threadFlag = threadArg
	}
	if threadFlag != "" {
		threadFlag, _, _ = strings.Cut(threadFlag, "?")
	}
	info, err := viewPR(ctx, r.gh, k)
	if err != nil {
		return r.die(ExitExternal, "cannot read %s: %v", k.URL(), err)
	}
	if info.State != "OPEN" {
		return r.die(ExitConflict, "PR #%d is %s; nothing to grind.", k.N, info.State)
	}
	if info.IsDraft {
		return r.die(ExitConflict, "PR #%d is a draft; mark it ready for review before grinding.", k.N)
	}
	now := r.now()

	// an existing state with a thread is reused, never restarted
	if d, err := r.files.Read(k); err == nil && d.Get("thread") != "" {
		err := r.files.Update(k, now, func(d *Doc) error {
			if !r.headless { // a human run clears the stop; an automated re-entry never does
				d.Del("paused")
				d.Del("done")
				d.Del("next-poll")
			}
			d.Del("idle-waits")
			if mode != "" {
				d.Set("mode", mode)
			}
			return nil
		})
		if err != nil {
			return r.die(ExitExternal, "cannot update the state: %v", err)
		}
		return r.printStatus(k)
	}

	ch := LoadChannels(r.h)
	pinned := reviewerFlag != "" && channelFlag == ""
	var rv Reviewers
	if !pinned {
		var rerr error
		if rv, rerr = ResolvePR(r.h, r.st, k.URL(), false); rerr != nil {
			return r.die(ExitExternal, "%v", rerr)
		}
		if rv.Skip != nil {
			if channelFlag != "" && strings.HasPrefix(*rv.Skip, "invalid Slack channel") {
				rv = emptyReviewers("")
			} else {
				fmt.Fprintln(r.env.Stdout, *rv.Skip)
				return ExitConflict
			}
		}
	}
	useSlack := !pinned && (channelFlag != "" || threadFlag != "" || rv.Path == nil || *rv.Path == "slack")

	var (
		thread, channel, reviewer string
		last, reviewers, unlogged []string
	)
	if !useSlack {
		logins := rv.Logins
		if pinned {
			logins = []string{reviewerFlag}
			if strings.EqualFold(reviewerFlag, info.Author) {
				return r.usage("--reviewer is the PR author")
			}
		}
		logins = without(logins, info.Author)
		if len(logins) == 0 {
			fmt.Fprintln(r.env.Stdout, NoReviewer)
			return ExitConflict
		}
		ok, failed := requestReviewers(ctx, r.gh, k, logins)
		if len(ok) == 0 {
			return r.die(ExitExternal, "could not request a review: %s", strings.Join(failed, "; "))
		}
		reviewers, last, thread = ok, ok, "github"
		reviewer = ok[0]
		return r.finishStart(ctx, k, info, now, mode, startHeader{
			thread: thread, reviewer: reviewer, reviewers: reviewers, last: last, pinned: pinnedLogin(pinned, reviewerFlag),
			failed: failed,
		})
	}

	ids := append([]string(nil), rv.Mentions...)
	botFallback := false
	if len(ids) == 0 {
		if ch.BotUID == "" {
			return r.usage("channels.json has no bot_uid and no reviewer has a Slack id")
		}
		ids, botFallback = []string{ch.BotUID}, true
	}
	if threadFlag != "" {
		thread = threadFlag
		channel = ThreadChannel(thread)
	} else {
		channel = firstNonEmpty(channelFlag, derefStr(rv.Channel), ch.Mapped(k.Slug()), ch.DMFallback)
		if channel == "" {
			return r.usage("no channel for %s and no dm_fallback in channels.json", k.Slug())
		}
		if ch.WorkspaceURL == "" {
			return r.usage("channels.json has no workspace_url; add it (never guessed)")
		}
		text := ch.Fill(firstNonEmpty(ch.Trigger, defaultTrigger), ids, k.URL())
		ts, cid, err := r.slack.Send(ctx, channel, text, "")
		if err != nil {
			return r.die(ExitExternal, "slack post failed; nothing recorded: %v", err)
		}
		if ts == "" {
			return r.die(ExitExternal, "slack gave no ts; nothing recorded")
		}
		if cid != "" {
			channel = cid
		}
		thread = ch.WorkspaceURL + "/archives/" + channel + "/p" + strings.Replace(ts, ".", "", 1)
	}
	reviewers = without(rv.Logins, info.Author)
	if botFallback {
		unlogged = []string{ch.BotUID}
	} else {
		unlogged = rv.Unlogged
	}
	last = ids
	h := startHeader{thread: thread, channel: channel, reviewers: reviewers, unlogged: unlogged, last: last}
	return r.finishStart(ctx, k, info, now, mode, h)
}

type startHeader struct {
	thread, channel, reviewer, pinned string
	reviewers, unlogged, last, failed []string
}

func pinnedLogin(pinned bool, l string) string {
	if pinned {
		return l
	}
	return ""
}

func derefStr(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func firstNonEmpty(s ...string) string {
	for _, v := range s {
		if v != "" {
			return v
		}
	}
	return ""
}

func (r *runner) finishStart(ctx context.Context, k Key, info PRInfo, now time.Time, mode string, h startHeader) int {
	err := r.files.Create(k, now, func(d *Doc) error {
		d.lines = nil
		d.Append(fmt.Sprintf("# pr-grind - %s #%d", k.Slug(), k.N), "")
		put := func(key, val string) {
			if val != "" {
				d.Add(key, val)
			}
		}
		put("owner", k.Owner)
		put("repo", k.Repo)
		put("number", itoa(k.N))
		put("author", info.Author)
		put("base", info.Base)
		put("mode", mode)
		put("thread", h.thread)
		put("channel", h.channel)
		put("reviewers", strings.Join(h.reviewers, ","))
		put("unlogged", strings.Join(h.unlogged, ","))
		put("reviewers-last", strings.Join(h.last, ","))
		put("pinned", h.pinned)
		put("head-at-open", info.Head)
		put("last-seen", stamp(now))
		put("started", stamp(now))
		put("updated", stamp(now))
		for _, f := range h.failed {
			d.Add("request-failed", f)
		}
		if h.reviewer != "" {
			d.Set("reviewer", h.reviewer)
		} else {
			refreshReviewer(d)
		}
		d.Append("")
		return nil
	})
	if err != nil {
		return r.die(ExitExternal, "cannot write the state: %v", err)
	}
	return r.printStatus(k)
}

func (r *runner) printStatus(k Key) int {
	st, _ := ReadStatus(r.files, k, settingsMode(r.st))
	r.printJSON(st)
	return 0
}

// ---------- wait ----------

// RoundOut is the JSON `wait` prints for a landed round (and `.last.json` stores).
type RoundOut struct {
	Round     int         `json:"round"`
	Head      string      `json:"head"`
	Mode      string      `json:"mode"`
	Reviewers []string    `json:"reviewers"`
	Reviews   []ReviewOut `json:"reviews"`
	Verdict   struct {
		Blocker   int `json:"blocker"`
		ShouldFix int `json:"should_fix"`
	} `json:"verdict"`
	Findings []Finding `json:"findings"`
	Clean    bool      `json:"clean"`
	Approved bool      `json:"approved"`
	Stop     *string   `json:"stop"`
}

type notOpenError struct{ state string }

func (e notOpenError) Error() string { return "PR is " + e.state }

// evaluate reads the PR's reviews and comments and evaluates them against the state file.
func (r *runner) evaluate(ctx context.Context, k Key, d *Doc) (PRInfo, RoundResult, error) {
	info, err := viewPR(ctx, r.gh, k)
	if err != nil {
		return info, RoundResult{}, err
	}
	if info.State != "OPEN" {
		return info, RoundResult{}, notOpenError{info.State}
	}
	base := "repos/" + k.Slug()
	reviews, err := pages[Review](ctx, r.gh, base+"/pulls/"+itoa(k.N)+"/reviews")
	if err != nil {
		return info, RoundResult{}, err
	}
	comments, err := pages[Comment](ctx, r.gh, base+"/pulls/"+itoa(k.N)+"/comments")
	if err != nil {
		return info, RoundResult{}, err
	}
	issue, err := pages[Comment](ctx, r.gh, base+"/issues/"+itoa(k.N)+"/comments")
	if err != nil {
		return info, RoundResult{}, err
	}
	last := firstNonEmpty(d.Get("last-seen"), d.Get("poll-since"), d.Get("started"), d.Get("updated"), stamp(r.now()))
	in := RoundInput{
		Last: last, Head: info.Head, Author: info.Author,
		Set: splitList(d.Get("reviewers")), Known: LoadChannels(r.h).KnownBots,
		Unlogged: splitList(d.Get("unlogged")), Learned: d.All("learned"), Seen: d.Findings(),
		Reviews: reviews, Comments: comments, Issue: issue,
	}
	return info, Evaluate(in), nil
}

func (r *runner) wait(ctx context.Context, args []string) int {
	p, err := parseArgs(args, []string{"--timeout"}, []string{"--once", "--last"})
	if err != nil {
		return r.usage("wait: %v", err)
	}
	if len(p.pos) != 1 {
		return r.usage("wait: expected one <pr> argument")
	}
	k, _, err := r.resolveRef(ctx, p.pos[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	d, code := r.needState(k)
	if d == nil {
		return code
	}
	if p.has["--last"] {
		b, err := os.ReadFile(r.files.LastPath(k))
		if err != nil {
			return r.die(cli.ExitUsage, "no previous round recorded")
		}
		_, _ = r.env.Stdout.Write(b)
		return 0
	}
	if c := r.guardActive(d); c != 0 {
		return c
	}
	lim := r.limits()
	rounds := d.Rounds()
	if rounds >= lim.MaxRounds {
		return r.rail(ctx, k, ExitRoundCap, "round cap: %d rounds recorded (max %d)", rounds, lim.MaxRounds)
	}
	maxWait := lim.MaxWait
	if p.has["--timeout"] {
		n := atoi(strings.TrimSpace(p.flags["--timeout"]))
		if n < 0 || !reDigits.MatchString(strings.TrimSpace(p.flags["--timeout"])) {
			return r.usage("--timeout must be a number of seconds")
		}
		maxWait = n
	}
	once := p.has["--once"]
	deadline := r.now().Add(time.Duration(maxWait) * time.Second)
	var res RoundResult
	var info PRInfo
	for {
		cur, _ := r.files.Read(k)
		if cur == nil {
			cur = d
		}
		var err error
		info, res, err = r.evaluate(ctx, k, cur)
		var no notOpenError
		switch {
		case errors.As(err, &no):
			return r.die(ExitNotOpen, "%s", err)
		case err != nil:
			if ctx.Err() != nil {
				return r.die(ExitExternal, "interrupted")
			}
			return r.die(ExitExternal, "could not read PR reviews from GitHub: %v", err)
		}
		if len(res.ThirdParty) > 0 {
			return r.rail(ctx, k, ExitThirdParty, "third-party human comment from: %s (add to known_bots if it is automation)", strings.Join(res.ThirdParty, ", "))
		}
		if res.Landed {
			break
		}
		if once {
			return r.nothingYet(ctx, k, cur, lim.MaxIdle)
		}
		if !r.now().Before(deadline) {
			idle := 0
			_ = r.files.Update(k, r.now(), func(d *Doc) error {
				idle = atoi(d.Get("idle-waits")) + 1
				d.Set("idle-waits", itoa(idle))
				return nil
			})
			if idle >= lim.MaxIdle {
				return r.rail(ctx, k, ExitSilent, "reviewer silent for %d waits of %ds", idle, maxWait)
			}
			r.printJSON(map[string]any{"reason": "timeout"})
			return ExitTimeout
		}
		if err := r.sleep(ctx, time.Duration(lim.Poll)*time.Second); err != nil {
			return r.die(ExitExternal, "interrupted")
		}
	}

	prURL := k.URL()
	mode := GrindMode(r.h, r.st, prURL)
	out := RoundOut{Head: info.Head, Mode: mode, Reviews: res.Reviews, Findings: res.Findings, Clean: res.Clean, Approved: res.Approved}
	out.Verdict.Blocker, out.Verdict.ShouldFix = res.Blocker, res.ShouldFix
	out.Reviewers = []string{}
	seenL := map[string]bool{}
	for _, rv := range res.Reviews {
		if !seenL[lc(rv.Reviewer)] {
			seenL[lc(rv.Reviewer)] = true
			out.Reviewers = append(out.Reviewers, rv.Reviewer)
		}
	}
	if out.Findings == nil {
		out.Findings = []Finding{}
	}
	if out.Reviews == nil {
		out.Reviews = []ReviewOut{}
	}
	stop := ""
	switch {
	case res.Approved:
		stop = "approved"
	case mode == "deep" && res.Clean:
		stop = "clean"
	}
	if stop != "" {
		out.Stop = &stop
	}
	now := r.now()
	err = r.files.Update(k, now, func(d *Doc) error {
		out.Round = d.Rounds() + 1
		for _, pr := range res.Learned {
			d.Add("learned", pr.SlackID+"="+pr.Login)
			addList(d, "reviewers", pr.Login)
		}
		for _, l := range res.LearnedAny {
			addList(d, "reviewers", l)
		}
		if len(res.Learned) > 0 || len(res.LearnedAny) > 0 {
			refreshReviewer(d)
		}
		d.Set("last-seen", res.SubmittedAt)
		d.Set("idle-waits", "0")
		d.Append("", fmt.Sprintf("## Round %d - %s", out.Round, stamp(now)))
		for _, rv := range res.Reviews {
			d.Append(fmt.Sprintf("- review: %d %s %s %s blocker=%d should-fix=%d", rv.ID, rv.Reviewer, rv.State, rv.SubmittedAt, rv.Blocker, rv.ShouldFix))
		}
		for _, f := range res.Findings {
			d.Append("- finding: " + oneLine(f.FP))
		}
		return nil
	})
	if err != nil {
		return r.die(ExitExternal, "cannot record the round: %v", err)
	}
	if b, err := gh.PyJSON(out); err == nil {
		_ = home.AtomicWrite(r.files.LastPath(k), append(b, '\n'), 0o600)
	}
	r.printJSON(out)
	var stuck []string
	for _, f := range res.Findings {
		if f.Seen >= lim.Stuck {
			stuck = append(stuck, f.FP)
		}
	}
	if len(stuck) > 0 {
		return r.rail(ctx, k, ExitStuck, "stuck: finding seen %d times already: %s", lim.Stuck, strings.Join(stuck, "; "))
	}
	if stop != "" {
		return ExitStop
	}
	return 0
}

// nothingYet is the `--once` outcome when no round landed: schedule the next heartbeat poll and
// count a silent wake. Only a wake that came because next-poll was due counts as silence, so a
// session started by a CI change does not shorten the reviewer's patience.
func (r *runner) nothingYet(ctx context.Context, k Key, d *Doc, maxIdle int) int {
	now := r.now()
	due := false
	if np, ok := ParseTime(d.Get("next-poll")); ok && !np.After(now) {
		due = true
	}
	next := now.Add(Heartbeat)
	idle := atoi(d.Get("idle-waits"))
	err := r.files.Update(k, now, func(d *Doc) error {
		if due {
			idle = atoi(d.Get("idle-waits")) + 1
			d.Set("idle-waits", itoa(idle))
		}
		d.Set("next-poll", stamp(next))
		return nil
	})
	if err != nil {
		r.warn("cannot write next-poll: %v", err)
	}
	if due && idle >= maxIdle {
		return r.rail(ctx, k, ExitSilent, "reviewer silent for %d waits of %ds", idle, int(Heartbeat/time.Second))
	}
	r.printJSON(map[string]any{"reason": "nothing yet", "next_poll": stamp(next)})
	return ExitTimeout
}

// ---------- ci ----------

func (r *runner) ciVerb(ctx context.Context, args []string) int {
	p, err := parseArgs(args, []string{"--timeout"}, []string{"--watch"})
	if err != nil {
		return r.usage("ci: %v", err)
	}
	if len(p.pos) != 1 {
		return r.usage("ci: expected one <pr> argument")
	}
	k, _, err := r.resolveRef(ctx, p.pos[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	lim := r.limits()
	timeout := lim.CITimeout
	if p.has["--timeout"] {
		if !reDigits.MatchString(strings.TrimSpace(p.flags["--timeout"])) {
			return r.usage("--timeout must be a number of seconds")
		}
		timeout = atoi(strings.TrimSpace(p.flags["--timeout"]))
	}
	pr := gh.PRRef{Owner: k.Owner, Repo: k.Repo, N: k.N}
	res := gh.CISnapshot(ctx, r.gh, pr)
	if p.has["--watch"] {
		deadline := r.now().Add(time.Duration(timeout) * time.Second)
		for (res.State == gh.CIPending || res.State == gh.CIError) && r.now().Before(deadline) {
			if err := r.sleep(ctx, time.Duration(lim.CIPoll)*time.Second); err != nil {
				break
			}
			res = gh.CISnapshot(ctx, r.gh, pr)
		}
		if res.State == gh.CIPending || res.State == gh.CIError {
			res.Note = fmt.Sprintf("wall-clock cap of %ds expired with checks still %s", timeout, res.State)
		}
	}
	res = gh.ExpandFailing(ctx, r.gh, pr, res)
	attempted := false
	if d, err := r.files.Read(k); err == nil && res.HeadSHA != "" {
		attempted = d.HasPrefix("ci-attempt: " + res.HeadSHA + " ")
	}
	b, _ := json.Marshal(res)
	b = append(b[:len(b)-1], []byte(fmt.Sprintf(`,"ci_attempted":%t}`, attempted))...)
	out, _ := gh.PyJSON(json.RawMessage(b))
	_, _ = r.env.Stdout.Write(append(out, '\n'))
	switch res.State {
	case gh.CIGreen:
		return ExitOK
	case gh.CIRed:
		return ExitRed
	case gh.CIPending:
		return ExitPending
	case gh.CIConflict:
		return ExitConflict
	}
	return ExitCIError
}

// ---------- threads ----------

func (r *runner) threadsVerb(ctx context.Context, args []string) int {
	if len(args) > 0 && args[0] != "list" && args[0] != "resolve" {
		args = append([]string{"list"}, args...)
	}
	for _, c := range gh.CommandsWith(r.gh) {
		if c.Name == "threads" {
			return c.Run(ctx, r.env, args)
		}
	}
	return ExitExternal
}

// ---------- retrigger ----------

func (r *runner) retrigger(ctx context.Context, args []string) int {
	p, err := parseArgs(args, nil, nil)
	if err != nil || len(p.pos) != 1 {
		return r.usage("retrigger: expected one <pr> argument")
	}
	k, _, err := r.resolveRef(ctx, p.pos[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	d, code := r.needState(k)
	if d == nil {
		return code
	}
	if c := r.guardActive(d); c != 0 {
		return c
	}
	if q := d.Get("queued-push"); q != "" {
		return r.die(ExitQueuedRetry, "queued-push is set: %s; push when CI is green first", q)
	}
	ci := gh.CISnapshot(ctx, r.gh, gh.PRRef{Owner: k.Owner, Repo: k.Repo, N: k.N})
	if ci.State != gh.CIGreen {
		return r.die(ExitNotGreen, "CI is %s at %s; never retrigger on a non-green head", ci.State, firstNonEmpty(ci.HeadSHA, "?"))
	}
	info, err := viewPR(ctx, r.gh, k)
	if err != nil {
		return r.die(ExitExternal, "cannot read %s: %v", k.URL(), err)
	}
	if info.State != "OPEN" {
		return r.die(ExitNotOpen, "PR is %s", info.State)
	}
	rv, _ := ResolvePR(r.h, r.st, k.URL(), false)
	posted, url := "", ""
	var newLogins, newUnlogged, usedIDs []string
	var kept string
	var failedLines []string
	thread := d.Get("thread")
	now := r.now()

	if !threadRE.MatchString(thread) { // GitHub path
		var logins []string
		if pin := d.Get("pinned"); pin != "" {
			logins = []string{pin}
		} else if rv.Skip == nil {
			logins = without(rv.Logins, info.Author)
		}
		if len(logins) == 0 {
			logins = splitList(d.Get("reviewers-last"))
			kept = "no active reviewer"
			if rv.Skip != nil {
				kept = "resolver skip: " + *rv.Skip
			}
		}
		ok, failed := requestReviewers(ctx, r.gh, k, logins)
		failedLines = failed
		if len(ok) == 0 && kept == "" {
			if last := splitList(d.Get("reviewers-last")); len(last) > 0 {
				ok, _ = requestReviewers(ctx, r.gh, k, last)
				kept = "all requests failed"
			}
		}
		if len(ok) == 0 {
			return r.die(ExitExternal, "could not request any reviewer: %s", strings.Join(failed, "; "))
		}
		posted, usedIDs, newLogins = "github", ok, ok
	} else { // Slack path
		ch := LoadChannels(r.h)
		var ids []string
		if rv.Skip == nil && len(rv.Mentions) > 0 {
			ids, newLogins, newUnlogged = rv.Mentions, without(rv.Logins, info.Author), rv.Unlogged
		} else if last := splitList(d.Get("reviewers-last")); len(last) > 0 {
			ids = last
			kept = "no active reviewer"
			if rv.Skip != nil {
				kept = "resolver skip: " + *rv.Skip
			}
		} else if d.Get("reviewer") == "UNRESOLVED" && ch.BotUID != "" {
			ids, newUnlogged = []string{ch.BotUID}, []string{ch.BotUID} // a pre-upgrade grind mentioned the bot
		}
		if len(ids) == 0 {
			return r.die(ExitExternal, "no reviewer set to ask; pause and report")
		}
		channel := firstNonEmpty(d.Get("channel"), ThreadChannel(thread))
		text := ch.Fill(firstNonEmpty(ch.Retrigger, defaultRetrigger), ids, k.URL())
		if _, _, err := r.slack.Send(ctx, channel, text, ThreadTS(thread)); err != nil {
			return r.die(ExitExternal, "slack post failed: %v", err)
		}
		posted, usedIDs, url = "slack", ids, thread
	}
	err = r.files.Update(k, now, func(d *Doc) error {
		d.Set("reviewers-last", strings.Join(usedIDs, ","))
		addList(d, "reviewers", newLogins...)
		if posted == "slack" {
			addList(d, "unlogged", newUnlogged...)
		}
		refreshReviewer(d)
		if kept != "" {
			d.Add("reviewers-kept", kept)
		}
		for _, f := range failedLines {
			d.Add("request-failed", f)
		}
		d.Set("last-retrigger", stamp(now)+" head="+ci.HeadSHA)
		d.Append(fmt.Sprintf("- retrigger: %s head=%s via %s", stamp(now), ci.HeadSHA, posted))
		if r.headless { // the setu timer re-enters on next-poll, a new review or a CI change
			d.Set("next-poll", stamp(now.Add(Heartbeat)))
		}
		return nil
	})
	if err != nil {
		r.warn("could not record the retrigger: %v", err)
	}
	out := map[string]any{"posted": posted}
	if url != "" {
		out["url"] = url
	}
	r.printJSON(out)
	return 0
}

// ---------- record ----------

func (r *runner) record(ctx context.Context, args []string) int {
	if len(args) < 2 {
		return r.usage("record: usage: record <pr> <kind> ...")
	}
	k, _, err := r.resolveRef(ctx, args[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	d, code := r.needState(k)
	if d == nil {
		return code
	}
	kind, rest := args[1], args[2:]
	now := r.now()
	text := func(from int) string { return oneLine(strings.Join(rest[from:], " ")) }
	var apply func(d *Doc) error
	switch kind {
	case "fixed":
		if len(rest) < 2 {
			return r.usage("record fixed <id> <sha> [note]")
		}
		apply = func(d *Doc) error {
			d.Append(strings.TrimRight(fmt.Sprintf("- fixed: %s %s %s", rest[0], rest[1], text(2)), " "))
			return nil
		}
	case "rebutted":
		if len(rest) < 1 {
			return r.usage("record rebutted <id> [note]")
		}
		apply = func(d *Doc) error {
			d.Append(strings.TrimRight(fmt.Sprintf("- rebutted: %s %s", rest[0], text(1)), " "))
			return nil
		}
	case "note", "jev-ci-hint", "jev-finding-hint":
		if len(rest) < 1 {
			return r.usage("record %s <text>", kind)
		}
		apply = func(d *Doc) error { d.Append(fmt.Sprintf("- %s: %s", kind, text(0))); return nil }
	case "ci-attempt":
		if len(rest) != 2 {
			return r.usage("record ci-attempt <sha> <started|outcome>")
		}
		sha, outcome := rest[0], oneLine(rest[1])
		apply = func(d *Doc) error {
			prefix := "ci-attempt: " + sha + " "
			if d.HasPrefix(prefix) {
				if outcome == "started" {
					return errAttemptExists
				}
				d.DelPrefix(prefix)
			}
			d.Add("ci-attempt", sha+" - "+outcome)
			return nil
		}
	case "queued":
		var shas []string
		then := ""
		for i := 0; i < len(rest); i++ {
			if rest[i] == "--then" && i+1 < len(rest) {
				then = rest[i+1]
				i++
				continue
			}
			if strings.HasPrefix(rest[i], "--then=") {
				then = strings.TrimPrefix(rest[i], "--then=")
				continue
			}
			shas = append(shas, rest[i])
		}
		if then != "retrigger" && then != "close" {
			return r.usage("record queued <sha>... --then retrigger|close")
		}
		if len(shas) == 0 {
			return r.usage("record queued needs at least one sha")
		}
		apply = func(d *Doc) error {
			d.Set("queued-push", fmt.Sprintf("%s - round %d - then %s", strings.Join(shas, " "), d.Rounds(), then))
			return nil
		}
	case "unqueue":
		apply = func(d *Doc) error { d.Del("queued-push"); return nil }
	default:
		return r.usage("unknown record kind: %s", kind)
	}
	if err := r.files.Update(k, now, apply); err != nil {
		if errors.Is(err, errAttemptExists) {
			return r.die(ExitAttempt, "CI fix attempt already recorded for %s; pause instead", rest[0])
		}
		return r.die(ExitExternal, "cannot write the state: %v", err)
	}
	return 0
}

var errAttemptExists = errors.New("ci attempt exists")

// ---------- pause / done ----------

func splitReason(args []string) (reason string, post bool, err error) {
	post = true
	var words []string
	for _, a := range args {
		if a == "--no-post" {
			post = false
			continue
		}
		words = append(words, a)
	}
	reason = oneLine(strings.Join(words, " "))
	if reason == "" {
		err = errors.New("a reason is required")
	}
	return
}

func (r *runner) pauseVerb(ctx context.Context, args []string) int {
	if len(args) < 1 {
		return r.usage("pause: usage: pause <pr> <reason...> [--no-post]")
	}
	k, _, err := r.resolveRef(ctx, args[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	reason, post, err := splitReason(args[1:])
	if err != nil {
		return r.usage("pause: %v", err)
	}
	if d, code := r.needState(k); d == nil {
		return code
	}
	if err := r.doPause(ctx, k, reason, post); err != nil {
		return r.die(ExitExternal, "cannot write the state: %v", err)
	}
	return 0
}

func (r *runner) doneVerb(ctx context.Context, args []string) int {
	if len(args) < 1 {
		return r.usage("done: usage: done <pr> <reason...> [--no-post]")
	}
	k, _, err := r.resolveRef(ctx, args[0], true)
	if err != nil {
		return r.usage("%v", err)
	}
	reason, post, err := splitReason(args[1:])
	if err != nil {
		return r.usage("done: %v", err)
	}
	if d, code := r.needState(k); d == nil {
		return code
	}
	var snap *Doc
	err = r.files.Update(k, r.now(), func(d *Doc) error {
		if q := d.Get("queued-push"); q != "" {
			return queuedError{q}
		}
		d.Set("done", stamp(r.now())+" - "+reason)
		d.Del("paused")
		d.Del("next-poll")
		snap = parseDoc(d.bytes())
		return nil
	})
	var qe queuedError
	if errors.As(err, &qe) {
		return r.die(ExitQueuedDone, "queued-push is set: %s; push or drop it before closing", qe.v)
	}
	if err != nil {
		return r.die(ExitExternal, "cannot write the state: %v", err)
	}
	if post {
		r.post(ctx, snap, fmt.Sprintf("grind done: %s (round %d). %s - ready for human merge, merging stays manual.", reason, snap.Rounds(), k.URL()))
	}
	return 0
}

type queuedError struct{ v string }

func (e queuedError) Error() string { return "queued-push is set" }

// ---------- status / mode / reviewers ----------

func (r *runner) statusVerb(ctx context.Context, args []string) int {
	p, err := parseArgs(args, nil, []string{"--json"})
	if err != nil || len(p.pos) != 1 {
		return r.usage("status: usage: status <pr> [--json]")
	}
	k, _, err := r.resolveRef(ctx, p.pos[0], false)
	if err != nil {
		return r.usage("%v", err)
	}
	st, _ := ReadStatus(r.files, k, settingsMode(r.st))
	if p.has["--json"] {
		r.printJSON(st)
		return 0
	}
	line := fmt.Sprintf("%s #%d: %s, %d rounds", st.Repo, st.PR, st.State, st.Rounds)
	if st.Mode != nil {
		line += ", mode " + *st.Mode
	}
	if st.Reason != nil {
		line += ", " + *st.Reason
	}
	fmt.Fprintln(r.env.Stdout, line)
	return 0
}

func (r *runner) modeVerb(_ context.Context, args []string) int {
	p, err := parseArgs(args, []string{"--pr"}, nil)
	if err != nil || len(p.pos) != 0 {
		return r.usage("mode: usage: mode [--pr URL]")
	}
	fmt.Fprintln(r.env.Stdout, GrindMode(r.h, r.st, p.flags["--pr"]))
	return 0
}

func (r *runner) reviewersVerb(_ context.Context, args []string) int {
	p, err := parseArgs(args, []string{"--pr"}, []string{"--strict"})
	if err != nil || len(p.pos) != 0 || !p.has["--pr"] {
		return r.usage("reviewers: usage: reviewers --pr URL [--strict]")
	}
	rv, err := ResolvePR(r.h, r.st, p.flags["--pr"], p.has["--strict"])
	if err != nil {
		r.printJSON(map[string]string{"error": err.Error()})
		return 1
	}
	r.printJSON(rv)
	return 0
}
