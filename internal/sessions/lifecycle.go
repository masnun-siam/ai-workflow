package sessions

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
)

const continuePrompt = "Continue from where you were stopped."

var errNotClaimed = errors.New("not claimed")

// claim moves a record out of one of the from statuses under the flock; false when it lost.
func (m *Manager) claim(id string, from []Status, mutate func(*Record)) (Record, bool) {
	rec, err := m.Update(id, func(r *Record) error {
		ok := false
		for _, s := range from {
			ok = ok || r.Status == s
		}
		if !ok {
			return errNotClaimed
		}
		if mutate != nil {
			mutate(r)
		}
		return nil
	})
	return rec, err == nil
}

// ---- resume / answer ----

// resumeSpawn continues claude session rec.SessionID with text. rec is already claimed (starting).
func (m *Manager) resumeSpawn(ctx context.Context, rec Record, text string) (Record, error) {
	if rec.SessionID == "" {
		return rec, m.failRec(rec.ID, "cannot resume: session has no claude session_id")
	}
	path, err := m.recordCwd(ctx, rec)
	if err != nil {
		return rec, m.failRec(rec.ID, "cannot resume: "+err.Error())
	}
	exe, err := m.preflight(ctx, rec.ID, rec.ClaudeCmd)
	if err != nil {
		return m.mustGet(rec.ID), err
	}
	argv, err := m.resumeArgv(exe, rec, rec.SessionID, text)
	if err != nil {
		return m.mustGet(rec.ID), m.failRec(rec.ID, "cannot build the command: "+err.Error())
	}
	return m.spawn(ctx, rec.ID, argv, path, spawnOpts{answered: true, resuming: true, mutate: func(r *Record) {
		r.CwdPath = path
		r.EndedAt, r.Error, r.Note, r.PendingAnswer = "", "", "", text
		r.PendingQuestion, r.ResumedFresh, r.TerminalHandoff = nil, nil, nil
		r.Stalled, r.IdleBlocks = "", 0
	}})
}

func validPromptText(text string, limit int) error {
	switch {
	case strings.TrimSpace(text) == "":
		return errs.Invalid("text must be a non-empty string")
	case strings.HasPrefix(strings.TrimLeft(text, " \t\r\n"), "-"):
		return errs.Invalid("text must not start with '-' (claude would parse it as a flag)")
	case strings.ContainsRune(text, 0):
		return errs.Invalid("text must not contain NUL")
	case limit > 0 && len([]rune(text)) > limit:
		return errs.Invalid("text is longer than %d characters", limit)
	}
	return nil
}

// Resume delivers text to a session as the prompt of a new `claude --resume` process (away
// answers, panel verdicts). The session must have no live process.
func (m *Manager) Resume(ctx context.Context, id, text string) error {
	ctx = context.WithoutCancel(ctx)
	if err := validPromptText(text, 0); err != nil {
		return err
	}
	m.resumeMu.Lock()
	rec, err := m.Get(id)
	if err != nil {
		m.resumeMu.Unlock()
		return err
	}
	if m.Alive(id) {
		m.resumeMu.Unlock()
		return errs.Conflict("session process is still running", map[string]any{"id": id})
	}
	if rec.Status == StQueued || rec.Status == StLimited && rec.SessionID == "" {
		m.resumeMu.Unlock()
		return errs.Conflict("session has not started yet", map[string]any{"id": id})
	}
	rec, err = m.Update(id, func(r *Record) error {
		r.Status, r.PID, r.PidStarted = StStarting, 0, ""
		r.LimitResetsAt, r.LimitType, r.AutoResume = 0, "", nil
		return nil
	})
	m.resumeMu.Unlock()
	if err != nil {
		return err
	}
	_, err = m.resumeSpawn(ctx, rec, text)
	return err
}

