package prompts

import (
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
)

// Headless and Reentry are the fixed texts of API.md §9.4.
const (
	Headless = "Headless run: ask via setu ask. AskUserQuestion is not available: wherever a skill says to ask the user with AskUserQuestion, run `setu ask --json '<the AskUserQuestion input>'` instead, then end your turn; the answer arrives as your next message. Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take an answer until it exits."

	Reentry = "This is an automated headless pr-grind re-entry from the setu timer. Take the On-wake branch, never clear `paused:`, never call ScheduleWakeup or Monitor, follow the headless steps in SKILL.md, then exit. A stop that needs a human decision is asked through `setu ask` as Step 8 says; any other stop stays a plain paused stop."
)

// Steps whose grammar starts with flags.
var flagFirst = map[string]bool{
	"release-pr": true, "release-note": true, "peer-review": true, "pr-review": true,
	"project-coordinator": true, "agentic-onboard": true,
}

// MaxArgChars caps every step's arguments, in Unicode code points after trim and line-break
// normalisation.
const MaxArgChars = 20000

// Steps whose arguments are free text that may span several lines (a pasted log or stack trace).
var multiLine = map[string]bool{"small-change": true, "report-bug": true}

var (
	reNum       = regexp.MustCompile(`^#?(\d+)$`)
	reNumList   = regexp.MustCompile(`^#?\d+([\s,]+#?\d+)*$`)
	reURL       = regexp.MustCompile(`^https://\S+$`)
	reChannel   = regexp.MustCompile(`^[A-Za-z0-9_]{1,40}$`)
	reReviewer  = regexp.MustCompile(`^(copilot|[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))$`)
	reMDPrdPath = regexp.MustCompile(`(^|/)docs/prds/\S+\.md$`)
)

// Build makes the prompt for a step. A bare PR number for pr-grind needs the repo: use BuildIn.
func (r *Registry) Build(stepID, args string) (Prompt, error) { return r.BuildIn(stepID, args, "") }

// BuildIn is Build with the repo slug (owner/name) used to expand a bare PR number of pr-grind
// into its URL.
func (r *Registry) BuildIn(stepID, args, repo string) (Prompt, error) {
	s, ok := r.byID[stepID]
	if !ok {
		return Prompt{}, errs.NotFound("unknown step %q", stepID)
	}
	args = strings.TrimSpace(args)
	if err := checkArgs(s, &args, repo); err != nil {
		return Prompt{}, err
	}
	if s.Source == SrcBlubird {
		t := strings.TrimSpace("/blubird:" + s.Skill + " " + args)
		return Prompt{Step: s.ID, Display: t, Text: t}, nil
	}
	display := strings.TrimSpace("/" + s.Skill + " " + args)
	text := "Base directory for this skill: " + r.root + "/" + s.Skill + "\n\n" + r.bodies[s.Skill] +
		"\n\nARGUMENTS: " + args
	return Prompt{Step: s.ID, Display: display, Text: strings.TrimRight(text, " ")}, nil
}

// IssueOf returns the issue number a step's args start with (implement-issue, after-merge): the
// sessions manager sets link.issue from it.
func IssueOf(stepID, args string) (int, bool) {
	if stepID != "implement-issue" && stepID != "after-merge" {
		return 0, false
	}
	f := strings.Fields(args)
	if len(f) == 0 {
		return 0, false
	}
	m := reNum.FindStringSubmatch(f[0])
	if m == nil {
		return 0, false
	}
	n, err := strconv.Atoi(m[1])
	return n, err == nil && n > 0
}

func checkArgs(s Step, args *string, repo string) error {
	a := *args
	if multiLine[s.ID] {
		a = strings.ReplaceAll(strings.ReplaceAll(a, "\r\n", "\n"), "\r", "\n")
		*args = a
		if strings.ContainsRune(a, 0) {
			return errs.Invalid("%s: arguments cannot contain NUL", s.ID)
		}
	} else if strings.ContainsAny(a, "\x00\r\n") {
		return errs.Invalid("%s: arguments must be one line without NUL", s.ID)
	}
	if utf8.RuneCountInString(a) > MaxArgChars {
		return errs.Invalid("%s: arguments are longer than %d characters", s.ID, MaxArgChars)
	}
	if strings.HasPrefix(a, "-") && !flagFirst[s.ID] {
		return errs.Invalid("%s: arguments cannot start with '-'", s.ID)
	}
	switch s.ID {
	case "implement-issue", "after-merge":
		f := strings.Fields(a)
		if len(f) == 0 || !(reNum.MatchString(f[0]) || (s.ID == "implement-issue" && reURL.MatchString(f[0]))) {
			return errs.Invalid("%s needs an issue number first, e.g. 12", s.ID)
		}
	case "refine-issues":
		if !reNumList.MatchString(a) {
			return errs.Invalid("refine-issues needs an epic or issue numbers, e.g. 12 13")
		}
		var ns []string
		for _, t := range strings.FieldsFunc(a, func(r rune) bool { return r == ',' || r == ' ' || r == '\t' }) {
			ns = append(ns, strings.TrimPrefix(t, "#"))
		}
		*args = strings.Join(ns, " ")
	case "pr-grind":
		return checkGrind(args, repo)
	case "create-tasks":
		if !reMDPrdPath.MatchString(a) || strings.Contains(a, "..") {
			return errs.Invalid("create-tasks needs a PRD path under docs/prds/ ending in .md")
		}
	}
	return nil
}

func checkGrind(args *string, repo string) error {
	f := strings.Fields(*args)
	if len(f) == 0 {
		return errs.Invalid("pr-grind needs a PR number or URL")
	}
	switch {
	case reNum.MatchString(f[0]):
		if !regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`).MatchString(repo) {
			return errs.Invalid("pr-grind: a PR number needs a repo; pass the PR URL")
		}
		f[0] = "https://github.com/" + repo + "/pull/" + strings.TrimPrefix(f[0], "#")
	case reURL.MatchString(f[0]):
	default:
		return errs.Invalid("pr-grind needs a PR number or an https URL first")
	}
	rest := f[1:]
	for i := 0; i < len(rest); i++ {
		if i+1 >= len(rest) {
			return errs.Invalid("pr-grind: %s needs a value", rest[i])
		}
		v := rest[i+1]
		switch rest[i] {
		case "--channel":
			if !reChannel.MatchString(v) {
				return errs.Invalid("pr-grind: bad --channel %q", v)
			}
		case "--reviewer":
			if !reReviewer.MatchString(v) {
				return errs.Invalid("pr-grind: bad --reviewer %q", v)
			}
		case "--mode":
			if v != "deep" && v != "simple" {
				return errs.Invalid("pr-grind: --mode is deep or simple")
			}
		default:
			return errs.Invalid("pr-grind: unknown flag %q", rest[i])
		}
		i++
	}
	*args = strings.Join(f, " ")
	return nil
}
