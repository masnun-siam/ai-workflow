// Package cli is the verb dispatcher behind `setu <verb>`.
package cli

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"

	"github.com/masnun-siam/setu/internal/home"
)

type Env struct {
	Stdin          io.Reader
	Stdout, Stderr io.Writer
	Getenv         func(string) string
	Home           *home.Home // nil when the data dir could not be opened
}

type Command struct {
	Name    string
	Aliases []string
	Summary string
	Run     func(ctx context.Context, env Env, args []string) int
}

// ExitUsage is the exit code for usage errors.
const ExitUsage = 64

// Main runs the verb args[0] with the process environment. SIGINT/SIGTERM/SIGHUP cancel the context.
func Main(cmds []Command, args []string) int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
	defer stop()
	env := Env{Stdin: os.Stdin, Stdout: os.Stdout, Stderr: os.Stderr, Getenv: os.Getenv}
	if len(args) > 0 && find(cmds, args[0]) != nil && args[0] != "version" {
		env.Home, _ = home.Open()
	}
	return Run(ctx, env, cmds, args)
}

// Run is Main with an explicit context and Env (for tests).
func Run(ctx context.Context, env Env, cmds []Command, args []string) int {
	if len(args) == 0 {
		usage(env.Stderr, cmds)
		return ExitUsage
	}
	c := find(cmds, args[0])
	if c == nil {
		fmt.Fprintf(env.Stderr, "setu: unknown verb %q\n\n", args[0])
		usage(env.Stderr, cmds)
		return ExitUsage
	}
	return c.Run(ctx, env, args[1:])
}

func find(cmds []Command, name string) *Command {
	for i := range cmds {
		if cmds[i].Name == name {
			return &cmds[i]
		}
		for _, a := range cmds[i].Aliases {
			if a == name {
				return &cmds[i]
			}
		}
	}
	return nil
}

func usage(w io.Writer, cmds []Command) {
	if w == nil {
		return
	}
	sorted := append([]Command(nil), cmds...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].Name < sorted[j].Name })
	fmt.Fprintln(w, "usage: setu <verb> [args]")
	for _, c := range sorted {
		name := c.Name
		if len(c.Aliases) > 0 {
			name += " (" + strings.Join(c.Aliases, ", ") + ")"
		}
		fmt.Fprintf(w, "  %-22s %s\n", name, c.Summary)
	}
}
