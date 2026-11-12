package sessions

import "strings"

// Headless is the system text appended to every gated start and every resume (API §9.4).
const Headless = "Headless run: ask via setu ask. AskUserQuestion is not available: wherever a skill says to ask the user with AskUserQuestion, run `setu ask --json '<the AskUserQuestion input>'` instead, then end your turn; the answer arrives as your next message. Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take an answer until it exits."

func baseArgs(allowed []string) []string {
	b := []string{"--print", "--output-format", "stream-json", "--verbose"}
	if len(allowed) > 0 {
		// one comma-joined value: the flag is variadic and would eat the prompt
		return append(b, "--allowedTools", strings.Join(allowed, ","))
	}
	return append(b, "--dangerously-skip-permissions")
}

func (m *Manager) agentBody(name string) (string, error) {
	if name == "" || m.d.Prompts == nil {
		return "", nil
	}
	body, _, err := m.d.Prompts.Agent(name)
	return body, err
}

func joinAppend(parts ...string) string {
	var out []string
	for _, p := range parts {
		if p != "" {
			out = append(out, p)
		}
	}
	return strings.Join(out, "\n\n")
}

// startArgv is the fresh-start command line (S§1.4 with API D4): the record carries everything.
func (m *Manager) startArgv(exe []string, r Record, prompt string) ([]string, error) {
	body, err := m.agentBody(r.Agent)
	if err != nil {
		return nil, err
	}
	argv := append(append([]string{}, exe...), baseArgs(r.AllowedTools)...)
	gate := ""
	if r.Gate {
		gate = Headless
	}
	if app := joinAppend(append([]string{body, gate}, r.Instructions...)...); app != "" {
		argv = append(argv, "--append-system-prompt", app)
	}
	if r.DirectEffort != "" {
		argv = append(argv, "--effort", r.DirectEffort)
	}
	if r.DirectModel != "" {
		argv = append(argv, "--model", r.DirectModel)
	}
	if r.RunModel != "" {
		argv = append(argv, "--model", r.RunModel)
	}
	if r.RunEffort != "" {
		argv = append(argv, "--effort", r.RunEffort)
	}
	return append(argv, prompt), nil
}

// resumeArgv resumes claude session sid. The agent body and Headless always ride in the one
// append value; the direct model/effort and the instructions are not re-added.
func (m *Manager) resumeArgv(exe []string, r Record, sid, prompt string) ([]string, error) {
	body, err := m.agentBody(r.Agent)
	if err != nil {
		return nil, err
	}
	argv := append(append([]string{}, exe...), baseArgs(r.AllowedTools)...)
	argv = append(argv, "--append-system-prompt", joinAppend(body, Headless))
	if r.RunModel != "" {
		argv = append(argv, "--model", r.RunModel)
	}
	if r.RunEffort != "" {
		argv = append(argv, "--effort", r.RunEffort)
	}
	return append(argv, "--resume", sid, prompt), nil
}
