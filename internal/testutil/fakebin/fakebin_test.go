package fakebin

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func run(t *testing.T, stdin string, name string, args ...string) (string, string, int) {
	t.Helper()
	cmd := exec.Command(name, args...)
	cmd.Stdin = strings.NewReader(stdin)
	var so, se strings.Builder
	cmd.Stdout, cmd.Stderr = &so, &se
	err := cmd.Run()
	code := 0
	if ee, ok := err.(*exec.ExitError); ok {
		code = ee.ExitCode()
	} else if err != nil {
		t.Fatal(err)
	}
	return so.String(), se.String(), code
}

func TestFakebin(t *testing.T) {
	dir := t.TempDir()
	Install(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "out.txt"), []byte("from file\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	WriteRules(t, dir, []Rule{
		{Bin: "gh", ArgsPrefix: []string{"pr", "view"}, Stdout: `{"state":"OPEN"}`},
		{Bin: "gh", ArgsPrefix: []string{"pr", "list"}, StdoutFile: "out.txt"},
		{Bin: "slackcli", StdinContains: "hello", Stdout: "sent"},
		{Bin: "gh", ArgsContains: "boom", Stderr: "bad", Exit: 3},
		{Bin: "jev", Once: true, Stdout: "first"},
		{Bin: "security", Exec: []string{"sh", "-c", "cat; exit 4"}},
	})
	t.Setenv("SETU_SESSION", "abc")

	cases := []struct {
		name, stdin string
		bin         string
		args        []string
		out, err    string
		code        int
	}{
		{"prefix", "", "gh", []string{"pr", "view", "5"}, `{"state":"OPEN"}`, "", 0},
		{"stdout_file", "", "gh", []string{"pr", "list"}, "from file\n", "", 0},
		{"stdin match", "say hello there", "slackcli", []string{"send"}, "sent", "", 0},
		{"stdin no match", "nope", "slackcli", []string{"send"}, "", "fakebin: no rule\n", 99},
		{"contains + exit", "", "gh", []string{"x", "boom"}, "", "bad", 3},
		{"no rule", "", "gh", []string{"issue", "list"}, "", "fakebin: no rule\n", 99},
		{"claude auth default", "", "claude", []string{"auth", "status", "--json"}, `{"loggedIn":true}` + "\n", "", 0},
		{"once first", "", "jev", nil, "first", "", 0},
		{"once second", "", "jev", nil, "", "fakebin: no rule\n", 99},
		{"exec", "piped", "security", nil, "piped", "", 4},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			out, errOut, code := run(t, c.stdin, c.bin, c.args...)
			if out != c.out || errOut != c.err || code != c.code {
				t.Fatalf("got (%q, %q, %d) want (%q, %q, %d)", out, errOut, code, c.out, c.err, c.code)
			}
		})
	}
	calls := Calls(t, dir)
	if len(calls) != len(cases) {
		t.Fatalf("calls: %d", len(calls))
	}
	if calls[0].Bin != "gh" || calls[0].Args[2] != "5" || calls[0].Env["SETU_SESSION"] != "abc" || calls[2].Stdin != "say hello there" {
		t.Fatalf("%+v", calls[:3])
	}
}
