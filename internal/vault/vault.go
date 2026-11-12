// Package vault serves the notes vault: the 05-Work project/feature folders, a Haiku folder
// suggestion for a new idea, and the PRD.md status of a folder (W§8).
package vault

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/settings"
)

// Settings is what vault needs from settings.Store (see StoreSettings).
type Settings interface {
	VaultDir() string   // "" = none configured
	DefaultCmd() string // the default account's command
}

// StoreSettings adapts *settings.Store.
type StoreSettings struct{ St *settings.Store }

func (s StoreSettings) VaultDir() string {
	if v := s.St.Get().VaultDir; v != nil {
		return *v
	}
	return ""
}
func (s StoreSettings) DefaultCmd() string { return s.St.Default().Cmd }

// Deps wires a Service.
type Deps struct {
	Settings Settings
	// Argv resolves an account command (default claude.Argv).
	Argv func(cmd string) ([]string, error)
	// Timeout of the suggestion run (default 90 s).
	Timeout time.Duration
}

// Service is the vault.
type Service struct{ d Deps }

// New returns a Service.
func New(d Deps) *Service {
	if d.Argv == nil {
		d.Argv = claude.Argv
	}
	if d.Timeout <= 0 {
		d.Timeout = 90 * time.Second
	}
	return &Service{d: d}
}

// VaultFolder, VaultSuggestion and VaultPRD are the API §4 shapes.
type VaultFolder struct {
	Project string  `json:"project"`
	Feature *string `json:"feature"`
	Path    string  `json:"path"`
}

type VaultSuggestion struct {
	Project    string `json:"project"`
	Feature    string `json:"feature"`
	NewProject bool   `json:"new_project"`
	NewFeature bool   `json:"new_feature"`
	Why        string `json:"why"`
}

type VaultPRD struct {
	Exists bool    `json:"exists"`
	Status *string `json:"status"`
	Title  *string `json:"title"`
	Folder string  `json:"folder"`
}

const workDir = "05-Work"

var folderRe = regexp.MustCompile(`^05-Work(/[^/\x00]{1,120}){1,2}$`)

// ValidFolder reports whether f is `05-Work/<project>[/<feature>]` with no ., .. or dot-led part.
func ValidFolder(f string) bool {
	if !folderRe.MatchString(f) {
		return false
	}
	for _, part := range strings.Split(f, "/")[1:] {
		if strings.HasPrefix(part, ".") {
			return false
		}
	}
	return true
}

// Dir returns the vault directory, or an Invalid error when none is set up.
func (s *Service) Dir() (string, error) {
	v := s.d.Settings.VaultDir()
	if v == "" {
		return "", errs.Invalid("no notes vault is set up: set vault_dir in Settings")
	}
	if fi, err := os.Stat(v); err != nil || !fi.IsDir() {
		return "", errs.Invalid("the notes vault %s does not exist", v)
	}
	return v, nil
}

func subdirs(dir string) []string {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range ents {
		n := e.Name()
		if e.IsDir() && !strings.HasPrefix(n, ".") && !strings.ContainsRune(n, 0) {
			out = append(out, n)
		}
	}
	sort.Strings(out)
	return out
}

// Folders lists the project and feature folders under 05-Work, sorted by path.
func (s *Service) Folders() ([]VaultFolder, error) {
	v, err := s.Dir()
	if err != nil {
		return nil, err
	}
	return foldersOf(v), nil
}

