package products

import (
	"context"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// CleanupFlags lists what removing a merged issue's worktree and branch would lose.
type CleanupFlags struct {
	Uncommitted []string `json:"uncommitted"`
	Unpushed    []string `json:"unpushed"`
}

var regenerable = []string{".next", ".venv", "__pycache__", "build", "dist", "node_modules", "target", "venv"}

type worktree struct{ path, branch string }

// worktrees returns the checkout's linked worktrees that live under <checkout>/.worktrees/.
func worktrees(ctx context.Context, checkout string) []worktree {
	out, ok := gitOut(ctx, checkout, "worktree", "list", "--porcelain")
	if !ok {
		return nil
	}
	root := realpath(filepath.Join(checkout, ".worktrees")) + string(filepath.Separator)
	var res []worktree
	var cur *worktree
	flush := func() {
		if cur != nil && strings.HasPrefix(realpath(cur.path)+string(filepath.Separator), root) {
			res = append(res, *cur)
		}
		cur = nil
	}
	for _, line := range strings.Split(out, "\n") {
		switch {
		case strings.HasPrefix(line, "worktree "):
			flush()
			cur = &worktree{path: strings.TrimPrefix(line, "worktree ")}
		case strings.HasPrefix(line, "branch ") && cur != nil:
			cur.branch = strings.TrimPrefix(strings.TrimPrefix(line, "branch "), "refs/heads/")
		}
	}
	flush()
	return res
}

type plan struct {
	wt     *worktree
	branch string
}

func makePlan(ctx context.Context, checkout string, n int) plan {
	var p plan
	prefix := strconv.Itoa(n) + "-"
	bprefix := "issue-" + prefix
	for _, w := range worktrees(ctx, checkout) {
		if strings.HasPrefix(filepath.Base(w.path), prefix) || strings.HasPrefix(w.branch, bprefix) {
			w := w
			p.wt, p.branch = &w, w.branch
			break
		}
	}
	if p.branch == "" {
		if out, ok := gitOut(ctx, checkout, "for-each-ref", "--format=%(refname:short)", "refs/heads/"+bprefix+"*"); ok && out != "" {
			p.branch = strings.SplitN(out, "\n", 2)[0]
		}
	}
	return p
}

func unquote(s string) string {
	if len(s) >= 2 && s[0] == '"' {
		if u, err := strconv.Unquote(s); err == nil {
			return u
		}
	}
	return s
}

// CleanupCheck returns nil when removing issue n's worktree and branch loses nothing.
func (r *Registry) CleanupCheck(checkout string, n int, mergedHead string) *CleanupFlags {
	return checkCleanup(context.Background(), checkout, n, mergedHead, makePlan(context.Background(), checkout, n))
}

func checkCleanup(ctx context.Context, checkout string, n int, mergedHead string, p plan) *CleanupFlags {
	f := CleanupFlags{Uncommitted: []string{}, Unpushed: []string{}}
	if p.wt != nil && isDir(p.wt.path) {
		args := []string{"status", "--porcelain", "--ignored", "-uall", "--", "."}
		for _, d := range regenerable {
			args = append(args, ":(exclude,glob)**/"+d+"/**")
		}
		if out, ok := gitOut(ctx, p.wt.path, args...); ok {
			for _, line := range strings.Split(out, "\n") {
				if len(line) > 3 {
					f.Uncommitted = append(f.Uncommitted, unquote(strings.TrimSpace(line[3:])))
				}
			}
		}
	}
	if p.branch != "" {
		args := []string{"rev-list", p.branch, "--not"}
		if mergedHead != "" {
			if _, ok := gitOut(ctx, checkout, "cat-file", "-e", mergedHead+"^{commit}"); ok {
				args = append(args, mergedHead)
			}
		}
		args = append(args, "--remotes")
		if out, ok := gitOut(ctx, checkout, args...); ok && out != "" {
			f.Unpushed = strings.Split(out, "\n")
		}
	}
	if len(f.Uncommitted) == 0 && len(f.Unpushed) == 0 {
		return nil
	}
	sort.Strings(f.Uncommitted)
	return &f
}

// Cleanup removes issue n's worktree (only under .worktrees/) and its local issue-<n>-* branch
// (never the checked-out one, never a remote). Flagged work is only removed with confirm.
func (r *Registry) Cleanup(checkout string, n int, confirm bool, mergedHead string) ([]string, *CleanupFlags, error) {
	ctx := context.Background()
	removed := []string{}
	if !isDir(checkout) {
		return removed, nil, nil
	}
	p := makePlan(ctx, checkout, n)
	flags := checkCleanup(ctx, checkout, n, mergedHead, p)
	if flags != nil && !confirm {
		return removed, flags, nil
	}
	if p.wt != nil {
		root := realpath(filepath.Join(checkout, ".worktrees")) + string(filepath.Separator)
		if isDir(p.wt.path) && strings.HasPrefix(realpath(p.wt.path)+string(filepath.Separator), root) {
			if res := git(ctx, checkout, "worktree", "remove", "--force", p.wt.path); res.Code == 0 {
				removed = append(removed, p.wt.path)
			}
		} else if !isDir(p.wt.path) {
			_ = git(ctx, checkout, "worktree", "prune")
		}
	}
	if p.branch != "" && regexp.MustCompile(`^issue-`+strconv.Itoa(n)+`-.+$`).MatchString(p.branch) {
		head, _ := gitOut(ctx, checkout, "symbolic-ref", "--short", "-q", "HEAD")
		if p.branch != head {
			if res := git(ctx, checkout, "branch", "-D", p.branch); res.Code == 0 {
				removed = append(removed, "branch "+p.branch)
			}
		}
	}
	return removed, flags, nil
}
