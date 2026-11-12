package sessions

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
)

const (
	limitTickEvery = 30 * time.Second
	limitBuffer    = 5 * time.Second
	maxPartialLine = 64 << 20
)

// Timing defaults (per-Manager fields, so tests can shorten them).
const (
	defPoll         = 200 * time.Millisecond
	defAskedGrace   = 30 * time.Second
	defStopGrace    = 10 * time.Second
	defLimitStagger = 2 * time.Second
)

var limitRe = regexp.MustCompile(`(?i)usage limit|limit reached|rate.?limit|hit your limit`)

// proc is a claude process this server follows. cmd is nil for a re-attached or watched pid.
type proc struct {
	cmd  *exec.Cmd
	pid  int
	done chan struct{}
	rc   atomic.Int32
}

func (p *proc) exited() bool {
	if p.cmd == nil {
		return false
	}
	select {
	case <-p.done:
		return true
	default:
		return false
	}
}

// ---- starting ----

// resolveCwd turns a registered slug or an absolute directory into a directory.
func (m *Manager) resolveCwd(ctx context.Context, cwd string) (string, error) {
	if filepath.IsAbs(cwd) {
		if fi, err := os.Stat(cwd); err == nil && fi.IsDir() {
			return cwd, nil
		}
		return "", errs.Invalid("cwd is not a directory or known checkout slug: %q", cwd)
	}
	if m.d.Repos != nil {
		if p, _, err := m.d.Repos.Resolve(ctx, cwd); err == nil && p != "" {
			return p, nil
		}
	}
	return "", errs.Invalid("cwd is not a directory or known checkout slug: %q", cwd)
}

// Launch starts one headless session (S§1.2). It returns the record: running, or queued or
// limited when it could not start yet. Preflight and spawn failures leave a failed record and
// return errs.Upstream.
func (m *Manager) Launch(ctx context.Context, s Spec) (Record, error) {
	ctx = context.WithoutCancel(ctx)
	text, display := s.Prompt.Text, s.Prompt.Display
	if text == "" {
		text = display
	}
	if display == "" {
		display = text
	}
	if strings.TrimSpace(text) == "" {
		return Record{}, errs.Invalid("command_text must be a non-empty string")
	}
	if strings.HasPrefix(text, "-") {
		return Record{}, errs.Invalid("command_text must not start with '-' (claude would parse it as a flag)")
	}
	path, err := m.resolveCwd(ctx, s.Cwd)
	if err != nil {
		return Record{}, err
	}
	cmd := s.Cmd
	if cmd == "" && m.d.Settings != nil {
		cmd = m.d.Settings.DefaultCmd()
	}
	if cmd == "" {
		cmd = "claude"
	}
	rec := Record{
		Command: display, Repo: path, Link: s.Link, Status: StStarting, ClaudeCmd: cmd,
		Step: s.Prompt.Step, Args: s.Args, Kind: s.Kind, Agent: s.Agent, Gate: s.Gate,
		Instructions: s.Instructions, AllowedTools: s.AllowedTools, CwdPath: path,
		DirectModel: s.Model, DirectEffort: s.Effort, RunModel: s.RunModel, RunEffort: s.RunEffort,
	}
	if s.Request != nil {
		rec.Request, _ = json.Marshal(s.Request)
	}
	if err := rec.applyFields(s.Fields); err != nil {
		return Record{}, errs.Invalid("bad session fields: %v", err)
	}

	if s.Batch != "" {
		maxN := s.BatchMax
		if maxN < 1 {
			maxN = 1
		}
		m.batchMu.Lock()
		rec.Batch, rec.BatchMax = s.Batch, maxN
		busy := m.batchBusy(s.Batch) >= maxN
		if busy {
			rec.Status = StQueued
			rec.Note = fmt.Sprintf("queued: %d of this batch run at once", maxN)
		}
		rec, err = m.create(rec)
		m.batchMu.Unlock()
		if err != nil {
			return rec, err
		}
		if busy {
			return rec, nil
		}
	} else if rec, err = m.create(rec); err != nil {
		return rec, err
	}

	// the account is rate limited: queue; the limit tick starts it at reset. Starts with their own
	// instructions, env, fds, agent or direct model/effort skip the queue.
	if until := m.limitedUntil(cmd); until > 0 && len(s.Instructions) == 0 && len(s.Env) == 0 &&
		len(s.ExtraFiles) == 0 && s.Agent == "" && s.Model == "" && s.Effort == "" {
		return m.Update(rec.ID, func(r *Record) error {
			r.Status = StLimited
			r.LimitResetsAt = until
			t := true
			r.AutoResume = &t
			r.Note = "queued: account is rate limited"
			return nil
		})
	}
	exe, err := m.preflight(ctx, rec.ID, cmd)
	if err != nil {
		return m.mustGet(rec.ID), err
	}
	argv, err := m.startArgv(exe, rec, text)
	if err != nil {
		return m.mustGet(rec.ID), m.failRec(rec.ID, "cannot build the command: "+err.Error())
	}
	return m.spawn(ctx, rec.ID, argv, path, spawnOpts{env: s.Env, files: s.ExtraFiles, mutate: func(r *Record) {
		r.Command = display
		r.CwdPath = path
	}})
}

