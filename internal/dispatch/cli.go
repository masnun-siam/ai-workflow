package dispatch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf16"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
)

// CLI exit codes of `setu dispatch`.
const (
	ExitOK      = 0
	ExitProblem = 1 // doctor found a problem; an unexpected failure
	ExitInvalid = 5 // a bad value, a conflict, a missing dispatch (the old ValueError)
)

// DefaultPort is the UI server's port when settings do not say otherwise.
const DefaultPort = 8420

// CLIGrind lets the wiring give the CLI process the grind resolver for `dispatch plan` (the server
// passes it through Deps). It returns nil when unavailable; plan then skips the grind warnings.
var CLIGrind func(h *home.Home) func(repo string) GrindPlan

// CLIStart starts `setu serve` detached; replaceable in tests.
var CLIStart = startServe

// Commands: the `dispatch` verb.
func Commands() []cli.Command {
	return []cli.Command{{Name: "dispatch", Summary: "run an epic's child issues as parallel lanes (plan|start|ls|show|set|pause|resume|cancel|lane|watch|retry-failed|end|archive|doctor)",
		Run: run}}
}

const usageText = `usage: setu dispatch <plan|start|ls|archive|doctor|show|set|pause|resume|cancel|lane|watch|retry-failed|end> ...
  plan|start <epic> [--max N] [--grind off|simple|full] [--ci wait|defer|ignore] [--auto-merge] [--skip-approval]
             [--feature-branch B] [--base-branch B] [--model M] [--effort E]
  ls | archive [--days D] | doctor [id] | show <id> | set <id> k=v... | pause|resume|cancel <id>
  lane <id> <lane|n> <action> [text] | watch <id> [--since T] [--timeout S] | retry-failed <id> | end <id> <open-pr|qa|grind-pr>
`

type opts map[string]string

// parseArgs splits args into positionals and flags (interspersed, `--k v` or `--k=v`).
func parseArgs(args, valueFlags, boolFlags []string) ([]string, opts, error) {
	val, bl := map[string]bool{}, map[string]bool{}
	for _, f := range valueFlags {
		val[f] = true
	}
	for _, f := range boolFlags {
		bl[f] = true
	}
	var pos []string
	o := opts{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if !strings.HasPrefix(a, "--") || a == "--" {
			pos = append(pos, a)
			continue
		}
		name, v, hasV := strings.Cut(a[2:], "=")
		switch {
		case bl[name]:
			o[name] = "true"
		case val[name]:
			if !hasV {
				if i+1 >= len(args) {
					return nil, nil, fmt.Errorf("--%s needs a value", name)
				}
				i++
				v = args[i]
			}
			o[name] = v
		default:
			return nil, nil, fmt.Errorf("unknown flag --%s", name)
		}
	}
	return pos, o, nil
}

// pyDump renders v like Python's json.dumps: ensure_ascii, ", " and ": " separators when compact,
// indent spaces otherwise.
func pyDump(v any, indent int) string {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if indent > 0 {
		enc.SetIndent("", strings.Repeat(" ", indent))
	}
	_ = enc.Encode(v)
	b := bytes.TrimRight(buf.Bytes(), "\n")
	var out strings.Builder
	inStr, esc := false, false
	for _, r := range string(b) {
		switch {
		case inStr:
			switch {
			case esc:
				esc = false
				out.WriteRune(r)
			case r == '\\':
				esc = true
				out.WriteRune(r)
			case r == '"':
				inStr = false
				out.WriteRune(r)
			case r < 0x80:
				out.WriteRune(r)
			case r > 0xFFFF:
				a, c := utf16.EncodeRune(r)
				fmt.Fprintf(&out, "\\u%04x\\u%04x", a, c)
			default:
				fmt.Fprintf(&out, "\\u%04x", r)
			}
		case r == '"':
			inStr = true
			out.WriteRune(r)
		case indent == 0 && (r == ',' || r == ':'):
			out.WriteRune(r)
			out.WriteRune(' ')
		default:
			out.WriteRune(r)
		}
	}
	return out.String()
}