// Answer validates and delivers the human's answer to the pending round (S§1.9 order).
func (m *Manager) Answer(ctx context.Context, id, roundID string, answers map[string]Answer) (Record, error) {
	ctx = context.WithoutCancel(ctx)
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	if rec.Status != StWaiting || rec.PendingQuestion == nil {
		return rec, errs.Conflict("session is not waiting for an answer", map[string]any{"id": id})
	}
	if m.Alive(id) {
		return rec, errs.Conflict("session process is still running", map[string]any{"id": id})
	}
	if rec.SessionID == "" {
		return rec, errs.Conflict("session has no claude session_id", map[string]any{"id": id})
	}
	if roundID == "" {
		return rec, errs.Invalid("round_id required")
	}
	if rec.PendingQuestion.ID != roundID {
		return rec, errs.Conflict("round_id is not the current pending round", map[string]any{"id": id})
	}
	text, err := AnswerText(*rec.PendingQuestion, answers)
	if err != nil {
		return rec, err
	}
	claimed, ok := m.ClaimAnswer(id, roundID)
	if !ok {
		return rec, errs.Conflict("round already answered", map[string]any{"id": id})
	}
	text = m.guardResumeText(rec, roundID, answers, text)
	cur := m.mustGet(id)
	out, err := m.resumeSpawn(ctx, cur, text)
	if err != nil {
		_ = m.RestoreRound(id, *claimed)
		return out, errs.WithStatus(500, err.Error())
	}
	return out, nil
}

// issueKey is the (repo, "<skill>:<number>") a start/resume guard compares; "" for other steps.
func (m *Manager) issueKey(r Record) string {
	step := m.stepOf(r)
	if step != "implement-issue" && step != "pr-grind" {
		return ""
	}
	n := 0
	if r.Link != nil && r.Link.Issue > 0 {
		n = r.Link.Issue
	} else {
		_, rest, ok := parseCommand(r.Command)
		if !ok {
			rest = r.Args
		}
		if mm := issueNumRe.FindStringSubmatch(strings.SplitN(rest, "\n", 2)[0]); mm != nil {
			fmt.Sscan(mm[1], &n)
		}
	}
	if n == 0 {
		return ""
	}
	return fmt.Sprintf("%s|%s:%d", strings.ToLower(m.slugOf(r)+"|"+r.Repo), step, n)
}

var issueNumRe = regexp.MustCompile(`(?:^|\s|/issues/|/pull/)#?(\d+)(?:\s|$)`)

func (m *Manager) liveForIssue(r Record) (string, bool) {
	key := m.issueKey(r)
	if key == "" {
		return "", false
	}
	for _, o := range m.listAll() {
		if o.ID != r.ID && (o.Status == StStarting || o.Status == StRunning || o.Status == StWaiting) && m.issueKey(o) == key {
			return o.ID, true
		}
	}
	return "", false
}

// SendPrompt sends text to a session: queued while it runs, resumed when it is finished.
func (m *Manager) SendPrompt(ctx context.Context, id, text string, limit int) (string, error) {
	ctx = context.WithoutCancel(ctx)
	if limit <= 0 {
		limit = 4000
	}
	if err := validPromptText(text, limit); err != nil {
		return "", err
	}
	m.resumeMu.Lock()
	rec, err := m.Get(id)
	if err != nil {
		m.resumeMu.Unlock()
		return "", err
	}
	switch rec.Status {
	case StWaiting:
		m.resumeMu.Unlock()
		return "", errs.Conflict("answer the pending question first", map[string]any{"id": id})
	case StStarting, StRunning, StLimited, StQueued:
		_, err := m.Update(id, func(r *Record) error { r.QueuedPrompt = text; return nil })
		m.resumeMu.Unlock()
		return "queued", err
	}
	if rec.SessionID == "" {
		m.resumeMu.Unlock()
		return "", errs.Conflict("session has no claude session_id", map[string]any{"id": id})
	}
	if other, live := m.liveForIssue(rec); live {
		m.resumeMu.Unlock()
		return "", errs.Conflict(fmt.Sprintf("session %s is already live for this issue", other), map[string]any{"id": other})
	}
	claimed, ok := m.claim(id, []Status{StDone, StFailed, StStopped}, func(r *Record) {
		r.Status, r.PID, r.PidStarted, r.QueuedPrompt = StStarting, 0, "", ""
	})
	m.resumeMu.Unlock()
	if !ok {
		return "", errs.Conflict("session changed state, retry", map[string]any{"id": id})
	}
	if _, err := m.resumeSpawn(ctx, claimed, text); err != nil {
		return "", err
	}
	return "sent", nil
}

