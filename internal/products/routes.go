package products

import (
	"context"
	"net"
	"net/http"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps are the routes' collaborators. Reg is required.
type Deps struct {
	Reg *Registry
	// ScanRoots returns the configured scan roots (settings); nil or empty means DefaultRoots.
	ScanRoots func() []string
	// Merged reports whether issue or PR n of the repo is in its snapshot's merged list and the
	// merged PR's head sha (poller).
	Merged func(repo string, n int) (mergedHead string, ok bool)
	// Pick opens the native folder picker; nil uses osascript on macOS.
	Pick func(ctx context.Context, start string) (string, error)
}

func (d Deps) roots() []string {
	if d.ScanRoots != nil {
		if r := d.ScanRoots(); len(r) > 0 {
			return r
		}
	}
	return DefaultRoots()
}

func canBrowse() bool {
	if runtime.GOOS != "darwin" {
		return false
	}
	_, err := exec.LookPath("osascript")
	return err == nil
}

// local reports whether the request came straight from this machine (not through tailscale).
func local(r *http.Request) bool {
	if r.Header.Get("Tailscale-User-Login") != "" {
		return false
	}
	h, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return false
	}
	ip := net.ParseIP(h)
	return ip != nil && ip.IsLoopback()
}

const pickerScript = `on run argv
	if (count of argv) > 0 then
		return POSIX path of (choose folder with prompt "Choose a repository folder" default location (POSIX file (item 1 of argv)))
	end if
	return POSIX path of (choose folder with prompt "Choose a repository folder")
end run`

func osaPick(ctx context.Context, start string) (string, error) {
	argv := []string{"osascript", "-e", pickerScript}
	if start != "" {
		argv = append(argv, start)
	}
	res := execx.Run(ctx, argv, execx.Opts{Timeout: 5 * time.Minute})
	if res.Code != 0 {
		return "", nil // cancelled
	}
	p := strings.TrimSpace(string(res.Stdout))
	if len(p) > 1 {
		p = strings.TrimRight(p, "/")
	}
	return p, nil
}

func reposBody(r *Registry) map[string]any { return map[string]any{"repos": r.Repos()} }

// Routes returns the repo, product and PRD routes of API §5.3.
func Routes(d Deps) []server.Route {
	reg := d.Reg
	pick := d.Pick
	if pick == nil {
		pick = osaPick
	}
	h := func(pat string, f server.HandlerFunc) server.Route {
		return server.Route{Pattern: pat, Handler: server.Handle(f)}
	}
	return []server.Route{
		h("GET /api/repos", func(r *http.Request) (int, any, error) {
			return 0, map[string]any{"repos": reg.Repos(), "can_browse": canBrowse(), "scan_roots": d.roots()}, nil
		}),
		h("POST /api/repos", func(r *http.Request) (int, any, error) {
			var in struct{ Slug, Path string }
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			rp, err := reg.RegisterRepo(r.Context(), in.Slug, in.Path)
			if err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"repo": rp, "repos": reg.Repos()}, nil
		}),
		h("DELETE /api/repos/{owner}/{name}", func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, errs.NotFound("%s", err.Error())
			}
			if err := reg.RemoveRepo(slug); err != nil {
				return 0, nil, err
			}
			return 0, reposBody(reg), nil
		}),
		h("POST /api/repos/scan", func(r *http.Request) (int, any, error) {
			var in struct {
				Roots []string `json:"roots"`
			}
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			roots := in.Roots
			if len(roots) == 0 {
				roots = d.roots()
			}
			res, err := reg.Scan(r.Context(), roots)
			return 0, res, err
		}),
		h("POST /api/repos/check", func(r *http.Request) (int, any, error) {
			return 0, map[string]any{"problems": reg.Check(r.Context())}, nil
		}),
		h("POST /api/repos/browse", func(r *http.Request) (int, any, error) {
			var in struct {
				Start string `json:"start"`
			}
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			if d.Pick == nil && (!canBrowse() || !local(r)) {
				return 0, nil, errs.Forbidden("folder picker is only available locally on macOS")
			}
			start := ""
			if in.Start != "" && filepath.IsAbs(in.Start) && !hasDotDot(in.Start) && isDir(in.Start) {
				start = in.Start
			}
			p, err := pick(r.Context(), start)
			if err != nil {
				return 0, nil, err
			}
			if p == "" {
				return 0, map[string]any{"path": nil}, nil
			}
			return 0, map[string]any{"path": p}, nil
		}),
		h("POST /api/repos/{owner}/{name}/cleanup", func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, errs.NotFound("%s", err.Error())
			}
			var in struct {
				Issue   int  `json:"issue"`
				Confirm bool `json:"confirm"`
			}
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			if in.Issue < 1 || !in.Confirm {
				return 0, nil, errs.Invalid("issue must be a positive integer and confirm must be true")
			}
			key, ok := findKey(reg.checkouts(), slug)
			if !ok {
				return 0, nil, errs.NotFound("%s is not a registered repo", slug)
			}
			head, merged := "", false
			if d.Merged != nil {
				head, merged = d.Merged(key, in.Issue)
			}
			if !merged {
				return 0, nil, errs.Conflict("#"+itoa(in.Issue)+"'s PR is not merged", nil)
			}
			removed, _, err := reg.Cleanup(reg.checkouts()[key], in.Issue, true, head)
			if err != nil {
				return 0, nil, err
			}
			reg.changed("registry", key)
			return 0, map[string]any{"removed": removed}, nil
		}),
		h("GET /api/products", func(r *http.Request) (int, any, error) {
			return 0, map[string]any{"products": reg.Products()}, nil
		}),
		h("POST /api/products", func(r *http.Request) (int, any, error) {
			var in struct {
				Path string `json:"path"`
			}
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			p, err := reg.Register(r.Context(), in.Path)
			if err != nil {
				return 0, nil, err
			}
			return http.StatusCreated, p, nil
		}),
		h("DELETE /api/products/{owner}/{name}", func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, errs.NotFound("%s", err.Error())
			}
			if err := reg.RemoveProduct(slug); err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"products": reg.Products()}, nil
		}),
		h("GET /api/products/{owner}/{name}/prds", func(r *http.Request) (int, any, error) {
			slug, err := server.Slug(r)
			if err != nil {
				return 0, nil, errs.NotFound("%s", err.Error())
			}
			prds, err := reg.PRDs(slug)
			if err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"prds": prds}, nil
		}),
		h("GET /api/prd", func(r *http.Request) (int, any, error) {
			repo, path := r.URL.Query().Get("repo"), r.URL.Query().Get("path")
			if !slugRe.MatchString(repo) {
				return 0, nil, errs.Invalid("repo must look like owner/repo")
			}
			f, err := reg.ReadPRD(repo, path)
			return 0, f, err
		}),
		h("PUT /api/prd", func(r *http.Request) (int, any, error) {
			var in struct {
				Repo    string `json:"repo"`
				Path    string `json:"path"`
				Text    string `json:"text"`
				BaseSHA string `json:"base_sha"`
			}
			if err := server.Decode(r, &in); err != nil {
				return 0, nil, err
			}
			if !slugRe.MatchString(in.Repo) {
				return 0, nil, errs.Invalid("repo must look like owner/repo")
			}
			f, err := reg.SavePRD(r.Context(), in.Repo, in.Path, in.Text, in.BaseSHA)
			return 0, f, err
		}),
	}
}