func (m *Manager) mustGet(id string) Record {
	r, _ := m.Get(id)
	return r
}

// failRec marks a session failed and returns the error to report (502).
func (m *Manager) failRec(id, msg string) error {
	_, _ = m.Update(id, func(r *Record) error {
		r.Status = StFailed
		r.Error = msg
		r.EndedAt = isoNow(m.d.now())
		return nil
	})
	return errs.Upstream("%s", msg)
}

// preflight is S§1.3: auth status must say logged in. It returns the account's argv.
func (m *Manager) preflight(ctx context.Context, id, cmd string) ([]string, error) {
	if m.d.Claude == nil {
		return nil, m.failRec(id, "claude CLI not found on PATH")
	}
	if err := m.d.Claude.Preflight(ctx, cmd, cmd == "claude"); err != nil {
		return nil, m.failRec(id, err.Error())
	}
	exe, err := m.d.Claude.Argv(cmd)
	if err != nil {
		return nil, m.failRec(id, err.Error())
	}
	return exe, nil
}

func (m *Manager) batchBusy(batch string) int {
	n := 0
	for _, r := range m.listAll() {
		if r.Batch == batch && (r.Status == StStarting || r.Status == StRunning) {
			n++
		}
	}
	return n
}

// restartPrompt is the text of a fresh (not resumed) start of a stored record.
func (m *Manager) restartPrompt(r Record) string {
	if r.Step != "" && m.d.Prompts != nil {
		if p, err := m.d.Prompts.Build(r.Step, r.Args); err == nil && p.Text != "" {
			return p.Text
		}
	}
	return r.Command
}

// startFresh spawns a claimed (status starting) record from its stored fields, no --resume.
func (m *Manager) startFresh(ctx context.Context, rec Record, mutate func(*Record)) (Record, error) {
	path, err := m.recordCwd(ctx, rec)
	if err != nil {
		return rec, m.failRec(rec.ID, "cannot start: "+err.Error())
	}
	exe, err := m.preflight(ctx, rec.ID, rec.ClaudeCmd)
	if err != nil {
		return m.mustGet(rec.ID), err
	}
	argv, err := m.startArgv(exe, rec, m.restartPrompt(rec))
	if err != nil {
		return m.mustGet(rec.ID), m.failRec(rec.ID, "cannot build the command: "+err.Error())
	}
	return m.spawn(ctx, rec.ID, argv, path, spawnOpts{mutate: func(r *Record) {
		r.CwdPath = path
		if mutate != nil {
			mutate(r)
		}
	}})
}

// recordCwd is the directory a stored record runs in.
func (m *Manager) recordCwd(ctx context.Context, rec Record) (string, error) {
	for _, c := range []string{rec.CwdPath, rec.Repo} {
		if c == "" {
			continue
		}
		if p, err := m.resolveCwd(ctx, c); err == nil {
			return p, nil
		}
	}
	return "", fmt.Errorf("cwd is not a directory: %q", rec.Repo)
}

// ---- spawning ----