// deliverQueued sends a stored prompt once the session is finished and not held.
func (m *Manager) deliverQueued(id string) {
	rec, err := m.Get(id)
	if err != nil || rec.QueuedPrompt == "" || rec.Hold || (rec.Status != StDone && rec.Status != StFailed) {
		return
	}
	text := rec.QueuedPrompt
	if _, err := m.SendPrompt(context.Background(), id, text, 32000); err != nil {
		drop := errs.KindOf(err) == errs.KInvalid
		_, _ = m.Update(id, func(r *Record) error {
			if drop {
				r.QueuedPrompt = ""
			}
			r.Note = "queued prompt not sent: " + err.Error()
			return nil
		})
	}
}

// ---- stop, hold, limits ----

func groupGone(pgid int, p *proc) bool {
	err := syscall.Kill(-pgid, 0)
	return err == syscall.ESRCH || err == syscall.EPERM
}

// Stop ends a session. A live process group gets SIGTERM, then SIGKILL after the grace.
func (m *Manager) Stop(ctx context.Context, id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	m.mu.Lock()
	p, tracked := m.procs[id]
	m.mu.Unlock()
	switch rec.Status {
	case StLimited:
		return m.Update(id, func(r *Record) error {
			r.Status, r.EndedAt = StStopped, isoNow(m.d.now())
			f := false
			r.AutoResume = &f
			return nil
		})
	case StQueued:
		return m.Update(id, func(r *Record) error { r.Status, r.EndedAt, r.Note = StStopped, isoNow(m.d.now()), ""; return nil })
	}
	reattached := !(tracked && p != nil && p.cmd != nil) && rec.PID > 0 && rec.PidStarted != ""
	if reattached {
		cur, failed := psStart(ctx, rec.PID)
		reattached = !failed && cur == rec.PidStarted
	}
	childGone := !tracked || p == nil || (p.cmd != nil && p.exited())
	if rec.Status == StWaiting && !reattached && childGone {
		return m.Update(id, func(r *Record) error {
			r.Status, r.EndedAt, r.PendingQuestion = StStopped, isoNow(m.d.now()), nil
			return nil
		})
	}
	if (rec.Status != StStarting && rec.Status != StRunning && rec.Status != StWaiting) || rec.PID == 0 {
		return rec, nil
	}
	if tracked && p != nil && p.cmd != nil && p.exited() {
		return rec, nil // already exited: the follower records done or failed
	}
	m.mu.Lock()
	m.stopping[id] = true
	m.mu.Unlock()
	pgid := rec.PID
	_ = syscall.Kill(-pgid, syscall.SIGTERM)
	wait := func(d time.Duration) bool {
		end := time.Now().Add(d)
		for !groupGone(pgid, p) && time.Now().Before(end) {
			time.Sleep(50 * time.Millisecond)
		}
		return groupGone(pgid, p)
	}
	if !wait(m.stopGrace) {
		_ = syscall.Kill(-pgid, syscall.SIGKILL)
		wait(2 * time.Second)
	}
	out, err := m.Update(id, func(r *Record) error {
		r.Status, r.EndedAt, r.PendingQuestion = StStopped, isoNow(m.d.now()), nil
		return nil
	})
	m.releaseBatch(out.Batch)
	m.mu.Lock()
	if _, ok := m.procs[id]; !ok {
		delete(m.stopping, id)
	}
	m.mu.Unlock()
	return out, err
}

