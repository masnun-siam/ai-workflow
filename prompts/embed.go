// Package builtin embeds the built-in prompts (SKILL.md + scripts) and agent texts. The Go side
// that extracts and serves them is internal/prompts.
package builtin

import "embed"

// FS holds release-pr, pr-grind, release-note, peer-review and agents/.
//
//go:embed all:release-pr all:pr-grind all:release-note all:peer-review all:agents
var FS embed.FS
