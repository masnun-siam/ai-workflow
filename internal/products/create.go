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

var (
	repoNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$`)
	ownerRe    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}$`)
)

// CreateLocal makes a new git repository <parent>/<name> with a README (and the PRD, when given, at
// docs/prds/<prdName>.md), commits it on main and registers it as local/<name>. Publish puts it on
// GitHub later.
func (r *Registry) CreateLocal(ctx context.Context, name, parent string, prd []byte, prdName string) (Repo, error) {
	if !repoNameRe.MatchString(name) || name == "." || name == ".." {
		return Repo{}, errs.Invalid("name may use letters, digits, '.', '_' and '-'")
	}
	if !filepath.IsAbs(parent) || hasDotDot(parent) || !isDir(parent) {
		return Repo{}, errs.Invalid("parent must be an existing absolute folder")
	}
	if _, taken := findKey(r.checkouts(), "local/"+name); taken {
		return Repo{}, errs.Conflict("local/"+name+" is already registered", nil)
	}
	dir := filepath.Join(parent, name)
	if exists(dir) {
		return Repo{}, errs.Conflict(dir+" already exists", nil)
	}
	if prdName == "" {
		prdName = strings.ToLower(name)
	}
	if !repoNameRe.MatchString(prdName) {
		return Repo{}, errs.Invalid("bad PRD name")
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return Repo{}, err
	}
	fail := func(msg string, res execx.Result) (Repo, error) {
		_ = os.RemoveAll(dir)
		return Repo{}, errs.Upstream("%s: %s", msg, strings.TrimSpace(string(res.Stderr)+string(res.Stdout)))
	}
	if res := git(ctx, dir, "init", "-q", "-b", "main"); res.Code != 0 {
		return fail("git init failed", res)
	}
	files := []string{"README.md"}
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("# "+name+"\n"), 0o644); err != nil {
		_ = os.RemoveAll(dir)
		return Repo{}, err
	}
	if len(prd) > 0 {
		p := filepath.Join(dir, "docs", "prds", prdName+".md")
		_ = os.MkdirAll(filepath.Dir(p), 0o755)
		if err := os.WriteFile(p, prd, 0o644); err != nil {
			_ = os.RemoveAll(dir)
			return Repo{}, err
		}
		files = append(files, "docs/prds/"+prdName+".md")
	}
	if res := git(ctx, dir, append([]string{"add", "--"}, files...)...); res.Code != 0 {
		return fail("git add failed", res)
	}
	if res := git(ctx, dir, "commit", "-q", "-m", "Start "+name); res.Code != 0 {
		return fail("git commit failed (is user.name/user.email set?)", res)
	}
	top := realpath(dir)
	r.mu.Lock()
	err := r.setCheckouts(map[string]string{"local/" + name: top})
	r.mu.Unlock()
	if err != nil {
		return Repo{}, err
	}
	r.changed("registry", "local/"+name)
	return Repo{Slug: "local/" + name, Path: top}, nil
}

// ghRun runs gh with a timeout; it is a var so tests can fake it.
var ghRun = func(ctx context.Context, args []string, timeout time.Duration) execx.Result {
	return execx.Run(ctx, append([]string{"gh"}, args...), execx.Opts{Timeout: timeout, Env: []string{"GH_PROMPT_DISABLED=1"}})
}

// Owners lists where a repo can be published: the signed-in gh user, then their organisations.
func (r *Registry) Owners(ctx context.Context) ([]string, error) {
	res := ghRun(ctx, []string{"api", "user", "-q", ".login"}, 20*time.Second)
	if res.Code != 0 {
		return nil, errs.Upstream("gh: %s", res.LastLine())
	}
	out := []string{strings.TrimSpace(string(res.Stdout))}
	orgs := ghRun(ctx, []string{"api", "user/orgs", "-q", ".[].login"}, 20*time.Second)
	if orgs.Code == 0 {
		for _, l := range strings.Split(string(orgs.Stdout), "\n") {
			if l = strings.TrimSpace(l); l != "" {
				out = append(out, l)
			}
		}
	}
	return out, nil
}

// Publish creates owner/name on GitHub from a local/<x> checkout, sets it as origin and pushes;
// the registry then renames the checkout to owner/name.
func (r *Registry) Publish(ctx context.Context, slug, owner, name string, private bool) (Repo, error) {
	if !strings.HasPrefix(slug, "local/") {
		return Repo{}, errs.Invalid("only a local/ repo can be published")
	}
	if !ownerRe.MatchString(owner) || !repoNameRe.MatchString(name) {
		return Repo{}, errs.Invalid("owner and name must be valid GitHub names")
	}
	k, ok := findKey(r.checkouts(), slug)
	if !ok {
		return Repo{}, errs.NotFound("%s is not registered", slug)
	}
	dir := r.checkouts()[k]
	if !isDir(dir) {
		return Repo{}, errs.Invalid("%s's folder is missing: %s", slug, dir)
	}
	vis := "--public"
	if private {
		vis = "--private"
	}
	res := ghRun(ctx, []string{"repo", "create", owner + "/" + name, vis, "--source", dir, "--remote", "origin", "--push"}, 2*time.Minute)
	if res.Code != 0 {
		return Repo{}, errs.Upstream("gh repo create: %s", res.LastLine())
	}
	r.promoteLocal(ctx)
	full := owner + "/" + name
	if k2, ok := findKey(r.checkouts(), full); ok {
		return Repo{Slug: k2, Path: r.checkouts()[k2]}, nil
	}
	return Repo{Slug: full, Path: dir}, nil
}
