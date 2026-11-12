// Package review runs peer-review panels: one headless, read-only peer-reviewer session per lens
// reviews one artifact, a root session (the author) revises it after each round, and the panel is
// done when every active lens says `Verdict: approve` in the same round (W§5).
package review

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

//go:embed shipped.json
var shippedJSON []byte

// Lens is one reviewing lens: a short focus line and the checklist prompt.
type Lens struct {
	Focus  string `json:"focus"`
	Prompt string `json:"prompt"`
}

// Config is the effective peer-review configuration.
type Config struct {
	MaxRounds     int                 `json:"max_rounds"`
	DefaultLenses []string            `json:"default_lenses"`
	Kinds         map[string][]string `json:"kinds"` // kind -> offered lenses
	Lenses        map[string]Lens     `json:"lenses"`
}

type shippedFile struct {
	MaxRounds     int      `json:"max_rounds"`
	DefaultLenses []string `json:"default_lenses"`
	Kinds         map[string]struct {
		Offer []string `json:"offer"`
	} `json:"kinds"`
	Lenses map[string]Lens `json:"lenses"`
}

// Shipped returns the defaults compiled into the binary.
func Shipped() Config {
	var f shippedFile
	if err := json.Unmarshal(shippedJSON, &f); err != nil {
		panic("review: bad shipped.json: " + err.Error())
	}
	c := Config{MaxRounds: f.MaxRounds, DefaultLenses: f.DefaultLenses, Kinds: map[string][]string{}, Lenses: f.Lenses}
	for k, v := range f.Kinds {
		c.Kinds[k] = v.Offer
	}
	return c
}

// ReviewConfig is the settings API shape (API §4).
type ReviewConfig struct {
	MaxRounds     int               `json:"max_rounds"`
	DefaultLenses []string          `json:"default_lenses"`
	Lenses        map[string]string `json:"lenses"`
	Shipped       ShippedConfig     `json:"shipped"`
	Overridden    bool              `json:"overridden"`
}

// ShippedConfig is the shipped part of ReviewConfig.
type ShippedConfig struct {
	MaxRounds     int               `json:"max_rounds"`
	DefaultLenses []string          `json:"default_lenses"`
	Lenses        map[string]string `json:"lenses"`
}

// ReviewOffers is GET /api/review/offers.
type ReviewOffers struct {
	Default   []string            `json:"default"`
	MaxRounds int                 `json:"max_rounds"`
	Kinds     map[string][]string `json:"kinds"`
}

const configFile = "config.json"

