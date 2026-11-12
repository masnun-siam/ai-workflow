package grind

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/settings"
)

// Exit codes of the grind verbs (API §8). 64 is cli.ExitUsage.
const (
	ExitOK          = 0
	ExitRed         = 1  // ci: red
	ExitPending     = 2  // ci: pending
	ExitConflict    = 3  // ci: conflict; start: draft or closed, or the resolver skip
	ExitCIError     = 4  // ci: could not be read
	ExitStop        = 10 // wait: approved, or clean in deep mode
	ExitTimeout     = 12 // wait: timeout, or nothing yet with --once
	ExitRoundCap    = 20
	ExitStuck       = 21
	ExitThirdParty  = 22
	ExitSilent      = 23
	ExitNotOpen     = 24
	ExitAttempt     = 30 // record ci-attempt: one exists for the head
	ExitQueuedDone  = 31 // done: a push is queued
	ExitQueuedRetry = 32 // retrigger: a push is queued
	ExitNotGreen    = 33 // retrigger: CI is not green
	ExitDone        = 40
	ExitPaused      = 41
	ExitExternal    = 70
)

// CLIDeps overrides the real collaborators of the verbs (tests). Zero fields use the real ones.
type CLIDeps struct {
	GH    gh.Client
	Slack Slack
	Now   func() time.Time
	Sleep func(ctx context.Context, d time.Duration) error
}

type runner struct {
	env      cli.Env
	h        *home.Home
	gh       gh.Client
	slack    Slack
	st       *settings.Store
	now      func() time.Time
	sleep    func(ctx context.Context, d time.Duration) error
	files    Files
	headless bool
}

func realSleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

func newRunner(env cli.Env, o CLIDeps) (*runner, bool) {
	if env.Home == nil {
		fmt.Fprintln(env.Stderr, "setu grind: cannot open the data dir")
		return nil, false
	}
	r := &runner{env: env, h: env.Home, gh: o.GH, slack: o.Slack, now: o.Now, sleep: o.Sleep}
	if r.gh == nil {
		r.gh = gh.New()
	}
	if r.slack == nil {
		r.slack = SlackCLI{}
	}
	if r.now == nil {
		r.now = time.Now
	}
	if r.sleep == nil {
		r.sleep = realSleep
	}
	r.st = settings.Open(env.Home, nil)
	r.files = Files{env.Home}
	get := env.Getenv
	if get == nil {
		get = func(string) string { return "" }
	}
	r.headless = get("SETU_HEADLESS") == "1" || get("AIW_HEADLESS") == "1"
	return r, true
}

// Commands are `setu grind ...`, `setu grind-mode` and `setu grind-reviewers`. The verbs `ci` and
// `threads` are registered by the gh package (`grind ci` and `grind threads` call the same code).
func Commands() []cli.Command { return CommandsWith(CLIDeps{}) }

// CommandsWith is Commands over explicit collaborators.
func CommandsWith(o CLIDeps) []cli.Command {
	wrap := func(f func(*runner, context.Context, []string) int) func(context.Context, cli.Env, []string) int {
		return func(ctx context.Context, env cli.Env, args []string) int {
			r, ok := newRunner(env, o)
			if !ok {
				return ExitExternal
			}
			return f(r, ctx, args)
		}
	}
	return []cli.Command{
		{Name: "grind", Summary: "PR review grind mechanics: start|wait|ci|threads|retrigger|record|pause|done|status|mode|reviewers",
			Run: wrap((*runner).grind)},
		{Name: "grind-mode", Summary: "print the grind mode, deep or simple: grind-mode [--pr URL]",
			Run: wrap((*runner).modeVerb)},
		{Name: "grind-reviewers", Summary: "print who a PR's grind asks: grind-reviewers --pr URL [--strict]",
			Run: wrap((*runner).reviewersVerb)},
	}
}

const grindUsage = `usage: setu grind <verb> <pr> [options]
  start <pr> [--thread URL] [--channel ID] [--reviewer LOGIN|copilot] [--mode deep|simple]
  wait <pr> [--once] [--timeout S] [--last]
  ci <pr> [--watch] [--timeout S]
  threads <pr> [--open-only] [--for-comment ID]
  retrigger <pr>
  record <pr> fixed <id> <sha> [note] | rebutted <id> [note] | note <text> | ci-attempt <sha> <started|outcome>
                queued <sha>... --then retrigger|close | unqueue | jev-ci-hint <text> | jev-finding-hint <text>
  pause <pr> <reason...> [--no-post]
  done <pr> <reason...> [--no-post]
  status <pr> [--json]
  mode [--pr URL]
  reviewers --pr URL [--strict]
exit codes: wait 0 round, 10 stop, 12 timeout/nothing yet, 20 round cap, 21 stuck finding,
  22 third-party comment, 23 reviewer silent, 24 PR not open, 40 done, 41 paused;
  ci 0 green, 1 red, 2 pending, 3 conflict, 4 error; start 3 draft/closed/skip, 64 usage, 70 external;
  retrigger 32 push queued, 33 CI not green; record ci-attempt 30; done 31 push queued`

