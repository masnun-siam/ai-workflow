package dispatch

import (
	"bufio"
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/poller"
)

// prCand is a PR candidate for a lane.
type prCand struct {
	N        int
	URL      string
	Draft    bool
	State    string
	CI       string
	Conflict bool
	SHA      string
	MergedAt string
}

func mergedBefore(c prCand, startedAt float64) bool {
	if c.MergedAt == "" {
		return false
	}
	t, err := time.Parse(time.RFC3339, c.MergedAt)
	return err == nil && epoch(t) < startedAt
}

// prOf is the lane's PR: the one it already has, else the open one, else a merged one.
func prOf(x *store.Lane, data poller.Data, issue *poller.Issue) *prCand {
	var prs []prCand
	if issue != nil {
		for _, p := range issue.PRs {
			prs = append(prs, prCand{p.N, p.URL, p.Draft, p.State, p.CI, p.Conflict, p.SHA, p.MergedAt})
		}
	} else { // closed issue: the merged list still names the PR that closed it
		for _, m := range data.Merged {
			for _, c := range m.Closes {
				if c == x.N {
					prs = append(prs, prCand{m.N, m.URL, false, "MERGED", "success", false, m.SHA, m.MergedAt})
				}
			}
		}
	}
	if x.PR != 0 {
		for i := range prs {
			if prs[i].N == x.PR {
				return &prs[i]
			}
		}
		return nil
	}
	if x.StartedAt != 0 { // a merged PR from before this lane started belongs to an earlier run of the issue
		kept := prs[:0:0]
		for _, p := range prs {
			if p.State != "MERGED" || !mergedBefore(p, x.StartedAt) {
				kept = append(kept, p)
			}
		}
		prs = kept
	}
	for i := range prs {
		if prs[i].State == "OPEN" {
			return &prs[i]
		}
	}
	for i := range prs {
		if prs[i].State == "MERGED" {
			return &prs[i]
		}
	}
	return nil
}

var (
	reGrindKV   = regexp.MustCompile(`^([A-Za-z][\w-]*): ?(.*)$`)
	reGrindDone = regexp.MustCompile(`^done: \d{4}-\d\d-\d\dT`)
)

// grindFact reads the pr-grind state file of a PR (pr-grind/<owner>-<repo>-<pr>.md): its header
// above the first "## " line, and a terminal `done:` line under a round.
func (s *Service) grindFact(repo string, pr int) *GrindFact {
	owner, name := splitSlug(repo)
	want := strings.ToLower(owner+"-"+name+"-"+strconv.Itoa(pr)) + ".md"
	dir := s.d.Home.Path("pr-grind")
	ents, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	for _, e := range ents {
		if e.IsDir() || strings.ToLower(e.Name()) != want {
			continue
		}
		f, err := os.Open(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil
		}
		defer f.Close()
		h := map[string]string{}
		inHeader := true
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 64<<10), 4<<20)
		for sc.Scan() {
			line := sc.Text()
			if strings.HasPrefix(line, "## ") {
				inHeader = false
			}
			if inHeader {
				if m := reGrindKV.FindStringSubmatch(line); m != nil {
					if _, ok := h[m[1]]; !ok {
						h[m[1]] = strings.TrimSpace(m[2])
					}
				}
			} else if reGrindDone.MatchString(line) {
				if _, ok := h["done"]; !ok {
					h["done"] = strings.TrimSpace(strings.TrimPrefix(line, "done:"))
				}
			}
		}
		if v, ok := h["done"]; ok {
			return &GrindFact{State: "done", Reason: v}
		}
		if v, ok := h["paused"]; ok {
			return &GrindFact{State: "paused", Reason: v}
		}
		return &GrindFact{State: "idle", Due: h["dispatch-due"]}
	}
	return nil
}

// issueClosed asks GitHub for the issue state: CLOSED is kept, OPEN for OpenRecheckSeconds.
func (s *Service) issueClosed(ctx context.Context, repo string, n int) bool {
	k := store.Key(repo, n)
	now := s.d.Now()
	s.mu.Lock()
	st := s.issueState[k]
	s.mu.Unlock()
	if st.state != "CLOSED" && (st.state == "" || now.Sub(st.at) >= OpenRecheckSeconds*time.Second) {
		r := s.d.GH.Run(ctx, []string{"issue", "view", strconv.Itoa(n), "-R", repo, "--json", "state", "-q", ".state"},
			execx.Opts{Timeout: 30 * time.Second})
		got := strings.TrimSpace(string(r.Stdout))
		if r.Code == 0 && (got == "OPEN" || got == "CLOSED") {
			st = issueState{got, now}
			s.mu.Lock()
			s.issueState[k] = st
			s.mu.Unlock()
		} else {
			msg := strings.TrimSpace(string(r.Stderr))
			if msg == "" {
				msg = got
			}
			if msg == "" {
				msg = "gh did not answer"
			}
			logf("state of %s: %s", k, trunc(msg, 200))
		}
	}
	return st.state == "CLOSED"
}

// laneFacts builds the facts of one lane, or false when its repo has no fresh snapshot, or when
// the snapshot's open-issue list was cut short and lacks the lane's issue while GitHub says it is
// open (past the cut) or does not answer. A closed issue past the cut is looked up on its own, so
// its lane can finish.
func (s *Service) laneFacts(ctx context.Context, x *store.Lane) (Facts, bool) {
	if s.d.Snapshots == nil {
		return Facts{}, false
	}
	snap := s.d.Snapshots.Snapshot(x.Repo)
	if !snap.Fresh() {
		return Facts{}, false
	}
	data := snap.Data
	var issue *poller.Issue
	for i := range data.Issues {
		if data.Issues[i].N == x.N {
			issue = &data.Issues[i]
			break
		}
	}
	if issue == nil && data.IssuesTruncated && !s.issueClosed(ctx, x.Repo, x.N) {
		k := x.Key()
		s.mu.Lock()
		warned := s.truncWarned[k]
		s.truncWarned[k] = true
		s.mu.Unlock()
		if !warned {
			logf("%s is not in the poller's truncated open-issue list and is open; the lane waits", k)
		}
		return Facts{}, false
	}
	f := Facts{IssueOpen: issue != nil}
	if issue != nil {
		for _, l := range issue.Labels {
			f.Refined = f.Refined || l == "refined"
		}
		for _, b := range issue.BlockedBy {
			if b.State == "OPEN" {
				repo := b.Repo
				if repo == "" {
					repo = x.Repo
				}
				f.BlockersOpen = append(f.BlockersOpen, store.Key(repo, b.N))
			}
		}
	}
	if s.d.Grind != nil {
		g := s.d.Grind(x.Repo)
		f.Slack, f.Channel = g.Path != "" && g.Skip == "", g.Channel
	}
	if s.d.Login != nil {
		owner, _ := splitSlug(x.Repo)
		if login := s.d.Login(ctx); login != "" && strings.EqualFold(owner, login) {
			f.Solo = true
		}
	}
	if p := prOf(x, data, issue); p != nil {
		pf := &PRFact{N: p.N, URL: p.URL, Draft: p.Draft, State: p.State, CI: p.CI, Conflict: p.Conflict, SHA: p.SHA}
		for _, o := range data.OpenPRs {
			if o.N == p.N {
				pf.Approved, pf.ChangesRequested, pf.ThreadsOpen = o.Approved, o.ChangesRequested, o.ThreadsOpen
				break
			}
		}
		f.PR = pf
		f.Grind = s.grindFact(x.Repo, p.N)
	}
	if x.Handle != nil {
		f.Agent = s.agentStatus(x.Handle)
	}
	return f, true
}
