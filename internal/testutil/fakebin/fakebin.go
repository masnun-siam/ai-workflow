// Package fakebin is a test harness: fake claude, gh, slackcli, jev, terminal-notifier, security
// and tailscale executables, driven by a rules file. One small Go program (./fake) is built once
// (cached in the OS temp dir by source hash) and symlinked under each binary name.
//
// Rules live in $FAKEBIN_FIXTURES (<dir>/rules.json), first match wins; an unmatched call exits
// 99 with "fakebin: no rule". Every call is appended to <dir>/calls.jsonl.
package fakebin

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
)

// Bins are the executables Install creates.
var Bins = []string{"claude", "gh", "slackcli", "jev", "terminal-notifier", "security", "tailscale"}

// Rule is one fixture entry.
type Rule struct {
	Bin           string   `json:"bin"`
	ArgsPrefix    []string `json:"args_prefix,omitempty"`
	ArgsContains  string   `json:"args_contains,omitempty"`  // substring of the args joined by a space
	StdinContains string   `json:"stdin_contains,omitempty"` // substring of stdin
	StdoutFile    string   `json:"stdout_file,omitempty"`    // relative paths resolve against the rules dir
	Stdout        string   `json:"stdout,omitempty"`
	Stderr        string   `json:"stderr,omitempty"`
	Exit          int      `json:"exit"`
	SleepMs       int      `json:"sleep_ms,omitempty"`
	Exec          []string `json:"exec,omitempty"` // run this command instead (stdin and env passed through), e.g. setu ask
	Once          bool     `json:"once,omitempty"`
}

// Call is one line of calls.jsonl.
type Call struct {
	Bin   string            `json:"bin"`
	Args  []string          `json:"args"`
	Cwd   string            `json:"cwd"`
	Env   map[string]string `json:"env"`
	Stdin string            `json:"stdin"`
}

var (
	buildOnce sync.Once
	builtPath string
	buildErr  error
)

// Install creates the fake binaries in dir, prepends dir to PATH and points FAKEBIN_FIXTURES at
// <dir>/rules.json (written empty if absent). Everything is undone when the test ends.
func Install(t testing.TB, dir string) {
	t.Helper()
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	bin, err := build()
	if err != nil {
		t.Fatalf("fakebin: %v", err)
	}
	for _, name := range Bins {
		link := filepath.Join(dir, name)
		_ = os.Remove(link)
		if err := os.Symlink(bin, link); err != nil {
			t.Fatal(err)
		}
	}
	rules := filepath.Join(dir, "rules.json")
	if _, err := os.Stat(rules); err != nil {
		WriteRules(t, dir, nil)
	}
	t.Setenv("FAKEBIN_FIXTURES", rules)
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
}

// WriteRules replaces <dir>/rules.json.
func WriteRules(t testing.TB, dir string, rules []Rule) {
	t.Helper()
	if rules == nil {
		rules = []Rule{}
	}
	b, _ := json.MarshalIndent(rules, "", "  ")
	if err := os.WriteFile(filepath.Join(dir, "rules.json"), b, 0o644); err != nil {
		t.Fatal(err)
	}
}