func (r *runner) grind(ctx context.Context, args []string) int {
	if len(args) == 0 {
		fmt.Fprintln(r.env.Stderr, grindUsage)
		return cli.ExitUsage
	}
	verb, rest := args[0], args[1:]
	switch verb {
	case "-h", "--help", "help":
		fmt.Fprintln(r.env.Stdout, grindUsage)
		return 0
	case "start":
		return r.start(ctx, rest)
	case "wait":
		return r.wait(ctx, rest)
	case "ci":
		return r.ciVerb(ctx, rest)
	case "threads":
		return r.threadsVerb(ctx, rest)
	case "retrigger":
		return r.retrigger(ctx, rest)
	case "record":
		return r.record(ctx, rest)
	case "pause":
		return r.pauseVerb(ctx, rest)
	case "done":
		return r.doneVerb(ctx, rest)
	case "status":
		return r.statusVerb(ctx, rest)
	case "mode":
		return r.modeVerb(ctx, rest)
	case "reviewers":
		return r.reviewersVerb(ctx, rest)
	}
	fmt.Fprintf(r.env.Stderr, "setu grind: unknown verb %q\n%s\n", verb, grindUsage)
	return cli.ExitUsage
}

// ---------- argument parsing ----------

type parsed struct {
	pos   []string
	flags map[string]string
	has   map[string]bool
}

// parseArgs takes options anywhere among the positionals (`--opt value`, `--opt=value`, `--`).
// Unknown `--opts` are errors.
func parseArgs(args []string, valued, bools []string) (parsed, error) {
	vs, bs := map[string]bool{}, map[string]bool{}
	for _, v := range valued {
		vs[v] = true
	}
	for _, b := range bools {
		bs[b] = true
	}
	p := parsed{flags: map[string]string{}, has: map[string]bool{}}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			p.pos = append(p.pos, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(a, "--") {
			p.pos = append(p.pos, a)
			continue
		}
		name, val, hasVal := strings.Cut(a, "=")
		switch {
		case bs[name]:
			if hasVal {
				return p, fmt.Errorf("%s takes no value", name)
			}
			p.has[name] = true
		case vs[name]:
			if !hasVal {
				if i+1 >= len(args) {
					return p, fmt.Errorf("%s expects a value", name)
				}
				i++
				val = args[i]
			}
			p.flags[name], p.has[name] = val, true
		default:
			return p, fmt.Errorf("unrecognized option %s", name)
		}
	}
	return p, nil
}

// usage prints a usage error and returns 64.
func (r *runner) usage(format string, a ...any) int {
	fmt.Fprintf(r.env.Stderr, "setu grind: "+format+"\n", a...)
	return cli.ExitUsage
}

func (r *runner) die(code int, format string, a ...any) int {
	fmt.Fprintf(r.env.Stderr, "setu grind: "+format+"\n", a...)
	return code
}

func (r *runner) warn(format string, a ...any) {
	fmt.Fprintf(r.env.Stderr, "setu grind: "+format+"\n", a...)
}

func (r *runner) printJSON(v any) {
	b, err := gh.PyJSON(v)
	if err != nil {
		fmt.Fprintln(r.env.Stderr, "setu grind: cannot encode output")
		return
	}
	_, _ = r.env.Stdout.Write(append(b, '\n'))
}

// resolveRef turns a PR URL, owner/repo#N, a bare number, or a Slack thread URL into a Key. For a
// Slack URL it also returns the thread. The Slack lookup reads the state files first; the network
// is used only for a thread no state knows (and only when allowNet).
func (r *runner) resolveRef(ctx context.Context, arg string, allowNet bool) (Key, string, error) {
	arg = strings.TrimSpace(arg)
	if arg == "" {
		return Key{}, "", errors.New("missing PR url")
	}
	if m := reURLRepo.FindStringSubmatch(arg); m != nil {
		return Key{m[1], m[2], atoi(m[3])}, "", nil
	}
	if m := reShortRef.FindStringSubmatch(arg); m != nil {
		return Key{m[1], m[2], atoi(m[3])}, "", nil
	}
	if reSlackURL.MatchString(arg) {
		thread, _, _ := strings.Cut(arg, "?")
		if k, ok := r.files.FindByThread(thread); ok {
			return k, "", nil
		}
		if allowNet {
			text, err := r.slack.ReadPermalink(ctx, thread)
			if err != nil {
				return Key{}, "", fmt.Errorf("cannot read the Slack thread: %v", err)
			}
			if m := reURLRepo.FindStringSubmatch(text); m != nil {
				return Key{m[1], m[2], atoi(m[3])}, thread, nil
			}
			return Key{}, "", errors.New("no PR url in the Slack thread")
		}
		return Key{}, "", errors.New("no grind state for that Slack thread")
	}
	if reDigits.MatchString(arg) {
		if !allowNet {
			return Key{}, "", errors.New("a bare PR number needs the network; pass the PR url")
		}
		ref, err := gh.ParsePRRef(ctx, r.gh, arg, "")
		if err != nil {
			return Key{}, "", err
		}
		return Key{ref.Owner, ref.Repo, ref.N}, "", nil
	}
	return Key{}, "", fmt.Errorf("cannot resolve a PR from: %s", arg)
}