var lensName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`)

// overlay is DATA/config.json's peer_review object.
type overlay struct {
	MaxRounds     *int     `json:"max_rounds"`
	DefaultLenses []string `json:"default_lenses"`
	Kinds         map[string]struct {
		Offer []string `json:"offer"`
	} `json:"kinds"`
	Lenses map[string]map[string]any `json:"lenses"`
}

func readOverlay(h *home.Home) (ov overlay, present bool) {
	var top map[string]json.RawMessage
	if err := home.ReadJSON(h.Path(configFile), &top); err != nil {
		return ov, false
	}
	raw, ok := top["peer_review"]
	if !ok {
		return ov, false
	}
	if json.Unmarshal(raw, &ov) != nil {
		// a field of the wrong type: take what parses, field by field
		var m map[string]json.RawMessage
		_ = json.Unmarshal(raw, &m)
		ov = overlay{}
		_ = json.Unmarshal(m["max_rounds"], &ov.MaxRounds)
		_ = json.Unmarshal(m["default_lenses"], &ov.DefaultLenses)
		_ = json.Unmarshal(m["kinds"], &ov.Kinds)
		_ = json.Unmarshal(m["lenses"], &ov.Lenses)
	}
	return ov, true
}

// LoadConfig overlays DATA/config.json's peer_review on the shipped defaults, key by key and,
// for lenses, field by field. Invalid overlay values are ignored.
func LoadConfig(h *home.Home) (cfg Config, overridden bool) {
	cfg = Shipped()
	ov, present := readOverlay(h)
	if !present {
		return cfg, false
	}
	if ov.MaxRounds != nil && *ov.MaxRounds >= 1 && *ov.MaxRounds <= 20 {
		cfg.MaxRounds = *ov.MaxRounds
		overridden = true
	}
	for name, f := range ov.Lenses {
		if !lensName.MatchString(name) {
			continue
		}
		l := cfg.Lenses[name]
		if s, ok := f["prompt"].(string); ok && strings.TrimSpace(s) != "" {
			l.Prompt = s
		}
		if s, ok := f["focus"].(string); ok && strings.TrimSpace(s) != "" {
			l.Focus = s
		}
		if l.Prompt == "" {
			continue
		}
		cfg.Lenses[name] = l
		overridden = true
	}
	for kind, v := range ov.Kinds {
		cfg.Kinds[kind] = v.Offer
		overridden = true
	}
	if len(ov.DefaultLenses) > 0 {
		cfg.DefaultLenses = ov.DefaultLenses
		overridden = true
	}
	// offers only name lenses that exist; a lens no kind offers joins "custom"
	offered := map[string]bool{}
	for k, offer := range cfg.Kinds {
		var keep []string
		for _, l := range offer {
			if _, ok := cfg.Lenses[l]; ok {
				keep = append(keep, l)
				offered[l] = true
			}
		}
		cfg.Kinds[k] = keep
	}
	for _, name := range sortedKeys(cfg.Lenses) {
		if !offered[name] {
			cfg.Kinds["custom"] = append(cfg.Kinds["custom"], name)
		}
	}
	var def []string
	for _, l := range cfg.DefaultLenses {
		if _, ok := cfg.Lenses[l]; ok {
			def = append(def, l)
		}
	}
	if len(def) == 0 {
		def = Shipped().DefaultLenses
	}
	cfg.DefaultLenses = def
	return cfg, overridden
}

// Offers is GET /api/review/offers.
func (c Config) Offers() ReviewOffers {
	k := map[string][]string{}
	for kind, o := range c.Kinds {
		k[kind] = append([]string{}, o...)
	}
	return ReviewOffers{Default: append([]string{}, c.DefaultLenses...), MaxRounds: c.MaxRounds, Kinds: k}
}

// View is the settings API shape.
func View(h *home.Home) ReviewConfig {
	cfg, over := LoadConfig(h)
	sh := Shipped()
	return ReviewConfig{
		MaxRounds: cfg.MaxRounds, DefaultLenses: cfg.DefaultLenses, Lenses: promptsOf(cfg.Lenses), Overridden: over,
		Shipped: ShippedConfig{MaxRounds: sh.MaxRounds, DefaultLenses: sh.DefaultLenses, Lenses: promptsOf(sh.Lenses)},
	}
}

func promptsOf(m map[string]Lens) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = v.Prompt
	}
	return out
}

// CheckLenses dedupes (order kept) and checks the picked lenses against the kind's offer.
func (c Config) CheckLenses(kind string, picked []string) ([]string, error) {
	offer, ok := c.Kinds[kind]
	if !ok {
		kinds := sortedKeys(c.Kinds)
		return nil, errs.Invalid("%s has no peer review; one of %s", kind, strings.Join(kinds, ", "))
	}
	seen := map[string]bool{}
	var out, bad []string
	for _, l := range picked {
		if seen[l] {
			continue
		}
		seen[l] = true
		out = append(out, l)
		if !contains(offer, l) {
			bad = append(bad, l)
		}
	}
	if len(out) == 0 || len(bad) > 0 {
		got := "none"
		if len(bad) > 0 {
			got = strings.Join(bad, ", ")
		}
		return nil, errs.Invalid("%s offers the lenses %s; got %s", kind, strings.Join(offer, ", "), got)
	}
	return out, nil
}

// SaveConfigInput is PUT /api/settings/review (a reset is {reset:true}).
type SaveConfigInput struct {
	Reset         bool              `json:"reset"`
	MaxRounds     *json.RawMessage  `json:"max_rounds"`
	DefaultLenses []string          `json:"default_lenses"`
	Lenses        map[string]string `json:"lenses"`
}

// SaveConfig validates and stores the overlay (or removes it) and returns the new view.
func SaveConfig(h *home.Home, in SaveConfigInput) (ReviewConfig, error) {
	path := h.Path(configFile)
	if in.Reset {
		_, err := home.UpdateJSON(path, func(m *map[string]any) error {
			delete(*m, "peer_review")
			return nil
		})
		if err != nil {
			return ReviewConfig{}, err
		}
		return View(h), nil
	}
	mr, err := intOf(in.MaxRounds)
	if err != nil || mr < 1 || mr > 20 {
		return ReviewConfig{}, errs.Invalid("max_rounds must be an integer from 1 to 20")
	}
	sh := Shipped()
	lenses := map[string]any{}
	known := map[string]bool{}
	for k := range sh.Lenses {
		known[k] = true
	}
	for name, p := range in.Lenses {
		if !lensName.MatchString(name) {
			return ReviewConfig{}, errs.Invalid("lens name %q must match [A-Za-z0-9][A-Za-z0-9_-]{0,39}", name)
		}
		if strings.TrimSpace(p) == "" || len(p) > 8000 || strings.ContainsRune(p, 0) {
			return ReviewConfig{}, errs.Invalid("lens %q needs a prompt of 1 to 8000 characters", name)
		}
		known[name] = true
		lenses[name] = map[string]any{"prompt": p}
	}
	if len(in.DefaultLenses) == 0 {
		return ReviewConfig{}, errs.Invalid("default_lenses needs at least one lens")
	}
	seen := map[string]bool{}
	var def []string
	for _, l := range in.DefaultLenses {
		if !known[l] {
			return ReviewConfig{}, errs.Invalid("default_lenses names an unknown lens: %q", l)
		}
		if !seen[l] {
			seen[l] = true
			def = append(def, l)
		}
	}
	_, err = home.UpdateJSON(path, func(m *map[string]any) error {
		if *m == nil {
			*m = map[string]any{}
		}
		(*m)["peer_review"] = map[string]any{"max_rounds": mr, "default_lenses": def, "lenses": lenses}
		return nil
	})
	if err != nil {
		return ReviewConfig{}, err
	}
	return View(h), nil
}

// intOf reads a strict JSON integer (no bool, no fraction, no string).
func intOf(raw *json.RawMessage) (int, error) {
	if raw == nil {
		return 0, fmt.Errorf("missing")
	}
	s := strings.TrimSpace(string(*raw))
	var n int
	if _, err := fmt.Sscanf(s, "%d", &n); err != nil || fmt.Sprint(n) != s {
		return 0, fmt.Errorf("not an integer")
	}
	return n, nil
}

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