// Hold lets the current run finish, then nothing continues the session until Release.
func (m *Manager) Hold(id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	switch rec.Status {
	case StStarting, StRunning, StWaiting, StLimited:
	default:
		return rec, errs.Conflict("session is not running", map[string]any{"id": id})
	}
	return m.Update(id, func(r *Record) error { r.Hold = true; return nil })
}

func (m *Manager) Release(id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	if !rec.Hold {
		return rec, errs.Conflict("session is not held", map[string]any{"id": id})
	}
	if _, err := m.Update(id, func(r *Record) error { r.Hold = false; return nil }); err != nil {
		return rec, err
	}
	m.deliverQueued(id)
	return m.Get(id)
}

func (m *Manager) CancelAuto(id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	if rec.Status != StLimited {
		return rec, errs.Conflict("session is not limited", map[string]any{"id": id})
	}
	return m.Update(id, func(r *Record) error { f := false; r.AutoResume = &f; return nil })
}

func (m *Manager) Dismiss(id string) (Record, error) {
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	if rec.Status != StFailed {
		return rec, errs.Conflict("only a failed session can be dismissed", map[string]any{"id": id})
	}
	return m.Update(id, func(r *Record) error { r.Dismissed = true; return nil })
}

// StartNow starts a queued session ahead of its batch turn.
func (m *Manager) StartNow(ctx context.Context, id string) (Record, error) {
	ctx = context.WithoutCancel(ctx)
	rec, err := m.Get(id)
	if err != nil {
		return rec, err
	}
	if rec.Status == StLimited && rec.SessionID == "" {
		return rec, errs.Conflict("this account is rate limited: the session starts by itself when the limit resets", map[string]any{"id": id})
	}
	claimed, ok := m.claim(id, []Status{StQueued}, func(r *Record) { r.Status, r.Note = StStarting, "" })
	if !ok {
		return rec, errs.Conflict("session is not queued", map[string]any{"id": id})
	}
	return m.startFresh(ctx, claimed, nil)
}

// ResumeStopped continues a stopped, limited or failed session (S§1.12). accountLabel rebinds it.
func (m *Manager) ResumeStopped(ctx context.Context, id, accountLabel string) (Record, error) {
	ctx = context.WithoutCancel(ctx)
	m.resumeMu.Lock()
	rec, err := m.Get(id)
	if err != nil {
		m.resumeMu.Unlock()
		return rec, err
	}
	if (rec.Status != StStopped && rec.Status != StLimited && rec.Status != StFailed) || m.Alive(id) {
		m.resumeMu.Unlock()
		return rec, errs.Conflict("session is not stopped, limited or failed", map[string]any{"id": id})
	}
	if other, live := m.liveForIssue(rec); live {
		m.resumeMu.Unlock()
		return rec, errs.Conflict(fmt.Sprintf("session %s is already live for this issue", other), map[string]any{"id": other})
	}
	newCmd := rec.ClaudeCmd
	if accountLabel != "" {
		cmd, ok := "", false
		if m.d.Settings != nil {
			cmd, ok = m.d.Settings.AccountCmd(accountLabel)
		}
		if !ok {
			m.resumeMu.Unlock()
			return rec, errs.Invalid("account must be a label saved in Settings")
		}
		newCmd = cmd
	}
	path, perr := m.recordCwd(ctx, rec)
	if newCmd != rec.ClaudeCmd && rec.SessionID != "" && perr == nil && m.d.Claude != nil {
		if err := m.d.Claude.CopyTranscript(rec.ClaudeCmd, newCmd, path, rec.SessionID); err != nil {
			m.resumeMu.Unlock()
			return rec, errs.Conflict(err.Error(), map[string]any{"id": id})
		}
	}
	wasLimited := rec.Status == StLimited
	prompt := continuePrompt
	if wasLimited && rec.PendingAnswer != "" {
		prompt = rec.PendingAnswer
	}
	claimed, ok := m.claim(id, []Status{StStopped, StLimited, StFailed}, func(r *Record) {
		r.Status, r.PID, r.PidStarted = StStarting, 0, ""
		r.LimitResetsAt, r.LimitType, r.AutoResume = 0, "", nil
		r.ClaudeCmd = newCmd
	})
	m.resumeMu.Unlock()
	if !ok {
		return rec, errs.Conflict("session is not stopped, limited or failed", map[string]any{"id": id})
	}
	m.mu.Lock()
	delete(m.stopping, id)
	m.mu.Unlock()
	if perr != nil {
		return claimed, m.failRec(id, "cannot resume: "+perr.Error())
	}
	if claimed.SessionID == "" {
		if wasLimited { // limited before claude ever reported a session: start over
			return m.startFresh(ctx, claimed, func(r *Record) { r.EndedAt, r.Error = "", "" })
		}
		return claimed, m.failRec(id, "cannot resume: session has no claude session_id")
	}
	return m.resumeSpawn(ctx, claimed, prompt)
}

