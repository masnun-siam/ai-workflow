package gh

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
)

// PRRef names one pull request.
type PRRef struct {
	Owner, Repo string
	N           int
}

func (p PRRef) Slug() string { return p.Owner + "/" + p.Repo }

var (
	reURL   = regexp.MustCompile(`github\.com/([^/]+)/([^/]+)/pull/(\d+)`)
	reShort = regexp.MustCompile(`^([^/\s]+)/([^/#\s]+)[#\s](\d+)$`)
	reDigit = regexp.MustCompile(`^\d+$`)
)

// ParsePRRef accepts a PR URL, `owner/repo#N`, `owner/repo N` or a bare number. A bare number
// resolves owner/repo from the checkout at cwd with `gh repo view`. Failures are errs.Invalid
// (the CLI exits 64).
func ParsePRRef(ctx context.Context, c Client, ref, cwd string) (PRRef, error) {
	ref = strings.TrimSpace(ref)
	if m := reURL.FindStringSubmatch(ref); m != nil {
		n, _ := strconv.Atoi(m[3])
		return PRRef{m[1], m[2], n}, nil
	}
	if m := reShort.FindStringSubmatch(ref); m != nil {
		n, _ := strconv.Atoi(m[3])
		return PRRef{m[1], m[2], n}, nil
	}
	if reDigit.MatchString(ref) {
		n, _ := strconv.Atoi(ref)
		var slug any
		res, err := runJSONIn(ctx, c, []string{"repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"}, cwd, &slug)
		if s, ok := slug.(string); ok && err == nil && strings.Contains(s, "/") {
			owner, repo, _ := strings.Cut(s, "/")
			return PRRef{owner, repo, n}, nil
		}
		return PRRef{}, errs.Invalid("cannot resolve owner/repo for PR %s: %s", ref, strings.TrimSpace(string(res.Stderr)))
	}
	return PRRef{}, errs.Invalid("unrecognised PR reference: %s (want a URL, owner/repo#N, or N)", pyRepr(ref))
}

func (p PRRef) String() string { return fmt.Sprintf("%s/%s#%d", p.Owner, p.Repo, p.N) }
