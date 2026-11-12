package execx

import (
	"context"
	"strings"
	"testing"
	"time"
)

func TestRun(t *testing.T) {
	ctx := context.Background()
	t.Run("ok", func(t *testing.T) {
		r := Run(ctx, []string{"sh", "-c", "echo hi; echo oops >&2"}, Opts{})
		if r.Code != 0 || string(r.Stdout) != "hi\n" || r.LastLine() != "oops" {
			t.Fatalf("%+v", r)
		}
	})
	t.Run("exit code", func(t *testing.T) {
		if r := Run(ctx, []string{"sh", "-c", "exit 7"}, Opts{}); r.Code != 7 {
			t.Fatalf("code %d", r.Code)
		}
	})
	t.Run("missing", func(t *testing.T) {
		r := Run(ctx, []string{"definitely-not-a-binary-xyz"}, Opts{})
		if r.Code != 127 || len(r.Stderr) == 0 {
			t.Fatalf("%+v", r)
		}
	})
	t.Run("timeout kills the group", func(t *testing.T) {
		start := time.Now()
		r := Run(ctx, []string{"sh", "-c", "sleep 30 & sleep 30"}, Opts{Timeout: 300 * time.Millisecond})
		if r.Code != 124 || !strings.HasPrefix(string(r.Stderr), "timed out after") {
			t.Fatalf("%+v", r)
		}
		if time.Since(start) > 5*time.Second {
			t.Fatal("did not return promptly")
		}
	})
	t.Run("env stdin dir", func(t *testing.T) {
		r := Run(ctx, []string{"sh", "-c", "cat; echo $FOO; pwd"}, Opts{Env: []string{"FOO=bar"}, Stdin: strings.NewReader("in\n"), Dir: "/"})
		if string(r.Stdout) != "in\nbar\n/\n" {
			t.Fatalf("%q", r.Stdout)
		}
	})
	t.Run("lastline long", func(t *testing.T) {
		r := Result{Stdout: []byte(strings.Repeat("x", 300) + "\n\n")}
		if len(r.LastLine()) != 200 {
			t.Fatal(len(r.LastLine()))
		}
	})
}
