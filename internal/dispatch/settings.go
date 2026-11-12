package dispatch

import (
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
)

// MaxCostLimit is the sanity bound of the max_cost setting (USD).
const MaxCostLimit = 10000

var (
	reBranch    = regexp.MustCompile(`^[A-Za-z0-9._/-]{1,100}$`)
	reModel     = regexp.MustCompile(`^[A-Za-z0-9][\w.\[\]:/-]{0,79}$`)
	efforts     = map[string]bool{"low": true, "medium": true, "high": true, "xhigh": true, "max": true}
	settingKeys = []string{"max", "grind", "ci", "auto_merge", "skip_approval", "feature_branch", "base_branch",
		"model", "effort", "account", "max_cost"}
)

// ParseSettings turns a JSON object into a settings map (numbers kept as json.Number).
func ParseSettings(raw json.RawMessage) (map[string]any, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return map[string]any{}, nil
	}
	dec := json.NewDecoder(bytesReader(raw))
	dec.UseNumber()
	var m map[string]any
	if err := dec.Decode(&m); err != nil || m == nil {
		return nil, errs.Invalid("settings must be an object")
	}
	return m, nil
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, _ := x.Float64()
		return f != 0
	case int:
		return x != 0
	case float64:
		return x != 0
	}
	return true
}

func asInt(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case json.Number:
		n, err := strconv.Atoi(x.String())
		return n, err == nil
	}
	return 0, false
}

func asFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case int:
		return float64(x), true
	case float64:
		return x, !math.IsNaN(x)
	case json.Number:
		f, err := x.Float64()
		return f, err == nil
	}
	return 0, false
}

func nullableString(v any, what string, ok func(string) bool, msg string) (*string, error) {
	if v == nil {
		return nil, nil
	}
	s, isStr := v.(string)
	if !isStr || !ok(s) {
		return nil, errs.Invalid("%s", msg)
	}
	return &s, nil
}

// ApplySettings overlays patch on base and validates the result (W§2.1 check_settings). Unknown
// keys are rejected. Each failure is errs.Invalid.
func ApplySettings(base store.Settings, patch map[string]any) (store.Settings, error) {
	s := base
	var unknown []string
	for k := range patch {
		known := false
		for _, n := range settingKeys {
			known = known || n == k
		}
		if !known {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return s, errs.Invalid("unknown settings: %v", unknown)
	}
	var err error
	for k, v := range patch {
		switch k {
		case "max":
			n, ok := asInt(v)
			if !ok {
				return s, errs.Invalid("max must be an integer from 1 to 10")
			}
			s.Max = n
		case "grind":
			g, _ := v.(string)
			s.Grind = g
		case "ci":
			c, _ := v.(string)
			s.CI = c
		case "auto_merge":
			s.AutoMerge = truthy(v)
		case "skip_approval":
			s.SkipApproval = truthy(v)
		case "feature_branch":
			if s.FeatureBranch, err = nullableString(v, k, reBranch.MatchString, "feature_branch is not a valid branch name"); err != nil {
				return s, err
			}
		case "base_branch":
			if s.BaseBranch, err = nullableString(v, k, reBranch.MatchString, "base_branch is not a valid branch name"); err != nil {
				return s, err
			}
		case "model":
			if s.Model, err = nullableString(v, k, reModel.MatchString, "model is not a model name"); err != nil {
				return s, err
			}
		case "effort":
			if s.Effort, err = nullableString(v, k, func(e string) bool { return efforts[e] },
				"effort must be low, medium, high, xhigh or max"); err != nil {
				return s, err
			}
		case "account":
			if s.Account, err = nullableString(v, k, func(a string) bool { return len(a) >= 1 && len(a) <= 40 },
				"account must be a saved account label"); err != nil {
				return s, err
			}
		case "max_cost":
			if v == nil {
				s.MaxCost = nil
				break
			}
			f, ok := asFloat(v)
			if !ok || f <= 0 || f > MaxCostLimit {
				return s, errs.Invalid("max_cost must be a positive number up to %d", MaxCostLimit)
			}
			s.MaxCost = &f
		}
	}
	return s, CheckSettings(s)
}

// CheckSettings validates a whole settings value.
func CheckSettings(s store.Settings) error {
	switch s.Grind {
	case "off", "simple", "full":
	default:
		return errs.Invalid("grind must be one of off, simple, full")
	}
	switch s.CI {
	case "wait", "defer", "ignore":
	default:
		return errs.Invalid("ci must be one of wait, defer, ignore")
	}
	if s.Max < 1 || s.Max > 10 {
		return errs.Invalid("max must be an integer from 1 to 10")
	}
	if s.MaxCost != nil && (*s.MaxCost <= 0 || *s.MaxCost > MaxCostLimit) {
		return errs.Invalid("max_cost must be a positive number up to %d", MaxCostLimit)
	}
	if s.FeatureBranch != nil && s.BaseBranch != nil && *s.FeatureBranch == *s.BaseBranch {
		return errs.Invalid("base_branch must differ from feature_branch")
	}
	return nil
}

// noFeatureBranch: an issue-list dispatch has none.
func noFeatureBranch(s store.Settings) error {
	if s.FeatureBranch != nil {
		return errs.Invalid("an issue-list dispatch has no feature branch")
	}
	return nil
}

func fmtSettings(patch map[string]any) string {
	keys := make([]string, 0, len(patch))
	for k := range patch {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := ""
	for i, k := range keys {
		if i > 0 {
			out += ", "
		}
		out += fmt.Sprintf("%s=%v", k, patch[k])
	}
	return out
}