// limitTick starts queued batch sessions with a free slot and resumes limited sessions whose
// limit has reset (5 s buffer, 2 s stagger).
func (m *Manager) limitTick(ctx context.Context) {
	batches := map[string]bool{}
	for _, r := range m.listAll() {
		if r.Status == StQueued && r.Batch != "" {
			batches[r.Batch] = true
		}
	}
	for b := range batches {
		m.releaseBatch(b)
	}
	now := m.d.now()
	for _, r := range m.listAll() {
		if ctx.Err() != nil {
			return
		}
		if r.Role == "away-answerer" || r.Hold || r.Status != StLimited || r.AutoResume == nil || !*r.AutoResume || r.LimitResetsAt == 0 {
			continue
		}
		if time.Unix(r.LimitResetsAt, 0).Add(limitBuffer).After(now) {
			continue
		}
		if _, err := m.ResumeStopped(ctx, r.ID, ""); err != nil {
			logf("sessions: limit auto-resume of %s failed: %v", r.ID, err)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(m.stagger):
		}
	}
}

// releaseBatch starts a batch's queued sessions, oldest first, while fewer than its max run.
func (m *Manager) releaseBatch(batch string) {
	if batch == "" {
		return
	}
	var started []Record
	m.batchMu.Lock()
	var mine []Record
	maxN, busy := 1, 0
	for _, r := range m.listAll() {
		if r.Batch != batch {
			continue
		}
		mine = append(mine, r)
		if r.BatchMax > maxN {
			maxN = r.BatchMax
		}
		if r.Status == StStarting || r.Status == StRunning {
			busy++
		}
	}
	free := maxN - busy
	var queued []Record
	for _, r := range mine {
		if r.Status == StQueued {
			queued = append(queued, r)
		}
	}
	sort.Slice(queued, func(i, j int) bool { return queued[i].StartedAt < queued[j].StartedAt })
	for _, r := range queued {
		if free <= 0 {
			break
		}
		if c, ok := m.claim(r.ID, []Status{StQueued}, func(x *Record) { x.Status, x.Note = StStarting, "" }); ok {
			free--
			started = append(started, c)
		}
	}
	m.batchMu.Unlock()
	for _, r := range started {
		rec := r
		go func() {
			if _, err := m.startFresh(context.Background(), rec, nil); err != nil {
				logf("sessions: batch %s: starting %s failed: %v", batch, rec.ID, err)
				if cur, e := m.Get(rec.ID); e == nil && cur.Status == StStarting {
					_, _ = m.Update(rec.ID, func(x *Record) error {
						x.Status, x.EndedAt, x.Error = StFailed, isoNow(m.d.now()), "could not start: "+err.Error()
						return nil
					})
				}
			}
		}()
	}
}
