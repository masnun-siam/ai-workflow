package sessions

import (
	"context"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// Commands returns the verbs of this package: `setu ask` and `setu hook`.
func Commands() []cli.Command {
	return []cli.Command{{
		Name:    "ask",
		Summary: "record a gate question for a headless run (AskUserQuestion stand-in)",
		Run:     runAsk,
	}, {
		Name:    "hook",
		Summary: "Claude Code hooks for setu sessions (idle)",
		Run:     runHook,
	}}
}

// runAsk runs inside a child claude session's Bash tool. It writes the session's meta.json under
// the session flock and prints the line the model acts on. Exit 0 recorded; 2 no session or
// another round is waiting; 5 bad payload.
func runAsk(ctx context.Context, env cli.Env, args []string) int {
	getenv := env.Getenv
	if getenv == nil {
		getenv = os.Getenv
	}
	var payload *string
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--json" && i+1 < len(args):
			i++
			payload = &args[i]
		case strings.HasPrefix(a, "--json="):
			v := strings.TrimPrefix(a, "--json=")
			payload = &v
		default:
			fmt.Fprintf(env.Stderr, "usage: setu ask [--json STR]\n")
			return cli.ExitUsage
		}
	}
	sid := getenv("SETU_SESSION")
	if sid == "" {
		sid = getenv("AIW_UI_SESSION")
	}
	h := env.Home
	if h == nil {
		var err error
		if h, err = home.Open(); err != nil {
			fmt.Fprintln(env.Stderr, "setu ask needs a setu session (SETU_SESSION); interactive runs use AskUserQuestion")
			return 2
		}
	}
	if _, err := readRecord(h, sid); err != nil {
		fmt.Fprintln(env.Stderr, "setu ask needs a setu session (SETU_SESSION); interactive runs use AskUserQuestion")
		return 2
	}
	var raw []byte
	if payload != nil {
		raw = []byte(*payload)
	} else if env.Stdin != nil {
		raw, _ = io.ReadAll(io.LimitReader(env.Stdin, 1<<20))
	}
	rid, err := SetPending(h, sid, raw)
	if err != nil {
		fmt.Fprintln(env.Stderr, err.Error())
		switch errs.KindOf(err) {
		case errs.KConflict:
			return 2
		case errs.KInvalid:
			return 5
		}
		return 1
	}
	fmt.Fprintf(env.Stdout, "RECORDED %s. The question is now with the human. End your turn immediately; the answer arrives as your next message: Answer to %s: {...}\n", rid, rid)
	return 0
}