type spawnOpts struct {
	answered bool // an answer or queued prompt is being delivered
	resuming bool
	env      []string
	files    []*os.File
	mutate   func(*Record)
}

func (m *Manager) childEnv(id string, extra []string) []string {
	var env []string
	for _, kv := range os.Environ() {
		k, _, _ := strings.Cut(kv, "=")
		switch k {
		case "CLAUDE_PLUGIN_DATA", "PATH", "SETU_HOME", "SETU_SESSION", "AIW_UI_SESSION", "BLUBIRD_IDLE_GUARD":
			continue
		}
		env = append(env, kv)
	}
	path := os.Getenv("PATH")
	if m.d.BinDir != "" {
		path = m.d.BinDir + string(os.PathListSeparator) + path
	}
	env = append(env,
		"PATH="+path,
		"SETU_HOME="+m.d.Home.Root,
		"SETU_SESSION="+id,
		"AIW_UI_SESSION="+id,
		"BLUBIRD_IDLE_GUARD=off",
	)
	return append(env, extra...)
}

// spawn starts claude detached (own session and process group), records pid and running, and
// starts the follower.
func (m *Manager) spawn(ctx context.Context, id string, argv []string, cwd string, o spawnOpts) (Record, error) {
	sp, ep := streamPath(m.d.Home, id), filepath.Join(sessionDir(m.d.Home, id), "stderr.log")
	var offset int64
	if fi, err := os.Stat(sp); err == nil {
		offset = fi.Size()
	}
	sf, err := os.OpenFile(sp, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return m.mustGet(id), m.failRec(id, "failed to spawn claude: "+err.Error())
	}
	ef, err := os.OpenFile(ep, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		sf.Close()
		return m.mustGet(id), m.failRec(id, "failed to spawn claude: "+err.Error())
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Dir = cwd
	cmd.Stdout, cmd.Stderr = sf, ef
	cmd.Env = m.childEnv(id, o.env)
	cmd.ExtraFiles = o.files
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		sf.Close()
		ef.Close()
		return m.mustGet(id), m.failRec(id, "failed to spawn claude: "+err.Error())
	}
	sf.Close()
	ef.Close()
	p := &proc{cmd: cmd, pid: cmd.Process.Pid, done: make(chan struct{})}
	started, _ := psStart(ctx, p.pid)
	m.mu.Lock()
	m.procs[id] = p
	m.mu.Unlock()
	go func() {
		err := cmd.Wait()
		rc := 0
		if err != nil {
			rc = -1
			if cmd.ProcessState != nil {
				rc = cmd.ProcessState.ExitCode()
			}
			if rc == 0 {
				rc = -1
			}
		}
		p.rc.Store(int32(rc))
		close(p.done)
	}()
	rec, err := m.Update(id, func(r *Record) error {
		r.PID, r.PidStarted = p.pid, started
		r.Status = StRunning
		r.StreamOffset = offset
		// accumulation bases: this process's own cost, tokens and hooks add to what came before
		r.CostBase, r.TokenBase, r.HooksBase = 0, nil, r.Hooks
		if r.Cost != nil {
			r.CostBase = *r.Cost
		}
		if r.Tokens != nil {
			t := *r.Tokens
			r.TokenBase = &t
		}
		if o.mutate != nil {
			o.mutate(r)
		}
		return nil
	})
	if err != nil {
		return rec, err
	}
	go m.follow(id, p, p.pid, started, offset, o.answered, o.resuming)
	return rec, nil
}

// psStart is the pid-reuse fingerprint: `ps -o lstart= -p pid` (LC_ALL=C). failed means ps
// itself did not run (a transient error); "" with failed=false means no such process.
func psStart(ctx context.Context, pid int) (start string, failed bool) {
	r := execx.Run(ctx, []string{"ps", "-o", "lstart=", "-p", fmt.Sprint(pid)}, execx.Opts{Env: []string{"LC_ALL=C"}, Timeout: 5 * time.Second})
	if r.Code == 127 || r.Code == 124 {
		return "", true
	}
	if r.Code != 0 {
		return "", false
	}
	return strings.TrimSpace(string(r.Stdout)), false
}

// ---- following ----