// Calls reads <dir>/calls.jsonl.
func Calls(t testing.TB, dir string) []Call {
	t.Helper()
	f, err := os.Open(filepath.Join(dir, "calls.jsonl"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out []Call
	sc := bufio.NewScanner(f)
	sc.Buffer(nil, 16<<20)
	for sc.Scan() {
		var c Call
		if err := json.Unmarshal(sc.Bytes(), &c); err != nil {
			t.Fatalf("calls.jsonl: %v", err)
		}
		out = append(out, c)
	}
	return out
}

func moduleRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..", "..")
}

// build compiles ./fake once per process, caching the binary by source hash across runs.
func build() (string, error) {
	buildOnce.Do(func() {
		root := moduleRoot()
		h := sha256.New()
		var files []string
		for _, d := range []string{"internal/testutil/fakebin", "internal/testutil/fakebin/fake"} {
			m, _ := filepath.Glob(filepath.Join(root, d, "*.go"))
			files = append(files, m...)
		}
		sort.Strings(files)
		for _, f := range files {
			if strings.HasSuffix(f, "_test.go") {
				continue
			}
			b, _ := os.ReadFile(f)
			h.Write([]byte(f))
			h.Write(b)
		}
		h.Write([]byte(runtime.Version()))
		sum := hex.EncodeToString(h.Sum(nil))[:16]
		dir := filepath.Join(os.TempDir(), "setu-fakebin-"+sum)
		out := filepath.Join(dir, "fakebin")
		if _, err := os.Stat(out); err == nil {
			builtPath = out
			return
		}
		if err := os.MkdirAll(dir, 0o755); err != nil {
			buildErr = err
			return
		}
		tmp := fmt.Sprintf("%s.%d.tmp", out, os.Getpid())
		cmd := exec.Command("go", "build", "-o", tmp, "./internal/testutil/fakebin/fake")
		cmd.Dir = root
		if b, err := cmd.CombinedOutput(); err != nil {
			buildErr = fmt.Errorf("go build: %v\n%s", err, b)
			return
		}
		if err := os.Rename(tmp, out); err != nil {
			buildErr = err
			return
		}
		builtPath = out
	})
	return builtPath, buildErr
}

// Run is the fake binary's behaviour. argv0 is the invoked name (its base picks the bin).
// It returns the exit code.
func Run(argv0 string, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	bin := filepath.Base(argv0)
	fixtures := os.Getenv("FAKEBIN_FIXTURES")
	dir := filepath.Dir(fixtures)
	var in []byte
	if stdin != nil {
		if f, ok := stdin.(*os.File); ok {
			if st, err := f.Stat(); err != nil || st.Mode()&os.ModeCharDevice != 0 {
				stdin = nil // a terminal or /dev/null: nothing to read
			}
		}
		if stdin != nil {
			in, _ = io.ReadAll(stdin)
		}
	}
	if fixtures != "" {
		recordCall(dir, bin, args, in)
	}
	var rules []Rule
	if fixtures != "" {
		if b, err := os.ReadFile(fixtures); err == nil {
			_ = json.Unmarshal(b, &rules)
		}
	}
	for i, r := range rules {
		if !matches(r, bin, args, in) {
			continue
		}
		if r.Once && !claimOnce(dir, i) {
			continue
		}
		return respond(r, dir, in, stdout, stderr)
	}
	if bin == "claude" && len(args) >= 2 && args[0] == "auth" && args[1] == "status" {
		fmt.Fprintln(stdout, `{"loggedIn":true}`)
		return 0
	}
	fmt.Fprintln(stderr, "fakebin: no rule")
	return 99
}

func matches(r Rule, bin string, args []string, in []byte) bool {
	if r.Bin != bin || len(args) < len(r.ArgsPrefix) {
		return false
	}
	for i, p := range r.ArgsPrefix {
		if args[i] != p {
			return false
		}
	}
	if r.ArgsContains != "" && !strings.Contains(strings.Join(args, " "), r.ArgsContains) {
		return false
	}
	return r.StdinContains == "" || strings.Contains(string(in), r.StdinContains)
}

func respond(r Rule, dir string, in []byte, stdout, stderr io.Writer) int {
	if r.SleepMs > 0 {
		time.Sleep(time.Duration(r.SleepMs) * time.Millisecond)
	}
	if len(r.Exec) > 0 {
		cmd := exec.Command(r.Exec[0], r.Exec[1:]...)
		cmd.Stdin, cmd.Stdout, cmd.Stderr = bytes.NewReader(in), stdout, stderr
		if err := cmd.Run(); err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				return ee.ExitCode()
			}
			fmt.Fprintln(stderr, "fakebin: exec:", err)
			return 127
		}
		return 0
	}
	if r.StdoutFile != "" {
		p := r.StdoutFile
		if !filepath.IsAbs(p) {
			p = filepath.Join(dir, p)
		}
		f, err := os.Open(p)
		if err != nil {
			fmt.Fprintln(stderr, "fakebin:", err)
			return 98
		}
		_, _ = io.Copy(stdout, f)
		f.Close()
	}
	if r.Stdout != "" {
		fmt.Fprint(stdout, r.Stdout)
	}
	if r.Stderr != "" {
		fmt.Fprint(stderr, r.Stderr)
	}
	return r.Exit
}

func claimOnce(dir string, i int) bool {
	f, err := os.OpenFile(filepath.Join(dir, fmt.Sprintf(".once-%d", i)), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return false
	}
	f.Close()
	return true
}

func recordCall(dir, bin string, args []string, in []byte) {
	cwd, _ := os.Getwd()
	env := map[string]string{}
	for _, kv := range os.Environ() {
		if strings.HasPrefix(kv, "SETU_") || strings.HasPrefix(kv, "AIW_") {
			k, v, _ := strings.Cut(kv, "=")
			env[k] = v
		}
	}
	if args == nil {
		args = []string{}
	}
	b, _ := json.Marshal(Call{Bin: bin, Args: args, Cwd: cwd, Env: env, Stdin: string(in)})
	f, err := os.OpenFile(filepath.Join(dir, "calls.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	_, _ = f.Write(append(b, '\n')) // one write: appends from concurrent fakes do not interleave
	f.Close()
}