func pyFloat(f float64) string {
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(s, ".") {
		s += ".0"
	}
	return s
}

type cliEnv struct {
	ctx  context.Context
	env  cli.Env
	svc  *Service
	h    *home.Home
	port int
}

func run(ctx context.Context, env cli.Env, args []string) int {
	if len(args) == 0 {
		fmt.Fprint(env.Stderr, usageText)
		return cli.ExitUsage
	}
	if env.Home == nil {
		fmt.Fprintln(env.Stderr, "setu dispatch: cannot open the data directory")
		return ExitProblem
	}
	var jv JevAsker
	jc := jev.New(env.Home, useJev(env.Home))
	jv = jc
	d := Deps{Home: env.Home, GH: gh.New(), Jev: jv}
	if CLIGrind != nil {
		d.Grind = CLIGrind(env.Home)
	}
	c := &cliEnv{ctx: ctx, env: env, svc: New(d), h: env.Home, port: serverPort(env.Home)}
	return c.dispatch(args)
}

func useJev(h *home.Home) func() bool {
	return func() bool {
		var m map[string]any
		_ = home.ReadJSON(h.Path("ui_settings.json"), &m)
		if v, ok := m["use_jev"].(bool); ok {
			return v
		}
		return true
	}
}

func serverPort(h *home.Home) int {
	var m struct {
		Server struct {
			Port int `json:"port"`
		} `json:"server"`
	}
	_ = home.ReadJSON(h.Path("ui_settings.json"), &m)
	if m.Server.Port > 0 {
		return m.Server.Port
	}
	return DefaultPort
}

