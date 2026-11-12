package gh

import (
	"context"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
)

// Commands are the verbs `setu ci status` and `setu threads list|resolve`. Output and exit codes
// match the `aiw` verbs they replace; the built-in prompts and pr-grind parse them.
func Commands() []cli.Command { return CommandsWith(New()) }

// CommandsWith is Commands over an explicit client (tests).
func CommandsWith(c Client) []cli.Command {
	return []cli.Command{
		{Name: "ci", Summary: "report a PR's check status: ci status <pr> [--watch] [--timeout S]",
			Run: func(ctx context.Context, env cli.Env, args []string) int { return runCI(ctx, c, env, args) }},
		{Name: "threads", Summary: "list or resolve a PR's review threads: threads list <pr> | resolve <node_id>...",
			Run: func(ctx context.Context, env cli.Env, args []string) int { return runThreads(ctx, c, env, args) }},
	}
}

// optSpec describes the options a verb takes: name -> takes a value.
type parsed struct {
	pos   []string
	flags map[string]string
	has   map[string]bool
}

// parseArgs accepts options anywhere among the positionals (like argparse), `--opt value`,
// `--opt=value` and `--` to end options.
func parseArgs(args []string, valued map[string]bool, bools map[string]bool) (parsed, error) {
	p := parsed{flags: map[string]string{}, has: map[string]bool{}}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			p.pos = append(p.pos, args[i+1:]...)
			break
		}
		if !strings.HasPrefix(a, "--") || a == "-" {
			p.pos = append(p.pos, a)
			continue
		}
		name, val, hasVal := strings.Cut(a, "=")
		switch {
		case bools[name]:
			if hasVal {
				return p, fmt.Errorf("argument %s: ignored explicit argument %q", name, val)
			}
			p.has[name] = true
		case valued[name]:
			if !hasVal {
				if i+1 >= len(args) {
					return p, fmt.Errorf("argument %s: expected one argument", name)
				}
				i++
				val = args[i]
			}
			p.flags[name], p.has[name] = val, true
		default:
			return p, fmt.Errorf("unrecognized arguments: %s", a)
		}
	}
	return p, nil
}

func usageErr(w io.Writer, verb string, err error) int {
	fmt.Fprintf(w, "setu %s: error: %v\n", verb, err)
	return cli.ExitUsage
}

func runCI(ctx context.Context, c Client, env cli.Env, args []string) int {
	if len(args) == 0 || args[0] != "status" {
		fmt.Fprintln(env.Stderr, "usage: setu ci status <pr> [--watch] [--timeout S]")
		return cli.ExitUsage
	}
	p, err := parseArgs(args[1:], map[string]bool{"--timeout": true}, map[string]bool{"--watch": true})
	if err != nil {
		return usageErr(env.Stderr, "ci status", err)
	}
	if len(p.pos) != 1 {
		return usageErr(env.Stderr, "ci status", fmt.Errorf("expected one <pr> argument"))
	}
	timeout := 1200
	if p.has["--timeout"] {
		if timeout, err = strconv.Atoi(strings.TrimSpace(p.flags["--timeout"])); err != nil {
			return usageErr(env.Stderr, "ci status", fmt.Errorf("argument --timeout: invalid int value: %s", pyRepr(p.flags["--timeout"])))
		}
	}
	ref, err := ParsePRRef(ctx, c, p.pos[0], "")
	if err != nil {
		fmt.Fprintln(env.Stderr, err.Error())
		return cli.ExitUsage
	}
	var res CI
	if p.has["--watch"] {
		res = CIWatch(ctx, c, ref, time.Duration(timeout)*time.Second)
	} else {
		res = CISnapshot(ctx, c, ref)
	}
	res = ExpandFailing(ctx, c, ref, res)
	b, _ := PyJSON(res)
	fmt.Fprintf(env.Stdout, "%s\n", b)
	return 0
}

func runThreads(ctx context.Context, c Client, env cli.Env, args []string) int {
	if len(args) == 0 || (args[0] != "list" && args[0] != "resolve") {
		fmt.Fprintln(env.Stderr, "usage: setu threads list <pr> [--open-only] [--for-comment ID] | resolve <node_id>...")
		return cli.ExitUsage
	}
	if args[0] == "resolve" {
		return runResolve(ctx, c, env, args[1:])
	}
	p, err := parseArgs(args[1:], map[string]bool{"--for-comment": true}, map[string]bool{"--open-only": true})
	if err != nil {
		return usageErr(env.Stderr, "threads list", err)
	}
	if len(p.pos) != 1 {
		return usageErr(env.Stderr, "threads list", fmt.Errorf("expected one <pr> argument"))
	}
	var forComment int
	if p.has["--for-comment"] {
		if forComment, err = strconv.Atoi(strings.TrimSpace(p.flags["--for-comment"])); err != nil {
			return usageErr(env.Stderr, "threads list", fmt.Errorf("argument --for-comment: invalid int value: %s", pyRepr(p.flags["--for-comment"])))
		}
	}
	ref, err := ParsePRRef(ctx, c, p.pos[0], "")
	if err != nil {
		fmt.Fprintln(env.Stderr, err.Error())
		return cli.ExitUsage
	}
	ts, err := ListThreads(ctx, c, ref)
	if err != nil {
		fmt.Fprintln(env.Stderr, err.Error())
		return 1
	}
	if p.has["--open-only"] {
		open := []Thread{}
		for _, t := range ts {
			if !t.IsResolved {
				open = append(open, t)
			}
		}
		ts = open
	}
	if p.has["--for-comment"] {
		if t, ok := ThreadForComment(ts, forComment); ok {
			ts = []Thread{t}
		} else {
			ts = []Thread{}
		}
	}
	b, _ := PyJSON(ts)
	fmt.Fprintf(env.Stdout, "%s\n", b)
	return 0
}

// runResolve is per-thread non-fatal: a failure warns and goes on; exit 1 only when every id failed.
func runResolve(ctx context.Context, c Client, env cli.Env, ids []string) int {
	if len(ids) == 0 {
		return usageErr(env.Stderr, "threads resolve", fmt.Errorf("the following arguments are required: node_ids"))
	}
	failed := 0
	for _, id := range ids {
		if err := ResolveThread(ctx, c, id); err != nil {
			failed++
			fmt.Fprintf(env.Stderr, "warning: %s\n", strings.TrimRight(fmt.Sprintf("could not resolve %s: %s", id, err.Error()), " \t\r\n"))
			continue
		}
		fmt.Fprintf(env.Stdout, "resolved %s\n", id)
	}
	if failed == len(ids) {
		return 1
	}
	return 0
}
