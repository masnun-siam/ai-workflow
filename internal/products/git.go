package products

import (
	"context"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
)

const gitTimeout = 10 * time.Second

var (
	slugRe   = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	originRe = regexp.MustCompile(`github\.com(?::\d+)?[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$`)
)

// git runs git -C dir args... with a 10 s timeout and no terminal prompts.
func git(ctx context.Context, dir string, args ...string) execx.Result {
	argv := append([]string{"git", "-C", dir}, args...)
	return execx.Run(ctx, argv, execx.Opts{Timeout: gitTimeout, Env: []string{"GIT_TERMINAL_PROMPT=0", "GIT_OPTIONAL_LOCKS=0"}})
}

func gitOut(ctx context.Context, dir string, args ...string) (string, bool) {
	r := git(ctx, dir, args...)
	return strings.TrimSpace(string(r.Stdout)), r.Code == 0
}

func hasDotDot(p string) bool {
	for _, seg := range strings.Split(filepath.ToSlash(p), "/") {
		if seg == ".." {
			return true
		}
	}
	return false
}

func realpath(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return filepath.Clean(p)
}

// validateRepo checks that path is an absolute, ..-free directory inside a git checkout and
// returns the real path of the checkout's top level.
func validateRepo(ctx context.Context, path string) (string, error) {
	if path == "" || strings.ContainsRune(path, 0) {
		return "", errs.Invalid("path must be a non-empty string")
	}
	if !filepath.IsAbs(path) {
		return "", errs.Invalid("path must be absolute: %s", path)
	}
	if hasDotDot(path) {
		return "", errs.Invalid("path must not contain '..': %s", path)
	}
	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		return "", errs.Invalid("not a folder: %s", path)
	}
	if st, err := os.Stat(real); err != nil || !st.IsDir() {
		return "", errs.Invalid("not a folder: %s", path)
	}
	top, ok := gitOut(ctx, real, "rev-parse", "--show-toplevel")
	if !ok || top == "" {
		return "", errs.Invalid("not a git repository: %s", path)
	}
	return realpath(top), nil
}

// originSlug parses owner/name from the origin remote ("" when it is not a GitHub URL).
func originSlug(ctx context.Context, top string) string {
	u, ok := gitOut(ctx, top, "remote", "get-url", "origin")
	if !ok {
		return ""
	}
	m := originRe.FindStringSubmatch(u)
	if m == nil {
		return ""
	}
	return m[1] + "/" + m[2]
}

func eqFold(a, b string) bool { return strings.EqualFold(a, b) }

// findKey finds slug in m case-insensitively and returns the registered spelling.
func findKey(m map[string]string, slug string) (string, bool) {
	if _, ok := m[slug]; ok {
		return slug, true
	}
	for k := range m {
		if eqFold(k, slug) {
			return k, true
		}
	}
	return "", false
}

func exists(p string) bool {
	_, err := os.Lstat(p)
	return err == nil
}

func isDir(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}
