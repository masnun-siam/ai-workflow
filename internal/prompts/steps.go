package prompts

import "strings"

// InStage reports whether the step belongs to a stage ("map-prds" is in both prd and ops; its
// Stage is "prd,ops").
func (s Step) InStage(stage string) bool {
	for _, x := range strings.Split(s.Stage, ",") {
		if x == stage {
			return true
		}
	}
	return false
}

// defaultSteps is API.md §9.1, in palette order.
func defaultSteps() []Step {
	b, s := SrcBlubird, SrcSetu
	return []Step{
		{"create-prd", b, "create-prd", InDocs, "prd", "Create PRD", "free text, a PRD path, or <path> — the team has reviewed it; approve it"},
		{"map-prds", b, "map-prds", InDocs, "prd,ops", "Map PRDs", "[file or folder ...]"},
		{"create-tasks", b, "create-tasks", InDocs, "tasks", "Create tasks", "<PRD path>"},
		{"small-change", b, "create-tasks", InRepo, "refine", "Small change", "<finding>"},
		{"refine-issues", b, "refine-issues", InIssue, "refine", "Refine issues", "<epic | issues>"},
		{"reproduce-bug", b, "reproduce-bug", InIssue, "refine", "Reproduce bug", "<issue | symptoms>"},
		{"report-bug", b, "reproduce-bug", InRepo, "refine", "Report bug", "<bug report>"},
		{"implement-issue", b, "implement-issue", InIssue, "implement", "Implement issue", "<issue | epic>"},
		{"after-merge", b, "implement-issue", InIssue, "implement", "After merge", "<n> (PR #p for issue #n is merged: ...)"},
		{"verifier-locally", b, "verifier-locally", InIssue, "implement", "Verify locally", "free"},
		{"project-coordinator", b, "project-coordinator", InDocs, "implement", "Project coordinator", "<issues link | n> [--destination L] [--max N]"},
		{"pr-review", b, "pr-review", InIssue, "review", "PR review", "<PR | branch | range> [--fix]"},
		{"peer-review", s, "peer-review", InRepo, "review", "Peer review", "[--lenses a,b] <artifact> | --root <panel> <artifact>"},
		{"pr-grind", s, "pr-grind", InIssue, "review", "PR grind", "<PR url | thread url> [--channel ID] [--reviewer L]"},
		{"release-pr", s, "release-pr", InRepo, "release", "Release PR", "[--dry-run] [<head> <base>]"},
		{"release-note", s, "release-note", InNone, "notify", "Release note", "<pr-url> [channel:<name>] [cc:<a,b>] [--draft <file>]"},
		{"agentic-onboard", b, "agentic-onboard", InRepo, "ops", "Agentic onboard", "[--dev]"},
		{"ci-optimize", b, "ci-optimize", InRepo, "ops", "CI optimize", ""},
		{"security-sweep", b, "security-sweep", InDocs, "ops", "Security sweep", "[repo name ...]"},
		{"docs-updater", b, "docs-updater", InRepo, "ops", "Docs updater", "[full] [issue]"},
		{"skill-feedback", b, "skill-feedback", InRepo, "ops", "Skill feedback", "<feedback> | reconcile ..."},
		{"day-end-reconcile", b, "day-end-reconcile", InNone, "me", "Day-end reconcile", ""},
		{"weekly-review", b, "weekly-review", InNone, "me", "Weekly review", ""},
	}
}
