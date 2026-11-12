package jev

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
	"sync"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/home"
)

const (
	ciQuestion      = "Is this failing CI log an infrastructure flake, or a real failure caused by the change?"
	findingQuestion = "Should this code review finding be fixed, or rebutted as wrong?"
	maxFindings     = 20
	workers         = 4
)

var (
	ciOptions = map[string]string{
		"flaky": "infrastructure flake: runner died, timeout with no test output, network or registry error, 429 or 503 from a mirror",
		"real":  "real failure: assertion, lint, type or build error",
	}
	findingOptions = map[string]string{
		"fix":   "the finding is valid or might be: change the code",
		"rebut": "the finding is wrong: handled elsewhere in the diff, would break a passing test, or rests on a false premise",
	}
)

func parseFloat(s string) (float64, bool) {
	f, err := strconv.ParseFloat(strings.TrimSpace(s), 64)
	return f, err == nil && !math.IsNaN(f) && !math.IsInf(f, 0)
}

// Hint is the advisory result of ci-hint and finding-hint.
type Hint struct {
	ID          any     `json:"id,omitempty"`
	Hint        string  `json:"hint"`
	Probability float64 `json:"probability"`
	Status      string  `json:"status"`
}

func none(status string) Hint { return Hint{Hint: "none", Status: status} }

func (c *Client) hint(ctx context.Context, point, question string, options map[string]string, text string) Hint {
	if s := c.Status(); s != "ok" {
		return none(s)
	}
	if strings.TrimSpace(text) == "" {
		return none("failed")
	}
	a := c.Ask(ctx, point, "choice", question, text, options, nil)
	if a.Status == "ok" {
		return Hint{Hint: a.Choice, Probability: math.Round(a.P*100) / 100, Status: "ok"}
	}
	if a.Status == "off" || a.Status == "missing" {
		return none(a.Status)
	}
	return none("failed")
}

// tail keeps the last n characters: failures print at the end of a log.
func tail(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[len(r)-n:])
}

// CIHint classifies a failing CI log as flaky or real.
func (c *Client) CIHint(ctx context.Context, text string) Hint {
	return c.hint(ctx, "ci-hint", ciQuestion, ciOptions, tail(text, MaxChars))
}

// FindingHints classifies up to 20 review findings (4 workers).
func (c *Client) FindingHints(ctx context.Context, findings []json.RawMessage) []Hint {
	if len(findings) > maxFindings {
		findings = findings[:maxFindings]
	}
	out := make([]Hint, len(findings))
	var wg sync.WaitGroup
	sem := make(chan struct{}, workers)
	for i, raw := range findings {
		var f struct {
			ID   any `json:"id"`
			Text any `json:"text"`
		}
		_ = json.Unmarshal(raw, &f)
		id := f.ID
		if id == nil {
			id = "#" + strconv.Itoa(i+1)
		}
		text, _ := f.Text.(string)
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			h := c.hint(ctx, "finding-hint", findingQuestion, findingOptions, text)
			h.ID = id
			out[i] = h
		}()
	}
	wg.Wait()
	return out
}

func readFile(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.ToValidUTF8(string(b), "�")
}

// useJev reads Settings "Use jev" (ui_settings.json, default true) on every call.
func useJev(h *home.Home) func() bool {
	return func() bool {
		if h == nil {
			return true
		}
		var m map[string]any
		_ = home.ReadJSON(h.Path("ui_settings.json"), &m)
		if v, ok := m["use_jev"].(bool); ok {
			return v
		}
		return true
	}
}

func fileArg(args []string) (string, bool) {
	for i := 0; i < len(args); i++ {
		switch {
		case args[i] == "--file" && i+1 < len(args):
			return args[i+1], true
		case strings.HasPrefix(args[i], "--file="):
			return strings.TrimPrefix(args[i], "--file="), true
		}
	}
	return "", false
}

func printJSON(w io.Writer, v any) {
	b, _ := json.Marshal(v)
	fmt.Fprintln(w, string(b))
}

func jevRun(ctx context.Context, env cli.Env, args []string) int {
	if len(args) == 0 || (args[0] != "ci-hint" && args[0] != "finding-hint") {
		fmt.Fprintln(env.Stderr, "usage: setu jev ci-hint|finding-hint --file F")
		return cli.ExitUsage
	}
	file, ok := fileArg(args[1:])
	if !ok {
		fmt.Fprintf(env.Stderr, "usage: setu jev %s --file F\n", args[0])
		return cli.ExitUsage
	}
	c := New(env.Home, useJev(env.Home))
	defer func() { // advisory verbs never exit non-zero
		if r := recover(); r != nil {
			fmt.Fprintln(env.Stderr, "jev: internal error")
			if args[0] == "ci-hint" {
				printJSON(env.Stdout, none("failed"))
			} else {
				printJSON(env.Stdout, []Hint{})
			}
		}
	}()
	if args[0] == "ci-hint" {
		printJSON(env.Stdout, c.CIHint(ctx, readFile(file)))
		return 0
	}
	var list []json.RawMessage
	if err := json.Unmarshal([]byte(readFile(file)), &list); err != nil || list == nil {
		list = nil
	}
	if list == nil {
		printJSON(env.Stdout, []Hint{})
		return 0
	}
	printJSON(env.Stdout, c.FindingHints(ctx, list))
	return 0
}

// Commands are the `setu jev` verbs.
func Commands() []cli.Command {
	return []cli.Command{{
		Name:    "jev",
		Summary: "advisory jev hints for the review grind: ci-hint|finding-hint --file F (JSON, always exit 0)",
		Run:     jevRun,
	}}
}
