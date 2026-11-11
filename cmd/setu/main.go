// Command setu is the local frontend for Claude Code. This file is wiring only: it builds the
// services, collects every package's Routes and Commands, and starts the loops.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/server"
)

// Set with -ldflags "-X main.version=... -X main.commit=...".
var (
	version = "dev"
	commit  = "none"
)

const defaultPort = 8420

func main() {
	os.Exit(cli.Main(commands(), os.Args[1:]))
}

// commands lists every verb. Packages that own verbs add their `Commands()` here (API.md §1.3).
func commands() []cli.Command {
	cmds := []cli.Command{
		{Name: "serve", Aliases: []string{"ui"}, Summary: "run the web app and API", Run: runServe},
		{Name: "version", Summary: "print the version", Run: runVersion},
	}
	return cmds
}

func runVersion(_ context.Context, env cli.Env, _ []string) int {
	fmt.Fprintf(env.Stdout, "setu %s (%s)\n", version, commit)
	return 0
}

type stringList []string

func (l *stringList) String() string     { return strings.Join(*l, ",") }
func (l *stringList) Set(v string) error { *l = append(*l, v); return nil }

func runServe(ctx context.Context, env cli.Env, args []string) int {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	fs.SetOutput(env.Stderr)
	port := fs.Int("port", defaultPort, "port to listen on (127.0.0.1)")
	noTS := fs.Bool("no-tailscale", false, "do not expose through tailscale serve")
	tsPort := fs.Int("tailscale-port", 443, "tailscale https port: 443, 8443 or 10000")
	var allow stringList
	fs.Var(&allow, "allow-host", "extra allowed Host header (repeatable)")
	if err := fs.Parse(args); err != nil {
		return cli.ExitUsage
	}
	if *tsPort != 443 && *tsPort != 8443 && *tsPort != 10000 {
		fmt.Fprintln(env.Stderr, "setu serve: --tailscale-port must be 443, 8443 or 10000")
		return cli.ExitUsage
	}

	h := env.Home
	if h == nil {
		var err error
		if h, err = home.Open(); err != nil {
			fmt.Fprintln(env.Stderr, "setu serve:", err)
			return 1
		}
	}
	if copied, err := home.Migrate(h, home.OldDataDir()); err != nil {
		fmt.Fprintln(env.Stderr, "setu serve: migration:", err) // not fatal: retried on the next start
	} else if copied {
		fmt.Fprintf(env.Stdout, "migrated %s into %s\n", home.OldDataDir(), h.Root)
	}

	bus := events.New()
	var routes []server.Route
	// Wiring (task O) builds settings, claude, blubird, prompts, gh, products, poller, notify,
	// sessions, grind, review, dispatch, release, away, inbox and views here, appends their
	// Routes to `routes`, and calls their Start(ctx).
	_ = *noTS // tailscale comes from settings.server once settings exist; off until then

	srv := server.New(server.Config{Port: *port, AllowHosts: allow, Version: version, TailscaleHTTPSPort: *tsPort}, bus, routes)
	errc := make(chan error, 1)
	go func() { errc <- srv.Listen(ctx) }()
	select {
	case <-srv.Ready():
		fmt.Fprintf(env.Stdout, "setu %s listening on http://%s\n", version, srv.Addr())
	case err := <-errc:
		fmt.Fprintln(env.Stderr, "setu serve:", err)
		return 1
	}
	if err := <-errc; err != nil {
		fmt.Fprintln(env.Stderr, "setu serve:", err)
		return 1
	}
	return 0
}