func foldersOf(vault string) []VaultFolder {
	out := []VaultFolder{}
	for _, p := range subdirs(filepath.Join(vault, workDir)) {
		out = append(out, VaultFolder{Project: p, Path: workDir + "/" + p})
		for _, f := range subdirs(filepath.Join(vault, workDir, p)) {
			f := f
			out = append(out, VaultFolder{Project: p, Feature: &f, Path: workDir + "/" + p + "/" + f})
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out
}

var (
	statusRe = regexp.MustCompile(`\*\*Status:\*\*[ \t]*([^·\r\n]*)`)
	titleRe  = regexp.MustCompile(`(?m)^# +(.+?)\s*$`)
	prdPre   = regexp.MustCompile(`(?i)^PRD\s*[-–—:]\s*`)
)

const maxPRD = 2 << 20

// PRD reads <vault>/<folder>/PRD.md.
func (s *Service) PRD(folder string) (VaultPRD, error) {
	if !ValidFolder(folder) {
		return VaultPRD{}, errs.Invalid("folder is not a valid notes folder")
	}
	v, err := s.Dir()
	if err != nil {
		return VaultPRD{}, err
	}
	out := VaultPRD{Folder: folder}
	f, err := os.Open(filepath.Join(v, folder, "PRD.md"))
	if err != nil {
		return out, nil
	}
	defer f.Close()
	b, _ := io.ReadAll(io.LimitReader(f, maxPRD))
	out.Exists = true
	text := string(b)
	if m := statusRe.FindStringSubmatch(text); m != nil {
		if st := strings.TrimSpace(m[1]); st != "" {
			out.Status = &st
		}
	}
	if m := titleRe.FindStringSubmatch(text); m != nil {
		t := strings.TrimSpace(prdPre.ReplaceAllString(m[1], ""))
		if t != "" {
			out.Title = &t
		}
	}
	return out, nil
}

const suggestPrompt = `You file ideas into a notes vault. The vault keeps work under 05-Work/<project>/<feature>.
Existing folders (one per line):
{{FOLDERS}}

The idea:
{{IDEA}}

Pick the project and feature this idea belongs to. Reuse an existing folder when it fits; otherwise name a new one
(short, plain words, no slashes). Reply with only JSON, no other text:
{"project": "...", "feature": "...", "new_project": true|false, "new_feature": true|false, "why": "one short sentence"}`

// Suggest asks Haiku where an idea belongs.
func (s *Service) Suggest(ctx context.Context, text string) (VaultSuggestion, error) {
	text = strings.TrimSpace(text)
	if text == "" || strings.ContainsRune(text, 0) {
		return VaultSuggestion{}, errs.Invalid("text is required")
	}
	v, err := s.Dir()
	if err != nil {
		return VaultSuggestion{}, err
	}
	folders := foldersOf(v)
	var list []string
	for _, f := range folders {
		list = append(list, f.Path)
	}
	existing := "(none yet)"
	if len(list) > 0 {
		existing = strings.Join(list, "\n")
	}
	if utf8.RuneCountInString(text) > 4000 {
		text = string([]rune(text)[:4000])
	}
	argv, err := s.d.Argv(s.d.Settings.DefaultCmd())
	if err != nil {
		return VaultSuggestion{}, errs.Upstream("%v", err)
	}
	prompt := strings.NewReplacer("{{FOLDERS}}", existing, "{{IDEA}}", text).Replace(suggestPrompt)
	argv = append(argv, "-p", "--model", "haiku", "--output-format", "text", prompt)
	res := execx.Run(ctx, argv, execx.Opts{Dir: v, Timeout: s.d.Timeout})
	if res.Code != 0 {
		msg := res.LastLine()
		if msg == "" {
			msg = "claude exited with " + itoa(res.Code)
		}
		return VaultSuggestion{}, errs.Upstream("%s", msg)
	}
	sug, err := ParseSuggestion(string(res.Stdout))
	if err != nil {
		return VaultSuggestion{}, errs.Upstream("%v", err)
	}
	// the flags follow the disk, not the model
	sug.NewProject, sug.NewFeature = true, true
	for _, f := range folders {
		if f.Project == sug.Project {
			sug.NewProject = false
			if f.Feature != nil && *f.Feature == sug.Feature {
				sug.NewFeature = false
			}
		}
	}
	return sug, nil
}

func itoa(n int) string { return strconv.Itoa(n) }

type badReply string

func (e badReply) Error() string { return string(e) }

// ParseSuggestion takes the first {...} object of a model reply and cleans it: `/`, `\` and NUL
// become spaces, values are trimmed, project and feature are cut to 80 characters and why to 200;
// an empty or dot-led project or feature is rejected.
func ParseSuggestion(out string) (VaultSuggestion, error) {
	obj := firstObject(out)
	if obj == "" {
		return VaultSuggestion{}, badReply("the suggestion was not JSON")
	}
	var raw struct {
		Project    any `json:"project"`
		Feature    any `json:"feature"`
		NewProject any `json:"new_project"`
		NewFeature any `json:"new_feature"`
		Why        any `json:"why"`
	}
	if err := json.Unmarshal([]byte(obj), &raw); err != nil {
		return VaultSuggestion{}, badReply("the suggestion was not JSON")
	}
	clean := func(v any, max int) string {
		s, _ := v.(string)
		s = strings.NewReplacer("/", " ", "\\", " ", "\x00", " ").Replace(s)
		s = strings.TrimSpace(s)
		if utf8.RuneCountInString(s) > max {
			s = strings.TrimSpace(string([]rune(s)[:max]))
		}
		return s
	}
	out2 := VaultSuggestion{Project: clean(raw.Project, 80), Feature: clean(raw.Feature, 80), Why: clean(raw.Why, 200)}
	for _, n := range []string{out2.Project, out2.Feature} {
		if n == "" || strings.HasPrefix(n, ".") {
			return VaultSuggestion{}, badReply("the suggestion named no usable folder")
		}
	}
	out2.NewProject, _ = raw.NewProject.(bool)
	out2.NewFeature, _ = raw.NewFeature.(bool)
	return out2, nil
}

// firstObject returns the first balanced {...} block (strings respected), or "".
func firstObject(s string) string {
	start := strings.IndexByte(s, '{')
	for start >= 0 {
		depth, inStr, esc := 0, false, false
		for i := start; i < len(s); i++ {
			c := s[i]
			switch {
			case inStr:
				if esc {
					esc = false
				} else if c == '\\' {
					esc = true
				} else if c == '"' {
					inStr = false
				}
			case c == '"':
				inStr = true
			case c == '{':
				depth++
			case c == '}':
				depth--
				if depth == 0 {
					blk := s[start : i+1]
					if json.Valid([]byte(blk)) {
						return blk
					}
					goto next
				}
			}
		}
	next:
		idx := strings.IndexByte(s[start+1:], '{')
		if idx < 0 {
			return ""
		}
		start += 1 + idx
	}
	return ""
}

// RouteDeps is Routes' input.
type RouteDeps struct{ Svc *Service }

// Routes is the vault part of API §5.5.
func Routes(d RouteDeps) []server.Route {
	s := d.Svc
	h := server.Handle
	return []server.Route{
		{Pattern: "GET /api/vault/folders", Handler: h(func(r *http.Request) (int, any, error) {
			v, err := s.Dir()
			if err != nil {
				return 0, nil, err
			}
			return 200, map[string]any{"vault": v, "folders": foldersOf(v)}, nil
		})},
		{Pattern: "GET /api/vault/prd", Handler: h(func(r *http.Request) (int, any, error) {
			p, err := s.PRD(r.URL.Query().Get("folder"))
			return 200, p, err
		})},
		{Pattern: "POST /api/vault/suggest", Handler: h(func(r *http.Request) (int, any, error) {
			var b struct {
				Text string `json:"text"`
			}
			if err := server.Decode(r, &b); err != nil {
				return 0, nil, err
			}
			sug, err := s.Suggest(r.Context(), b.Text)
			return 200, sug, err
		})},
	}
}

// PRDFile returns the PRD.md of a notes folder, for a new repo's first PRD.
func (s *Service) PRDFile(folder string) ([]byte, error) {
	if !ValidFolder(folder) {
		return nil, errs.Invalid("folder is not a valid notes folder")
	}
	v, err := s.Dir()
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(filepath.Join(v, folder, "PRD.md"))
	if err != nil {
		return nil, errs.Invalid("%s has no PRD.md", folder)
	}
	if len(b) > maxPRD {
		return nil, errs.Invalid("PRD.md is too large")
	}
	return b, nil
}
