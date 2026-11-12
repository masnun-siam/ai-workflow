// Command setu is the local frontend for Claude Code. This file is wiring only: it builds the
// services (internal/wire), collects every package's Commands, and starts the loops.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"runtime/debug"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/grind"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/review"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/wire"
)

// Set with -ldflags "-X main.version=... -X main.commit=...".
var (
	version = "dev"
	commit  = "none"
)

func main() {
	wire.SetupCLI()
	os.Exit(cli.Main(commands(), os.Args[1:]))
}

// commands lists every verb. Packages that own verbs add their `Commands()` here (API.md §1.3).
func commands() []cli.Command {
	cmds := []cli.Command{
		{Name: "serve", Aliases: []string{"ui"}, Summary: "run the web app and API", Run: runServe},
		{Name: "version", Summary: "print the version", Run: runVersion},
		{Name: "paths", Summary: "print the data and prompt directories as JSON", Run: runPaths},
	}
	cmds = append(cmds, sessions.Commands()...) // ask
	cmds = append(cmds, gh.Commands()...)       // ci, threads
	cmds = append(cmds, grind.Commands()...)    // grind, grind-mode, grind-reviewers
	cmds = append(cmds, dispatch.Commands()...)
	cmds = append(cmds, jev.Commands()...)
	cmds = append(cmds, blubird.Commands()...)
	cmds = append(cmds, review.Commands()...)
	return cmds
}

func runVersion(_ context.Context, env cli.Env, _ []string) int {
	fmt.Fprintf(env.Stdout, "setu %s (%s)\n", version, commit)
	return 0
}

// runPaths prints where the data and the extracted prompts live (the built-in prompts call it).
func runPaths(_ context.Context, env cli.Env, _ []string) int {
	h := env.Home
	reg, err := prompts.Load(h, version, blubird.New(h, nil))
	if err != nil {
		fmt.Fprintln(env.Stderr, "setu paths:", err)
		return 1
	}
	grindDir := h.Path("pr-grind")
	if err := os.MkdirAll(grindDir, 0o755); err != nil {
		fmt.Fprintln(env.Stderr, "setu paths:", err)
		return 1
	}
	out := map[string]string{
		"plugin_root": reg.Root(), "prompts_dir": reg.Root(), "data_dir": h.Root, "pr_grind_dir": grindDir,
		"channels": h.Path("channels.json"), "checkouts": h.Path("checkouts.json"), "home": h.Root,
	}
	b, _ := json.MarshalIndent(out, "", "  ")
	fmt.Fprintf(env.Stdout, "%s\n", b)
	return 0
}

type stringList []string

func (l *stringList) String() string     { return strings.Join(*l, ",") }
func (l *stringList) Set(v string) error { *l = append(*l, v); return nil }

// migrationSource is the old data dir; SETU_MIGRATE_FROM overrides it (tests and dry runs).
func migrationSource() string {
	if d := os.Getenv("SETU_MIGRATE_FROM"); d != "" {
		return d
	}
	return home.OldDataDir()
}

func runServe(ctx context.Context, env cli.Env, args []string) int {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	fs.SetOutput(env.Stderr)
	port := fs.Int("port", 0, "port to listen on (127.0.0.1); default from settings (8420)")
	noTS := fs.Bool("no-tailscale", false, "do not expose through tailscale serve")
	tsPort := fs.Int("tailscale-port", 0, "tailscale https port: 443, 8443 or 10000")
	var allow stringList
	fs.Var(&allow, "allow-host", "extra allowed Host header (repeatable)")
	if err := fs.Parse(args); err != nil {
		return cli.ExitUsage
	}
	if *tsPort != 0 && *tsPort != 443 && *tsPort != 8443 && *tsPort != 10000 {
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
	log.SetOutput(env.Stderr)
	src := migrationSource()
	if copied, err := home.Migrate(h, src); err != nil {
		fmt.Fprintln(env.Stderr, "setu serve: migration:", err) // not fatal: retried on the next start
	} else if copied {
		fmt.Fprintf(env.Stdout, "migrated %s into %s\n", src, h.Root)
	}

	bus := events.New()
	binDir := ""
	if exe, err := os.Executable(); err == nil {
		if r, err := filepath.EvalSymlinks(exe); err == nil {
			exe = r
		}
		binDir = filepath.Dir(exe)
	}
	app, err := wire.Build(ctx, h, bus, version, binDir)
	if err != nil {
		fmt.Fprintln(env.Stderr, "setu serve:", err)
		return 1
	}

	cfg := app.Settings.Get().Server
	sc := server.Config{Port: cfg.Port, AllowHosts: append([]string{}, cfg.AllowHosts...), Tailscale: cfg.Tailscale,
		TailscaleHTTPSPort: cfg.TailscaleHTTPSPort, Version: version}
	if *port > 0 {
		sc.Port = *port
	}
	if *tsPort != 0 {
		sc.TailscaleHTTPSPort = *tsPort
	}
	if *noTS {
		sc.Tailscale = false
	}
	if sc.Tailscale {
		if _, err := exec.LookPath("tailscale"); err != nil {
			sc.Tailscale = false
		}
	}
	sc.AllowHosts = append(sc.AllowHosts, allow...)

	srv := server.New(sc, bus, app.Routes())
	app.SetBootID(srv.BootID)
	errc := make(chan error, 1)
	go func() { errc <- srv.Listen(ctx) }()
	select {
	case <-srv.Ready():
		fmt.Fprintf(env.Stdout, "setu %s listening on http://%s\n", version, srv.Addr())
	case err := <-errc:
		fmt.Fprintln(env.Stderr, "setu serve:", err)
		return 1
	}
	app.Start(ctx)
	trimMemory(ctx)
	if err := <-errc; err != nil {
		fmt.Fprintln(env.Stderr, "setu serve:", err)
		return 1
	}
	return 0 // child claude processes are never killed on exit
}

// trimMemory keeps the idle footprint small (resource budget): a lower GC target, and the heap
// handed back to the OS every two minutes.
func trimMemory(ctx context.Context) {
	debug.SetGCPercent(40)
	go func() {
		t := time.NewTicker(2 * time.Minute)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				debug.FreeOSMemory()
			}
		}
	}()
}