func portOpen(port int) bool {
	c, err := net.DialTimeout("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)), time.Second)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

// startServe launches `setu serve` detached, logging to <home>/setu.log.
func startServe(h *home.Home) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	log, err := os.OpenFile(h.Path("setu.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	defer log.Close()
	cmd := exec.Command(exe, "serve")
	cmd.Stdout, cmd.Stderr = log, log
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

func (c *cliEnv) out(format string, a ...any) { fmt.Fprintf(c.env.Stdout, format+"\n", a...) }

func (c *cliEnv) fail(err error) int {
	fmt.Fprintln(c.env.Stderr, "error:", err)
	if errs.KindOf(err) != 0 {
		return ExitInvalid
	}
	return ExitProblem
}

func (c *cliEnv) usage(msg string) int {
	fmt.Fprintln(c.env.Stderr, "setu dispatch:", msg)
	return cli.ExitUsage
}

var settingFlags = []string{"max", "grind", "ci", "feature-branch", "base-branch", "model", "effort"}

// flagSettings is the settings patch given by flags to plan and start.
func flagSettings(o opts) (map[string]any, error) {
	p := map[string]any{}
	if v, ok := o["max"]; ok {
		n, err := strconv.Atoi(v)
		if err != nil {
			return nil, fmt.Errorf("--max must be an integer")
		}
		p["max"] = n
	}
	for _, k := range []string{"grind", "ci", "model", "effort"} {
		if v, ok := o[k]; ok {
			p[k] = v
		}
	}
	if v, ok := o["feature-branch"]; ok {
		p["feature_branch"] = v
	}
	if v, ok := o["base-branch"]; ok {
		p["base_branch"] = v
	}
	if o["auto-merge"] == "true" {
		p["auto_merge"] = true
	}
	if o["skip-approval"] == "true" {
		p["skip_approval"] = true
	}
	return p, nil
}

func (c *cliEnv) dispatch(args []string) int {
	verb, rest := args[0], args[1:]
	switch verb {
	case "plan", "start":
		pos, o, err := parseArgs(rest, settingFlags, []string{"auto-merge", "skip-approval"})
		if err != nil || len(pos) != 1 {
			if err == nil {
				err = fmt.Errorf("give the epic as owner/repo#N, or N in the current checkout")
			}
			return c.usage(err.Error())
		}
		patch, err := flagSettings(o)
		if err != nil {
			return c.usage(err.Error())
		}
		req := CreateRequest{Epic: pos[0], Settings: patch}
		if verb == "plan" {
			p, err := c.svc.Plan(c.ctx, req)
			if err != nil {
				return c.fail(err)
			}
			c.out("%s", pyDump(p, 1))
			return ExitOK
		}
		d, err := c.svc.Create(c.ctx, req)
		if err != nil {
			return c.fail(err)
		}
		if !portOpen(c.port) {
			if err := CLIStart(c.h); err != nil {
				fmt.Fprintln(c.env.Stderr, "warning: could not start setu serve:", err)
			}
		}
		c.out("%s", pyDump(map[string]any{"id": d.ID, "lanes": len(d.Lanes), "since": d.CreatedAt,
			"ui": "http://127.0.0.1:" + strconv.Itoa(c.port)}, 0))
		return ExitOK
	case "ls":
		for _, d := range store.List(c.h) {
			closed := 0
			for _, x := range d.Lanes {
				if x.Stage == store.StClosed {
					closed++
				}
			}
			name := d.Title
			if d.Epic != nil && *d.Epic != "" {
				name = *d.Epic
			}
			c.out("%s  %-9s  %-24s  %d/%d closed  %s", d.ID, d.State, name, closed, len(d.Lanes), d.Runner)
		}
		return ExitOK
	case "archive":
		_, o, err := parseArgs(rest, []string{"days"}, nil)
		if err != nil {
			return c.usage(err.Error())
		}
		days := float64(store.ArchiveDays)
		if v, ok := o["days"]; ok {
			if days, err = strconv.ParseFloat(v, 64); err != nil {
				return c.usage("--days must be a number")
			}
		}
		for _, id := range c.svc.Archive(days) {
			c.out("%s", id)
		}
		return ExitOK
	case "doctor":
		return c.doctor(rest)
	case "show":
		if len(rest) != 1 {
			return c.usage("show <id>")
		}
		d, err := store.Load(c.h, rest[0])
		if err != nil {
			return c.fail(err)
		}
		c.out("%s", pyDump(summary(d), 1))
		return ExitOK
	case "set":
		if len(rest) < 2 {
			return c.usage("set <id> key=value ...")
		}
		patch := map[string]any{}
		for _, item := range rest[1:] {
			k, v, ok := strings.Cut(item, "=")
			if !ok || !isSettingKey(k) {
				return c.fail(errs.Invalid("expected key=value with key in %v, got %q", sortedKeys(), item))
			}
			val, err := castSetting(k, v)
			if err != nil {
				return c.fail(err)
			}
			patch[k] = val
		}
		d, err := c.svc.SetSettings(rest[0], patch)
		if err != nil {
			return c.fail(err)
		}
		c.out("%s", pyDump(d.Settings, 0))
		return ExitOK
	case "pause", "resume", "cancel":
		if len(rest) != 1 {
			return c.usage(verb + " <id>")
		}
		state := map[string]string{"pause": store.Paused, "resume": store.Running, "cancel": store.Cancelled}[verb]
		if _, err := c.svc.SetState(rest[0], state, false); err != nil {
			return c.fail(err)
		}
		if verb == "cancel" {
			c.out("cancelled")
		} else {
			c.out("%sd", verb)
		}
		return ExitOK
	case "lane":
		if len(rest) < 3 || len(rest) > 4 {
			return c.usage("lane <id> <lane|n> <action> [text]")
		}
		d, err := store.Load(c.h, rest[0])
		if err != nil {
			return c.fail(err)
		}
		k := rest[1]
		if !strings.Contains(k, "#") {
			for key, x := range d.Lanes {
				if strconv.Itoa(x.N) == k {
					k = key
				}
			}
		}
		text := ""
		if len(rest) == 4 {
			text = rest[3]
		}
		if _, err := c.svc.LaneAction(rest[0], k, rest[2], text); err != nil {
			return c.fail(err)
		}
		c.out("%s: %s", k, rest[2])
		return ExitOK
	case "watch":
		pos, o, err := parseArgs(rest, []string{"since", "timeout"}, nil)
		if err != nil || len(pos) != 1 {
			return c.usage("watch <id> [--since T] [--timeout S]")
		}
		since := epoch(time.Now())
		if v, ok := o["since"]; ok {
			if since, err = strconv.ParseFloat(v, 64); err != nil {
				return c.usage("--since must be a number")
			}
		}
		timeout := 3000.0
		if v, ok := o["timeout"]; ok {
			if timeout, err = strconv.ParseFloat(v, 64); err != nil {
				return c.usage("--timeout must be a number")
			}
		}
		evs, state, err := Watch(c.h, pos[0], since, timeout, 10, WatchHooks{Up: func() bool { return portOpen(c.port) },
			Start: func() { _ = CLIStart(c.h) }})
		if err != nil {
			return c.fail(err)
		}
		last := since
		for _, e := range evs {
			lane := "-"
			if e.Lane != nil {
				lane = *e.Lane
			}
			c.out("%s  %-20s  %-14s  %s", time.Unix(int64(e.At), 0).Format("15:04"), lane, e.Kind, e.Text)
			if e.At > last {
				last = e.At
			}
		}
		c.out("state=%s since=%s", state, pyFloat(last))
		return ExitOK
	case "retry-failed":
		if len(rest) != 1 {
			return c.usage("retry-failed <id>")
		}
		_, keys, err := c.svc.RetryFailed(rest[0])
		if err != nil {
			return c.fail(err)
		}
		if len(keys) == 0 {
			c.out("nothing to retry")
		} else {
			c.out("%s", strings.Join(keys, "\n"))
		}
		return ExitOK
	case "end":
		if len(rest) != 2 {
			return c.usage("end <id> <open-pr|qa|grind-pr>")
		}
		if _, err := c.svc.RequestEnd(rest[0], rest[1]); err != nil {
			return c.fail(err)
		}
		c.out("%s: requested; the UI server runs it at its next tick", rest[1])
		return ExitOK
	}
	fmt.Fprint(c.env.Stderr, usageText)
	return cli.ExitUsage
}

func isSettingKey(k string) bool {
	for _, n := range settingKeys {
		if n == k {
			return true
		}
	}
	return false
}

func sortedKeys() []string {
	k := append([]string(nil), settingKeys...)
	sort.Strings(k)
	return k
}

// castSetting casts the text of a `set k=v` pair: max int, flags truthy in 1,true,on,yes,
// max_cost float or null, the rest string or null.
func castSetting(k, v string) (any, error) {
	switch k {
	case "max":
		n, err := strconv.Atoi(v)
		if err != nil {
			return nil, errs.Invalid("max must be an integer from 1 to 10")
		}
		return n, nil
	case "auto_merge", "skip_approval":
		switch strings.ToLower(v) {
		case "1", "true", "on", "yes":
			return true, nil
		}
		return false, nil
	case "max_cost":
		if v == "" {
			return nil, nil
		}
		f, err := strconv.ParseFloat(v, 64)
		if err != nil {
			return nil, errs.Invalid("max_cost must be a positive number up to %d", MaxCostLimit)
		}
		return f, nil
	}
	if v == "" {
		return nil, nil
	}
	return v, nil
}

type summaryLane struct {
	Repo       string  `json:"repo"`
	N          int     `json:"n"`
	Title      string  `json:"title"`
	Stage      string  `json:"stage"`
	PR         *int    `json:"pr"`
	NeedsYou   *string `json:"needs_you"`
	Held       *string `json:"held"`
	Gate       *string `json:"gate"`
	SkipReason *string `json:"skip_reason"`
	Paused     bool    `json:"paused"`
}

type dispatchSummary struct {
	ID       string            `json:"id"`
	Epic     *string           `json:"epic"`
	Issues   []string          `json:"issues"`
	Runner   string            `json:"runner"`
	State    string            `json:"state"`
	Settings store.Settings    `json:"settings"`
	FinalPRs map[string]string `json:"final_prs"`
	Lanes    []summaryLane     `json:"lanes"`
}

func summary(d store.Dispatch) dispatchSummary {
	s := dispatchSummary{ID: d.ID, Epic: d.Epic, Issues: d.Issues, Runner: d.Runner, State: d.State, Settings: d.Settings,
		FinalPRs: d.FinalPRs, Lanes: []summaryLane{}}
	xs := make([]*store.Lane, 0, len(d.Lanes))
	for _, x := range d.Lanes {
		xs = append(xs, x)
	}
	sort.Slice(xs, func(i, j int) bool {
		if xs[i].N != xs[j].N {
			return xs[i].N < xs[j].N
		}
		return xs[i].Repo < xs[j].Repo
	})
	for _, x := range xs {
		l := summaryLane{Repo: x.Repo, N: x.N, Title: x.Title, Stage: x.Stage, NeedsYou: store.Ptr(x.NeedsYou),
			Held: store.Ptr(x.Held), Gate: store.Ptr(x.Gate), SkipReason: store.Ptr(x.SkipReason), Paused: x.Paused}
		if x.PR != 0 {
			pr := x.PR
			l.PR = &pr
		}
		s.Lanes = append(s.Lanes, l)
	}
	return s
}

func (c *cliEnv) doctor(rest []string) int {
	var ds []store.Dispatch
	if len(rest) > 0 {
		d, err := store.Load(c.h, rest[0])
		if err != nil {
			return c.fail(err)
		}
		ds = []store.Dispatch{d}
	} else {
		for _, d := range store.List(c.h) {
			if d.State != store.Done && d.State != store.Cancelled {
				ds = append(ds, d)
			}
		}
	}
	up := portOpen(c.port)
	bad := 0
	for i := range ds {
		d := &ds[i]
		probs := Diagnose(d, nil)
		if !up && store.Live(d.State) {
			probs = append([]Problem{{"", "dead server: nothing ticks this dispatch (run `setu serve`)"}}, probs...)
		}
		for _, p := range probs {
			lane := p.Lane
			if lane == "" {
				lane = "-"
			}
			c.out("%s  %s  %s", d.ID, lane, p.Problem)
		}
		bad += len(probs)
		if len(probs) == 0 && d.State != store.Done && d.State != store.Cancelled {
			c.out("%s  ok", d.ID)
		}
	}
	if bad > 0 {
		return ExitProblem
	}
	return ExitOK
}

// WatchKinds are the event kinds that end a watch.
var WatchKinds = map[string]bool{"needs_you": true, "held": true, "awaiting_merge": true, "finished": true, "end": true}

// WatchHooks are the server probes of Watch (nil = none).
type WatchHooks struct {
	Up    func() bool
	Start func()
	Sleep func(time.Duration)
	Clock func() time.Time
}

// Watch polls the record and returns the new events (at > since) once one needs the user, the
// dispatch is done or cancelled, or the timeout passes. While waiting it restarts the server if its
// port is closed, at most once per 60 s.
func Watch(h *home.Home, id string, since, timeout, interval float64, hk WatchHooks) ([]store.Event, string, error) {
	sleep, clock := hk.Sleep, hk.Clock
	if sleep == nil {
		sleep = time.Sleep
	}
	if clock == nil {
		clock = time.Now
	}
	end := clock().Add(time.Duration(timeout * float64(time.Second)))
	lastStart := time.Time{}
	for {
		d, err := store.Load(h, id)
		if err != nil {
			return nil, "", err
		}
		var fresh []store.Event
		wake := false
		for _, e := range d.Events {
			if e.At > since {
				fresh = append(fresh, e)
				wake = wake || WatchKinds[e.Kind]
			}
		}
		if wake || d.State == store.Done || d.State == store.Cancelled || !clock().Before(end) {
			return fresh, d.State, nil
		}
		if hk.Up != nil && hk.Start != nil && !hk.Up() && (lastStart.IsZero() || clock().Sub(lastStart) >= 60*time.Second) {
			hk.Start()
			lastStart = clock()
		}
		sleep(time.Duration(interval * float64(time.Second)))
	}
}
