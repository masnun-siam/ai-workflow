package sessions

// ContinueText is the FR-6 message that resumes a stalled session of step.
func ContinueText(step string) string {
	return "Continue the `" + step + "` flow from where you stopped. Do the remaining steps, then end as the idle guard says."
}
