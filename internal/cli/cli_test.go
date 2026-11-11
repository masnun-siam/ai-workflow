package cli

import (
	"bytes"
	"context"
	"strings"
	"testing"
)

func TestRun(t *testing.T) {
	var got []string
	cmds := []Command{
		{Name: "serve", Aliases: []string{"ui"}, Summary: "start", Run: func(_ context.Context, env Env, a []string) int {
			got = a
			return 3
		}},
		{Name: "paths", Summary: "paths", Run: func(context.Context, Env, []string) int { return 0 }},
	}
	cases := []struct {
		args []string
		code int
		err  string
	}{
		{[]string{"serve", "--port", "1"}, 3, ""},
		{[]string{"ui"}, 3, ""},
		{[]string{"paths"}, 0, ""},
		{[]string{"nope"}, 64, "unknown verb"},
		{nil, 64, "usage: setu"},
	}
	for _, c := range cases {
		var errb bytes.Buffer
		if code := Run(context.Background(), Env{Stderr: &errb}, cmds, c.args); code != c.code {
			t.Errorf("%v: code %d want %d", c.args, code, c.code)
		}
		if !strings.Contains(errb.String(), c.err) {
			t.Errorf("%v: stderr %q want %q", c.args, errb.String(), c.err)
		}
	}
	Run(context.Background(), Env{Stderr: &bytes.Buffer{}}, cmds, []string{"serve", "--port", "1"})
	if len(got) != 2 || got[0] != "--port" {
		t.Fatalf("args not passed through: %v", got)
	}
}
