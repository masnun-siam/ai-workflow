// Package prompts is the registry of workflow steps: blubird skills (passed through as slash
// commands) and setu's four built-in prompts (embedded, extracted to ~/.setu/prompts/<version>/).
package prompts

import (
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
	builtin "github.com/masnun-siam/setu/prompts"
)

type Source string

const (
	SrcBlubird Source = "blubird"
	SrcSetu    Source = "setu"
)

type RunsIn string

const (
	InDocs  RunsIn = "docs"
	InIssue RunsIn = "issue"
	InRepo  RunsIn = "repo"
	InNone  RunsIn = "none"
)

type Step struct {
	ID       string `json:"id"`
	Source   Source `json:"source"`
	Skill    string `json:"skill"`
	RunsIn   RunsIn `json:"runs_in"`
	Stage    string `json:"stage"`
	Label    string `json:"label"`
	ArgsHint string `json:"args_hint"`
}

// Prompt is what a session runs: Display is shown to people, Text is what claude receives.
type Prompt struct{ Step, Display, Text string }

const keepVersions = 5

type Registry struct {
	root   string
	steps  []Step
	byID   map[string]Step
	bodies map[string]string // setu skill -> SKILL.md without frontmatter
	agents map[string]agent
	bb     *blubird.Manager
}

type agent struct {
	body  string
	tools []string
}

// Load extracts the embedded prompts to <home>/prompts/<version>/ (skipped when that directory
// already holds the same content), prunes old versions and returns the registry.
func Load(h *home.Home, version string, bb *blubird.Manager) (*Registry, error) {
	if version == "" || strings.ContainsAny(version, `/\`) || version == "." || version == ".." {
		version = "dev"
	}
	base := h.Path("prompts")
	root := filepath.Join(base, version)
	if err := extract(builtin.FS, root); err != nil {
		return nil, err
	}
	prune(base, version)
	r := &Registry{root: root, steps: defaultSteps(), byID: map[string]Step{}, bodies: map[string]string{}, agents: map[string]agent{}, bb: bb}
	for _, s := range r.steps {
		r.byID[s.ID] = s
		if s.Source == SrcSetu {
			b, err := fs.ReadFile(builtin.FS, path.Join(s.Skill, "SKILL.md"))
			if err != nil {
				return nil, err
			}
			fm, body := splitFrontmatter(string(b))
			_ = fm
			r.bodies[s.Skill] = strings.TrimSpace(body)
		}
	}
	for _, name := range []string{"peer-reviewer", "away-answerer"} {
		b, err := fs.ReadFile(builtin.FS, path.Join("agents", name+".md"))
		if err != nil {
			return nil, err
		}
		fm, body := splitFrontmatter(string(b))
		r.agents[name] = agent{body: strings.TrimSpace(body), tools: parseTools(fm)}
	}
	return r, nil
}

func (r *Registry) Steps() []Step { return append([]Step(nil), r.steps...) }

func (r *Registry) Step(id string) (Step, bool) { s, ok := r.byID[id]; return s, ok }

// Root is the extraction directory (`setu paths` plugin_root).
func (r *Registry) Root() string { return r.root }

// Agent returns an agent's instructions and its allowed tools.
func (r *Registry) Agent(name string) (string, []string, error) {
	a, ok := r.agents[name]
	if !ok {
		return "", nil, errs.NotFound("unknown agent %q", name)
	}
	return a.body, append([]string(nil), a.tools...), nil
}

// Available is nil when the step can run: a blubird step needs blubird installed.
func (r *Registry) Available(stepID string) error {
	s, ok := r.byID[stepID]
	if !ok {
		return errs.NotFound("unknown step %q", stepID)
	}
	if s.Source == SrcBlubird && (r.bb == nil || !r.bb.Status().Installed) {
		return errs.Conflict("blubird is not installed", nil)
	}
	return nil
}

// splitFrontmatter separates a leading `---` block from the rest.
func splitFrontmatter(s string) (front, body string) {
	s = strings.TrimPrefix(s, "\xef\xbb\xbf")
	if !strings.HasPrefix(s, "---\n") {
		return "", s
	}
	rest := s[4:]
	i := strings.Index(rest, "\n---")
	if i < 0 {
		return "", s
	}
	front = rest[:i]
	body = rest[i+4:]
	if j := strings.IndexByte(body, '\n'); j >= 0 {
		body = body[j+1:]
	} else {
		body = ""
	}
	return front, body
}

func parseTools(front string) []string {
	for _, ln := range strings.Split(front, "\n") {
		if v, ok := strings.CutPrefix(ln, "tools:"); ok {
			var out []string
			for _, t := range strings.Split(strings.TrimSpace(v), ", ") {
				if t = strings.TrimSpace(t); t != "" {
					out = append(out, t)
				}
			}
			return out
		}
	}
	return nil
}

// ---- extraction ----

const marker = ".extracted"

func contentHash(fsys fs.FS) (string, error) {
	h := sha256.New()
	err := fs.WalkDir(fsys, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		b, err := fs.ReadFile(fsys, p)
		if err != nil {
			return err
		}
		h.Write([]byte(p + "\x00"))
		h.Write(b)
		h.Write([]byte{0})
		return nil
	})
	return hex.EncodeToString(h.Sum(nil)), err
}

// extract writes fsys under root unless the marker already carries the same content hash.
// Files under scripts/ are executable.
func extract(fsys fs.FS, root string) error {
	sum, err := contentHash(fsys)
	if err != nil {
		return err
	}
	if b, err := os.ReadFile(filepath.Join(root, marker)); err == nil && strings.TrimSpace(string(b)) == sum {
		return nil
	}
	err = fs.WalkDir(fsys, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		dst := filepath.Join(root, filepath.FromSlash(p))
		if d.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		b, err := fs.ReadFile(fsys, p)
		if err != nil {
			return err
		}
		perm := os.FileMode(0o644)
		if strings.Contains("/"+p, "/scripts/") {
			perm = 0o755
		}
		return home.AtomicWrite(dst, b, perm)
	})
	if err != nil {
		return err
	}
	return home.AtomicWrite(filepath.Join(root, marker), []byte(sum+"\n"), 0o644)
}

// prune deletes version directories beyond the newest keepVersions; the current one is always kept.
func prune(base, current string) {
	ents, err := os.ReadDir(base)
	if err != nil {
		return
	}
	type v struct {
		name string
		mod  int64
	}
	var vs []v
	for _, e := range ents {
		if !e.IsDir() {
			continue
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		vs = append(vs, v{e.Name(), fi.ModTime().UnixNano()})
	}
	sort.Slice(vs, func(i, j int) bool {
		if vs[i].name == current || vs[j].name == current {
			return vs[i].name == current
		}
		return vs[i].mod > vs[j].mod
	})
	for i, x := range vs {
		if i >= keepVersions {
			_ = os.RemoveAll(filepath.Join(base, x.name))
		}
	}
}
