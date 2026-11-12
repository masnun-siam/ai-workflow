package gh

import (
	"context"
	"regexp"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
)

// MaxComment is GitHub's comment body limit.
const MaxComment = 65536

var reSHA = regexp.MustCompile(`^[0-9a-f]{40}$`)

// ghWrite runs a gh write; a failure is errs.Upstream with gh's message (stripped, 300 chars).
func ghWrite(ctx context.Context, c Client, args []string) (execx.Result, error) {
	res := c.Run(ctx, args, execx.Opts{Timeout: JSONTimeout})
	if res.Code != 0 {
		msg := strings.TrimSpace(string(res.Stderr))
		if msg == "" {
			msg = strings.TrimSpace(string(res.Stdout))
		}
		if msg == "" {
			msg = "gh failed"
		}
		return res, errs.Upstream("%s", trunc(msg, 300))
	}
	return res, nil
}

func checkID(slug string, n int) error {
	if _, _, err := splitSlug(slug); err != nil || n < 1 {
		return errs.Invalid("bad issue id")
	}
	return nil
}

// Comment posts a comment on an issue or a PR (both are issues to the REST API) and returns its URL.
func Comment(ctx context.Context, c Client, slug string, n int, text string) (string, error) {
	if err := checkID(slug, n); err != nil {
		return "", err
	}
	if strings.TrimSpace(text) == "" {
		return "", errs.Invalid("comment text is required")
	}
	if len([]rune(text)) > MaxComment {
		return "", errs.Invalid("comment is longer than %d characters", MaxComment)
	}
	var out struct {
		HTMLURL string `json:"html_url"`
	}
	res, err := ghWrite(ctx, c, []string{"api", "repos/" + slug + "/issues/" + itoa(n) + "/comments", "-f", "body=" + text})
	if err != nil {
		return "", err
	}
	_ = parseOut(res, &out)
	return out.HTMLURL, nil
}

// SetIssueState closes (reason completed | not_planned, default completed) or reopens an issue.
func SetIssueState(ctx context.Context, c Client, slug string, n int, state, reason string) error {
	if err := checkID(slug, n); err != nil {
		return err
	}
	switch state {
	case "open":
		_, err := ghWrite(ctx, c, []string{"issue", "reopen", itoa(n), "-R", slug})
		return err
	case "closed":
		why := map[string]string{"": "completed", "completed": "completed", "not_planned": "not planned"}[reason]
		if why == "" {
			return errs.Invalid("reason must be completed or not_planned")
		}
		_, err := ghWrite(ctx, c, []string{"issue", "close", itoa(n), "-R", slug, "--reason", why})
		return err
	}
	return errs.Invalid("state must be open or closed")
}

// SetPRState closes (branch kept, no comment) or reopens a PR.
func SetPRState(ctx context.Context, c Client, slug string, n int, state string) error {
	if err := checkID(slug, n); err != nil {
		return err
	}
	verb := map[string]string{"open": "reopen", "closed": "close"}[state]
	if verb == "" {
		return errs.Invalid("state must be open or closed")
	}
	_, err := ghWrite(ctx, c, []string{"pr", verb, itoa(n), "-R", slug})
	return err
}

// MergePR merges with a merge commit pinned to the head sha; GitHub refuses it if the head moved.
// Never squash. Agents never call this: it is a human action.
func MergePR(ctx context.Context, c Client, slug string, n int, sha string) error {
	if err := checkID(slug, n); err != nil {
		return err
	}
	if !reSHA.MatchString(sha) {
		return errs.Invalid("sha must be the PR head commit (40 hex characters)")
	}
	_, err := ghWrite(ctx, c, []string{"pr", "merge", itoa(n), "-R", slug, "--merge", "--match-head-commit", sha})
	return err
}

// CloseEpic closes every child (as completed), then the epic. It stops at the first failure and
// says what had closed. children are issue numbers of the same repo.
func CloseEpic(ctx context.Context, c Client, slug string, epic int, children []int) ([]int, error) {
	if err := checkID(slug, epic); err != nil {
		return nil, err
	}
	closed := []int{}
	for _, n := range append(append([]int{}, children...), epic) {
		if err := SetIssueState(ctx, c, slug, n, "closed", "completed"); err != nil {
			done := "nothing"
			if len(closed) > 0 {
				parts := make([]string, len(closed))
				for i, x := range closed {
					parts[i] = "#" + itoa(x)
				}
				done = strings.Join(parts, ", ")
			}
			return closed, errs.Upstream("closing #%d failed (%s); closed so far: %s", n, err.Error(), done)
		}
		closed = append(closed, n)
	}
	return closed, nil
}