type runState struct {
	asked, sawInit, sawResult, isError bool
	firstErr                           string
	hasFirstErr                        bool
	guard                              map[string]any
	blocked                            string
	limit                              *event
	runCost                            *float64
	runTokens                          *Tokens
	runHooks, hooksFlushed             int
}

// follow tails stream.jsonl until the process is gone and then decides the outcome (S§1.8).
// p.cmd is nil for a re-attached pid, which is judged by its ps fingerprint.
func (m *Manager) follow(id string, p *proc, pid int, started string, offset int64, answered, resuming bool) {
	var st runState
	reaped := false
	defer func() {
		if r := recover(); r != nil {
			logf("sessions: follower for %s failed: %v", id, r)
			m.followFailed(id, fmt.Sprint(r))
		}
		m.mu.Lock()
		if m.procs[id] == p {
			delete(m.procs, id)
			delete(m.stopping, id)
		}
		m.mu.Unlock()
		if rec, err := m.Get(id); err == nil {
			m.releaseBatch(rec.Batch)
		}
	}()
	rec, err := m.Get(id)
	if err != nil {
		return
	}
	base := rec
	cmdKey := rec.ClaudeCmd
	path := streamPath(m.d.Home, id)
	var buf []byte
	var turnEnded time.Time
	psErrors := 0

	handle := func(line []byte) {
		for _, ev := range parseLine(line) {
			m.onEvent(id, &st, ev, cmdKey, base)
		}
	}
	drain := func() error {
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		defer f.Close()
		chunk := make([]byte, 256<<10)
		grew := false
		for {
			n, rerr := f.ReadAt(chunk, offset)
			if n > 0 {
				grew = true
				offset += int64(n)
				buf = append(buf, chunk[:n]...)
				for {
					i := indexByte(buf, '\n')
					if i < 0 {
						break
					}
					handle(buf[:i])
					buf = buf[i+1:]
				}
				if len(buf) > maxPartialLine {
					buf = nil
				}
			}
			if rerr != nil || n == 0 {
				if rerr != nil && rerr != io.EOF {
					return rerr
				}
				break
			}
		}
		if grew {
			m.streamPing(id)
		}
		m.flushHooks(id, &st, base)
		return nil
	}
	alive := func() bool {
		if p.cmd != nil {
			return !p.exited()
		}
		if started == "" {
			return false
		}
		cur, failed := psStart(context.Background(), pid)
		if failed {
			psErrors++
			return psErrors <= 25
		}
		psErrors = 0
		return cur == started
	}

	for alive() {
		_ = drain()
		if st.sawResult && st.asked && !st.isError && !reaped {
			if turnEnded.IsZero() {
				turnEnded = time.Now()
			}
			if time.Since(turnEnded) > m.grace {
				if cur, err := m.Get(id); err == nil && cur.Status == StWaiting {
					reaped = true
					_ = syscall.Kill(-pid, syscall.SIGTERM)
				}
			}
		}
		if p.cmd != nil {
			select {
			case <-p.done:
			case <-time.After(m.poll):
			}
		} else {
			time.Sleep(m.poll)
		}
	}
	if err := drain(); err != nil && p.cmd != nil && !os.IsNotExist(err) {
		panic(err)
	}
	if len(strings.TrimSpace(string(buf))) > 0 {
		handle(buf)
		buf = nil
		m.flushHooks(id, &st, base)
	}
	var rc *int
	if reaped {
		z := 0
		rc = &z
	} else if p.cmd != nil {
		v := int(p.rc.Load())
		rc = &v
	}
	m.outcome(id, &st, rc, p.cmd != nil, answered, resuming, cmdKey)
}

func indexByte(b []byte, c byte) int {
	for i, x := range b {
		if x == c {
			return i
		}
	}
	return -1
}

func (m *Manager) followFailed(id, msg string) {
	if m.isStopping(id) {
		return
	}
	if rec, err := m.Get(id); err == nil && (rec.Status == StStarting || rec.Status == StRunning) {
		_, _ = m.Update(id, func(r *Record) error {
			r.Status = StFailed
			r.EndedAt = isoNow(m.d.now())
			r.PendingQuestion = nil
			r.Error = "follower failed: " + msg
			return nil
		})
	}
}

