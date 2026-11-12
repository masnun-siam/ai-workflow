// Package claude knows how to run and read the claude CLI: account argv and config dirs,
// the login preflight, stream-json parsing, transcript copy and the usage meters.
package claude

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/settings"
)

// Argv is the absolute argv prefix of an account command (S§3.1): `cc` becomes `cc-profile`
// and the first token is resolved with LookPath. It is never run through a shell.
func Argv(cmd string) ([]string, error) { return settings.ResolveCmd(cmd) }

// ConfigDir is the claude config dir an account command runs under.
func ConfigDir(cmd string) string {
	u, _ := os.UserHomeDir()
	if toks, err := settings.Split(cmd); err == nil && len(toks) > 1 && (toks[0] == "cc" || toks[0] == "cc-profile") {
		return filepath.Join(u, ".claude-profiles", toks[1])
	}
	if d := os.Getenv("CLAUDE_CONFIG_DIR"); d != "" {
		return d
	}
	return filepath.Join(u, ".claude")
}

var nonAlnum = regexp.MustCompile(`[^A-Za-z0-9]`)

const authTimeout = 30 * time.Second

type authStatus struct {
	LoggedIn *bool  `json:"loggedIn"`
	Email    string `json:"email"`
	Account  string `json:"account"`
}

// authCheck runs `<argv> auth status --json`. err is the "auth status check failed" cause
// (timeout, exec or JSON error); status is nil when the output was not an object.
func authCheck(ctx context.Context, exe []string) (st *authStatus, err error) {
	r := execx.Run(ctx, append(append([]string{}, exe...), "auth", "status", "--json"), execx.Opts{Timeout: authTimeout})
	if r.Code == 124 || r.Code == 127 {
		return nil, fmt.Errorf("%s", strings.TrimSpace(string(r.Stderr)))
	}
	var raw any
	if e := json.Unmarshal(r.Stdout, &raw); e != nil {
		return nil, e
	}
	if _, ok := raw.(map[string]any); !ok {
		return &authStatus{}, nil
	}
	st = &authStatus{}
	_ = json.Unmarshal(r.Stdout, st) // field type mismatches leave LoggedIn nil = not logged in
	return st, nil
}

// Preflight checks that the account command exists and is logged in (S§1.3). Failures are
// errs.Upstream with the user-facing message.
func Preflight(ctx context.Context, cmd string, isDefault bool) error {
	exe, err := Argv(cmd)
	if err != nil {
		if isDefault {
			return errs.Upstream("claude CLI not found on PATH")
		}
		return errs.Upstream("claude command '%s' unusable: %s", cmd, err)
	}
	login := "claude CLI is not logged in, run `claude auth login`"
	if !isDefault {
		login = fmt.Sprintf("claude CLI is not logged in, run `%s auth login`", cmd)
	}
	st, err := authCheck(ctx, exe)
	if err != nil {
		return errs.Upstream("%s (auth status check failed: %s)", login, err)
	}
	if st.LoggedIn == nil || !*st.LoggedIn {
		return errs.Upstream("%s", login)
	}
	return nil
}

// TestAccount runs the login check for the Settings "test" button. It never errors.
func TestAccount(ctx context.Context, cmd string) (ok bool, msg string) {
	exe, err := Argv(cmd)
	if err != nil {
		return false, "auth status check failed: " + err.Error()
	}
	st, err := authCheck(ctx, exe)
	if err != nil {
		return false, "auth status check failed: " + err.Error()
	}
	if st.LoggedIn == nil || !*st.LoggedIn {
		return false, "not logged in"
	}
	who := st.Email
	if who == "" {
		who = st.Account
	}
	return true, strings.TrimSpace("logged in " + who)
}

// ProjectDirName is how claude names a cwd under <config>/projects: the real path with every
// non-alphanumeric byte turned into "-".
func ProjectDirName(cwd string) string {
	if r, err := filepath.EvalSymlinks(cwd); err == nil {
		cwd = r
	}
	return nonAlnum.ReplaceAllString(cwd, "-")
}

// CopyTranscript copies a session transcript from one account's config dir to another's
// (S§1.12) so a stopped session can resume on a different account.
func CopyTranscript(fromCmd, toCmd, cwd, sessionID string) error {
	if sessionID == "" || strings.ContainsAny(sessionID, "/\\\x00") || sessionID == "." || sessionID == ".." {
		return errs.Invalid("bad session id")
	}
	slug := ProjectDirName(cwd)
	src := filepath.Join(ConfigDir(fromCmd), "projects", slug, sessionID+".jsonl")
	dstDir := filepath.Join(ConfigDir(toCmd), "projects", slug)
	dst := filepath.Join(dstDir, sessionID+".jsonl")
	if src == dst {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return errs.Conflict("transcript not found at "+src, nil)
	}
	defer in.Close()
	if err := os.MkdirAll(dstDir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dstDir, ".copy-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, in); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), dst)
}
