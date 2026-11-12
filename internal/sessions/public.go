package sessions

import (
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var cmdRe = regexp.MustCompile(`(?s)^/(?:[\w-]+:)?([\w-]+)(?:\s+(.*))?$`)

// parseCommand is S§5.3 parse: "/plugin:skill rest" -> (skill, rest).
func parseCommand(cmd string) (name, rest string, ok bool) {
	m := cmdRe.FindStringSubmatch(strings.TrimLeft(cmd, " \t\r\n"))
	if m == nil {
		return "", "", false
	}
	return m[1], m[2], true
}

func equalFold(a, b string) bool { return strings.EqualFold(a, b) }

// stepOf is the record's step id; legacy records infer it from the command.
func (m *Manager) stepOf(r Record) string {
	if r.Step != "" {
		return r.Step
	}
	if name, _, ok := parseCommand(r.Command); ok && m.d.Prompts != nil {
		if _, ok := m.d.Prompts.Step(name); ok {
			return name
		}
	}
	return ""
}

// slugOf is the registered slug of the session's checkout, else the link's, else "".
func (m *Manager) slugOf(r Record) string {
	p := r.CwdPath
	if p == "" && filepath.IsAbs(r.Repo) {
		p = r.Repo
	}
	if p != "" && m.d.Repos != nil {
		if s := m.d.Repos.SlugOf(p); s != "" {
			return s
		}
	}
	if !filepath.IsAbs(r.Repo) && strings.Count(r.Repo, "/") == 1 && !r.NoRepo {
		return r.Repo
	}
	if r.Link != nil && r.Link.Owner != "" {
		return r.Link.Owner + "/" + r.Link.Repo
	}
	return ""
}

func strp(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// shellQuote is shlex.quote.
func shellQuote(s string) string {
	if s == "" {
		return "''"
	}
	safe := true
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune("@%+=:,./-_", c)) {
			safe = false
			break
		}
	}
	if safe {
		return s
	}
	return "'" + strings.ReplaceAll(s, "'", `'"'"'`) + "'"
}

func parseISO(s string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		t, err = time.Parse("2006-01-02T15:04:05.999999999-07:00", s)
	}
	return t, err == nil
}

// Public builds the API shape of a record.
func (m *Manager) Public(r Record) Session {
	s := Session{
		ID: r.ID, Command: r.Command, Link: r.Link, Status: r.Status,
		Cost: r.Cost, Tokens: r.Tokens, StartedAt: r.StartedAt,
		Waiting: r.PendingQuestion != nil, PendingQuestion: r.PendingQuestion,
		Hold: r.Hold, NoRepo: r.NoRepo, Dismissed: r.Dismissed, Hooks: r.Hooks,
		AutoResume: r.AutoResume,
	}
	step := m.stepOf(r)
	s.Step = strp(step)
	if step != "" && m.d.Prompts != nil {
		if st, ok := m.d.Prompts.Step(step); ok {
			sk := st.Skill
			if st.Source == "blubird" {
				sk = "blubird:" + st.Skill
			}
			s.Skill = &sk
		}
	}
	s.Kind = strp(r.Kind)
	slug := m.slugOf(r)
	s.Repo = strp(slug)
	s.RepoPath = strp(r.CwdPath)
	s.SessionID = strp(r.SessionID)
	if r.Model != "" {
		s.Model = &r.Model
	} else {
		s.Model = strp(r.RunModel)
	}
	s.Effort = strp(r.RunEffort)
	s.EndedAt = strp(r.EndedAt)
	s.Error, s.Note = strp(r.Error), strp(r.Note)
	s.PendingAnswer, s.QueuedPrompt = strp(r.PendingAnswer), strp(r.QueuedPrompt)
	s.Account = r.ClaudeCmd
	if m.d.Settings != nil {
		if l := m.d.Settings.LabelFor(r.ClaudeCmd); l != "" {
			s.Account = l
		}
	}
	if r.LimitResetsAt != 0 {
		v := r.LimitResetsAt
		s.LimitResetsAt = &v
	}
	s.LimitType = strp(r.LimitType)
	s.VaultFolder = strp(r.VaultFolder)
	if t0, ok := parseISO(r.StartedAt); ok {
		end := m.d.now()
		if t1, ok := parseISO(r.EndedAt); ok {
			end = t1
		}
		d := int64(end.Sub(t0).Seconds())
		if d < 0 {
			d = 0
		}
		s.DurationS = &d
	}
	s.Title = m.titleOf(r, slug)
	if r.Panel != "" {
		p := &Panel{ID: r.Panel, Role: r.PanelRole, Lens: strp(r.PanelLens)}
		if m.d.PanelState != nil {
			p.State = m.d.PanelState(r.Panel)
		}
		s.Panel = p
	}
	if r.Dispatch != "" {
		s.Dispatch = &DispatchRef{ID: r.Dispatch, Lane: r.Lane}
	}
	if r.CwdPath != "" && r.SessionID != "" {
		c := "cd " + shellQuote(r.CwdPath) + " && claude --resume " + shellQuote(r.SessionID)
		s.ResumeCommand = &c
	}
	return s
}

func (m *Manager) titleOf(r Record, slug string) string {
	if r.Link != nil && m.d.Title != nil && slug != "" {
		if t := m.d.Title(slug, r.Link.Issue); t != "" {
			return t
		}
	}
	line := strings.TrimSpace(strings.SplitN(strings.TrimSpace(r.Command), "\n", 2)[0])
	if c := clip(line, 119); c != line {
		return strings.TrimRight(c, " ") + "…"
	}
	return line
}

// Stats tallies today's and this month's sessions and cost (UTC).
func (m *Manager) Stats() SessionStats {
	now := m.d.now().UTC()
	var st SessionStats
	for _, r := range m.listAll() {
		t, ok := parseISO(r.StartedAt)
		if !ok {
			continue
		}
		t = t.UTC()
		if t.Year() != now.Year() || t.Month() != now.Month() {
			continue
		}
		c := 0.0
		if r.Cost != nil {
			c = *r.Cost
		}
		st.MonthCount++
		st.MonthCost += c
		if t.Day() == now.Day() {
			st.TodayCount++
			st.TodayCost += c
		}
	}
	return st
}
