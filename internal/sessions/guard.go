package sessions

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const (
	guardPrefix = "guard-"
	guardReason = "blubird's guard stopped this edit: CLAUDE.md and AGENTS.md are the protected agent instructions. Approve only if a human asked for this change."
	guardShow   = 1500
)

// realpath is os.path.realpath: symlinks resolved as far as the path exists.
func realpath(p string) string {
	p = filepath.Clean(p)
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	dir, base := filepath.Split(p)
	dir = filepath.Clean(dir)
	if dir == p || dir == "" || dir == "." {
		return p
	}
	return filepath.Join(realpath(dir), base)
}

func joinPy(cwd, p string) string {
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(cwd, p)
}

// rootGuarded: path is the same file as cwd's root CLAUDE.md or AGENTS.md (symlinks followed).
func rootGuarded(cwd, path string) bool {
	if cwd == "" || path == "" {
		return false
	}
	real := realpath(joinPy(cwd, path))
	for _, name := range []string{"CLAUDE.md", "AGENTS.md"} {
		root := filepath.Join(cwd, name)
		a, e1 := os.Stat(real)
		b, e2 := os.Stat(root)
		if e1 == nil && e2 == nil {
			if os.SameFile(a, b) {
				return true
			}
			continue
		}
		if e1 != nil && real == realpath(root) {
			return true
		}
	}
	return false
}

func code(s string) string {
	if strings.Contains(s, "`") {
		return s
	}
	return "`" + s + "`"
}

var tickRun = regexp.MustCompile("`+")

func fenced(text string) string {
	run := 0
	for _, m := range tickRun.FindAllString(text, -1) {
		if len(m) > run {
			run = len(m)
		}
	}
	n := run + 1
	if n < 3 {
		n = 3
	}
	f := strings.Repeat("`", n)
	return f + "diff\n" + text + "\n" + f
}

type editFields struct {
	OldString  string `json:"old_string"`
	NewString  string `json:"new_string"`
	ReplaceAll bool   `json:"replace_all"`
}

type toolInput struct {
	FilePath string       `json:"file_path"`
	Content  *string      `json:"content"`
	Edits    []editFields `json:"edits"`
	editFields
}

func guardDiff(e GuardEdit) string {
	var in toolInput
	_ = json.Unmarshal(e.ToolInput, &in)
	var text string
	switch {
	case e.ToolName == "Write":
		c := ""
		if in.Content != nil {
			c = *in.Content
		}
		text = "New content:\n" + c
	default:
		pairs := []editFields{in.editFields}
		if e.ToolName == "MultiEdit" {
			pairs = in.Edits
		}
		var parts []string
		for _, p := range pairs {
			parts = append(parts, "- "+p.OldString+"\n+ "+p.NewString)
		}
		text = strings.Join(parts, "\n")
	}
	r := []rune(text)
	if len(r) <= guardShow {
		return text
	}
	return fmt.Sprintf("%s\n… %d more characters not shown; Approve applies all of it", string(r[:guardShow]), len(r)-guardShow)
}