// streamPing publishes a stream-growth event, at most once a second per session.
func (m *Manager) streamPing(id string) {
	if m.d.Bus == nil {
		return
	}
	m.mu.Lock()
	last := m.streamAt[id]
	now := time.Now()
	if now.Sub(last) < time.Second {
		m.mu.Unlock()
		return
	}
	m.streamAt[id] = now
	m.mu.Unlock()
	m.d.Bus.Publish(events.TSessions, map[string]any{"id": id, "change": "stream"})
}

func (m *Manager) flushHooks(id string, st *runState, base Record) {
	if st.runHooks == 0 || st.runHooks == st.hooksFlushed {
		return
	}
	st.hooksFlushed = st.runHooks
	want := base.HooksBase + st.runHooks
	_, _ = m.Update(id, func(r *Record) error { r.Hooks = want; return nil })
}

// onEvent applies one stream event to the run state and the record.
func (m *Manager) onEvent(id string, st *runState, ev event, cmdKey string, base Record) {
	if ev.isHook() {
		st.runHooks++
	}
	switch ev.Kind {
	case "session_id":
		st.sawInit = true
		// a new process: an earlier `setu ask` was answered (or this is a replay)
		st.asked, st.sawResult, st.isError = false, false, false
		st.guard, st.blocked = nil, ""
		st.runCost, st.runTokens = nil, nil
		_, _ = m.Update(id, func(r *Record) error {
			r.SessionID = ev.ID
			if ev.Model != "" {
				r.Model = ev.Model
			}
			return nil
		})
	case "tool":
		if ev.Name == "Bash" {
			var in struct {
				Command string `json:"command"`
			}
			if json.Unmarshal(ev.Input, &in) == nil {
				c := strings.TrimLeft(in.Command, " \t\r\n")
				if strings.HasPrefix(c, "setu ask") || strings.HasPrefix(c, "aiw ask") {
					st.asked = true
				}
			}
		}
	case "guard_ask":
		if st.guard == nil && len(ev.Edits) > 0 {
			st.guard = ev.Edits[0]
		}
		if len(ev.Edits) > 1 {
			logf("sessions %s: %d protected edits denied; only the first is relayed", id, len(ev.Edits))
		}
	case "prompt_blocked":
		st.blocked = ev.Reason
	case "limit":
		m.mu.Lock()
		m.usage[cmdKey] = ev.Info
		m.mu.Unlock()
		if v := ev.Info["status"]; v != nil {
			if status, _ := v.(string); status != "allowed" && status != "allowed_warning" {
				e := ev
				st.limit = &e
			}
		}
	case "result":
		st.isError, st.sawResult = ev.IsError, true
		if ev.IsError && !st.hasFirstErr {
			st.hasFirstErr = true
			switch {
			case ev.Err != "":
				st.firstErr = ev.Err
			case ev.ResultText != nil && *ev.ResultText != "":
				st.firstErr = *ev.ResultText
			default:
				st.firstErr = "claude reported an error"
			}
		}
		if ev.Cost != nil {
			c := *ev.Cost
			st.runCost = &c
		}
		if ev.Tokens != nil {
			t := *ev.Tokens
			if st.runTokens != nil {
				t = st.runTokens.add(t)
			}
			st.runTokens = &t
		}
		// accumulate across resumes: this process's total on top of what came before it
		_, _ = m.Update(id, func(r *Record) error {
			if st.runCost != nil {
				c := base.CostBase + *st.runCost
				r.Cost = &c
			}
			if st.runTokens != nil {
				t := *st.runTokens
				if base.TokenBase != nil {
					t = base.TokenBase.add(t)
				}
				r.Tokens = &t
			}
			return nil
		})
	}
}