// relayGuard asks the human about a denied protected edit (FR-5): a held Approve/Deny round.
// False when the edit is not the session's root file or a tool the UI cannot apply.
func (m *Manager) relayGuard(id string, denial map[string]any) bool {
	rec, err := m.Get(id)
	if err != nil {
		return false
	}
	tool, _ := denial["tool_name"].(string)
	in, _ := denial["tool_input"].(map[string]any)
	path, _ := in["file_path"].(string)
	if (tool != "Edit" && tool != "Write" && tool != "MultiEdit") || !rootGuarded(rec.CwdPath, path) {
		return false
	}
	real := realpath(joinPy(rec.CwdPath, path))
	shown := code(path)
	if real != path {
		shown += " (the file written: " + code(real) + ")"
	}
	rawIn, _ := json.Marshal(in)
	toolUse, _ := denial["tool_use_id"].(string)
	edit := GuardEdit{ToolName: tool, ToolInput: rawIn, ToolUseID: toolUse}
	rid := toolUse
	if rid == "" {
		var b [2]byte
		_, _ = rand.Read(b[:])
		rid = hex.EncodeToString(b[:])
	}
	round := Round{
		ID: guardPrefix + rid, Status: "pending", AllowFreeText: true, Held: true,
		Questions: []Question{{
			Header:   "Protected file",
			Question: guardReason + "\n\n" + shown + "\n\n" + fenced(guardDiff(edit)),
			Options: []Option{
				{Label: "Approve", Description: "Apply this edit"},
				{Label: "Deny", Description: "Leave the file unchanged"},
			},
		}},
	}
	_, err = m.setPending(id, round, func(r *Record) { r.GuardEdit = &edit })
	return err == nil
}

// applyGuardEdit applies the approved edit to cwd's root file. All or nothing.
func applyGuardEdit(cwd string, e GuardEdit) error {
	var in toolInput
	_ = json.Unmarshal(e.ToolInput, &in)
	if !rootGuarded(cwd, in.FilePath) {
		return fmt.Errorf("%q is not this repo's root CLAUDE.md or AGENTS.md", in.FilePath)
	}
	real := realpath(joinPy(cwd, in.FilePath))
	var content string
	switch e.ToolName {
	case "Write":
		if in.Content == nil {
			return fmt.Errorf("the Write has no content")
		}
		content = *in.Content
	case "Edit", "MultiEdit":
		b, err := os.ReadFile(real)
		if err != nil {
			return fmt.Errorf("cannot read the file: %v", err)
		}
		content = string(b)
		edits := []editFields{in.editFields}
		if e.ToolName == "MultiEdit" {
			edits = in.Edits
		}
		for i, ed := range edits {
			if ed.OldString == "" {
				return fmt.Errorf("edit %d is malformed", i+1)
			}
			n := strings.Count(content, ed.OldString)
			if n == 0 {
				return fmt.Errorf("edit %d: the text to replace is no longer in the file", i+1)
			}
			if n > 1 && !ed.ReplaceAll {
				return fmt.Errorf("edit %d: the text to replace occurs %d times", i+1, n)
			}
			if ed.ReplaceAll {
				content = strings.ReplaceAll(content, ed.OldString, ed.NewString)
			} else {
				content = strings.Replace(content, ed.OldString, ed.NewString, 1)
			}
		}
	default:
		return fmt.Errorf("%s edits are not applied by the UI", e.ToolName)
	}
	if err := os.WriteFile(real, []byte(content), 0o644); err != nil {
		return fmt.Errorf("cannot write the file: %v", err)
	}
	return nil
}

// guardResumeText: for an answered guard round, Approve applies the stored edit first; both
// answers tell the agent what happened. Other rounds: text unchanged.
func (m *Manager) guardResumeText(rec Record, roundID string, answers map[string]Answer, text string) string {
	if !strings.HasPrefix(roundID, guardPrefix) || rec.GuardEdit == nil {
		return text
	}
	edit := *rec.GuardEdit
	_, _ = m.Update(rec.ID, func(r *Record) error { r.GuardEdit = nil; return nil })
	var in toolInput
	_ = json.Unmarshal(edit.ToolInput, &in)
	path := in.FilePath
	a := answers["0"]
	if len(answers) != 1 || len(a.Labels) != 1 || a.Labels[0] != "Approve" || a.Other != nil || a.None {
		return text + "\nThe human denied this edit to " + path + ". Leave it unchanged and continue without it."
	}
	if err := applyGuardEdit(rec.CwdPath, edit); err != nil {
		return text + "\nThe human approved the edit but the UI could not apply it: " + err.Error() + ". Say so and continue."
	}
	return text + "\nThe human approved the edit to " + path + " and the UI applied it. Continue."
}