// outcome decides the record's state once the process is gone (S§1.8). rc is nil for a
// re-attached pid.
func (m *Manager) outcome(id string, st *runState, rc *int, isChild, answered, resuming bool, cmdKey string) {
	rec, err := m.Get(id)
	if err != nil {
		return
	}
	now := isoNow(m.d.now())
	if !m.isStopping(id) && rec.Status != StStopped {
		switch {
		case st.isError && (st.limit != nil || limitRe.MatchString(st.firstErr)):
			m.markLimited(id, st.limit, st.firstErr)
		case (answered || resuming) && (rc == nil || *rc != 0) && !st.sawInit && st.hasFirstErr:
			_, _ = m.Update(id, func(r *Record) error {
				r.Status, r.EndedAt, r.PendingQuestion = StFailed, now, nil
				r.Error = "cannot resume: " + st.firstErr
				return nil
			})
		case !isChild && !(st.sawResult && !st.isError):
			_, _ = m.Update(id, func(r *Record) error {
				r.Status, r.EndedAt, r.PendingQuestion = StFailed, now, nil
				r.Error = "claude exited while the UI was down without a successful result; see stderr.log"
				return nil
			})
		case (rc == nil || *rc == 0) && !st.isError:
			switch {
			case st.blocked != "":
				_, _ = m.Update(id, func(r *Record) error {
					r.Status, r.EndedAt, r.PendingQuestion, r.PendingAnswer = StFailed, now, nil, ""
					r.Error = "blocked by mask-secrets: " + st.blocked
					return nil
				})
			case rec.Status == StWaiting: // a question was recorded mid-run: stay waiting for the answer
				_, _ = m.Update(id, func(r *Record) error { r.EndedAt, r.PendingAnswer = now, ""; return nil })
			case st.guard != nil && m.relayGuard(id, st.guard):
				_, _ = m.Update(id, func(r *Record) error { r.EndedAt, r.PendingAnswer = now, ""; return nil })
			case st.asked:
				_, _ = m.Update(id, func(r *Record) error {
					r.Status, r.EndedAt = StFailed, now
					r.Error = "setu ask ran but recorded no question; see stream.jsonl"
					return nil
				})
			default:
				_, _ = m.Update(id, func(r *Record) error {
					r.Status, r.EndedAt, r.PendingAnswer = StDone, now, ""
					return nil
				})
			}
		default:
			code := "?"
			if rc != nil {
				code = fmt.Sprint(*rc)
			}
			_, _ = m.Update(id, func(r *Record) error {
				r.Status, r.EndedAt, r.PendingQuestion = StFailed, now, nil
				r.Error = "claude exited with code " + code + "; see stderr.log"
				return nil
			})
		}
		m.deliverQueued(id)
	}
}

// markLimited records a rate-limited run: it resumes by itself at reset when the time is known.
func (m *Manager) markLimited(id string, ev *event, firstErr string) {
	_, _ = m.Update(id, func(r *Record) error {
		r.Status = StLimited
		r.PendingQuestion = nil
		r.Error = firstErr
		r.EndedAt = ""
		r.LimitResetsAt, r.LimitType = 0, ""
		auto := false
		if ev != nil {
			r.LimitType = ev.LimitType
			if ev.ResetsAt != nil {
				r.LimitResetsAt = *ev.ResetsAt
				auto = true
			}
		}
		r.AutoResume = &auto
		return nil
	})
}

// Limits is {account cmd: {limited_until, warning}} for the header chips.
func (m *Manager) Limits() map[string]Limit {
	now := m.d.now().Unix()
	out := map[string]Limit{}
	for _, r := range m.listAll() {
		if r.Status == StLimited && r.LimitResetsAt > now {
			l := out[r.ClaudeCmd]
			if r.LimitResetsAt > l.LimitedUntil {
				l.LimitedUntil = r.LimitResetsAt
			}
			out[r.ClaudeCmd] = l
		}
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	for cmd, info := range m.usage {
		if s, _ := info["status"].(string); s == "allowed_warning" {
			if reset, _ := info["resetsAt"].(float64); int64(reset) > now {
				l := out[cmd]
				w := &LimitWarning{}
				w.Type, _ = info["rateLimitType"].(string)
				if u, ok := info["utilization"].(float64); ok {
					w.Utilization = &u
				}
				l.Warning = w
				out[cmd] = l
			}
		}
	}
	return out
}

func (m *Manager) limitedUntil(cmd string) int64 {
	return m.Limits()[cmd].LimitedUntil
}
