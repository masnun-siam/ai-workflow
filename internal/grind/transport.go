package grind

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh"
)

var (
	reURLRepo  = regexp.MustCompile(`github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)`)
	reShortRef = regexp.MustCompile(`^([\w.-]+)/([\w.-]+)#(\d+)$`)
	reSlackURL = regexp.MustCompile(`^https://[^/\s]*slack\.com/archives/([A-Z0-9]+)/p(\d+)`)
	reLogin    = regexp.MustCompile(`^[A-Za-z0-9-]{1,39}$`)
)

func atoi(s string) int { n, _ := strconv.Atoi(s); return n }
func itoa(n int) string { return strconv.Itoa(n) }

// Slack is the Slack transport. The grind only posts: new top-level messages and thread replies.
type Slack interface {
	// Send posts text to a channel (a reply when threadTS is set) and returns the message ts and the
	// channel id Slack reports (either may be empty if the tool did not say).
	Send(ctx context.Context, channel, text, threadTS string) (ts, channelID string, err error)
	// ReadPermalink returns the text of the message a permalink points at.
	ReadPermalink(ctx context.Context, url string) (string, error)
}

// SlackCLI is the Slack transport over `slackcli`.
type SlackCLI struct{}

const slackTimeout = 60 * time.Second

func (SlackCLI) Send(ctx context.Context, channel, text, threadTS string) (string, string, error) {
	args := []string{"slackcli", "messages", "send", "--recipient-id", channel, "--message", text, "--json"}
	if threadTS != "" {
		args = append(args, "--thread-ts", threadTS)
	}
	r := execx.Run(ctx, args, execx.Opts{Timeout: slackTimeout})
	if r.Code != 0 {
		return "", "", errors.New(firstLine(string(r.Stderr), "slackcli failed"))
	}
	var out struct {
		TS        string `json:"ts"`
		ChannelID string `json:"channel_id"`
	}
	_ = json.Unmarshal(bytes.TrimSpace(r.Stdout), &out)
	return out.TS, out.ChannelID, nil
}

func (SlackCLI) ReadPermalink(ctx context.Context, url string) (string, error) {
	r := execx.Run(ctx, []string{"slackcli", "conversations", "read", "--permalink", url, "--json", "--limit", "1"}, execx.Opts{Timeout: slackTimeout})
	if r.Code != 0 {
		return "", errors.New(firstLine(string(r.Stderr), "slackcli failed"))
	}
	var out struct {
		Messages []struct {
			Text string `json:"text"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(bytes.TrimSpace(r.Stdout), &out); err != nil || len(out.Messages) == 0 {
		return "", errors.New("no message at that permalink")
	}
	return out.Messages[0].Text, nil
}

func firstLine(s, def string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return def
	}
	l, _, _ := strings.Cut(s, "\n")
	if len(l) > 200 {
		l = l[:200]
	}
	return l
}

// ThreadTS converts a Slack permalink's p<digits> into a message ts (seconds.micros).
func ThreadTS(url string) string {
	m := reSlackURL.FindStringSubmatch(url)
	if m == nil || len(m[2]) <= 6 {
		return ""
	}
	d := m[2]
	return d[:len(d)-6] + "." + d[len(d)-6:]
}

// ThreadChannel is the channel id of a Slack permalink.
func ThreadChannel(url string) string {
	if m := reSlackURL.FindStringSubmatch(url); m != nil {
		return m[1]
	}
	return ""
}

// PRInfo is what the grind reads from `gh pr view`.
type PRInfo struct {
	State    string
	IsDraft  bool
	Author   string
	Base     string
	Head     string
	Decision string
}

func viewPR(ctx context.Context, c gh.Client, k Key) (PRInfo, error) {
	var v struct {
		State          string `json:"state"`
		IsDraft        bool   `json:"isDraft"`
		HeadRefOid     string `json:"headRefOid"`
		BaseRefName    string `json:"baseRefName"`
		ReviewDecision string `json:"reviewDecision"`
		Author         *struct {
			Login string `json:"login"`
		} `json:"author"`
	}
	_, err := c.JSON(ctx, []string{"pr", "view", itoa(k.N), "--repo", k.Slug(), "--json",
		"state,isDraft,author,baseRefName,headRefOid,reviewDecision"}, 0, &v)
	if err != nil {
		return PRInfo{}, err
	}
	p := PRInfo{State: v.State, IsDraft: v.IsDraft, Head: v.HeadRefOid, Base: v.BaseRefName, Decision: v.ReviewDecision}
	if v.Author != nil {
		p.Author = v.Author.Login
	}
	return p, nil
}

// pages runs a paginated `gh api` list and joins the arrays (gh prints one array per page).
func pages[T any](ctx context.Context, c gh.Client, endpoint string) ([]T, error) {
	r := c.Run(ctx, []string{"api", endpoint, "--paginate"}, execx.Opts{Timeout: gh.JSONTimeout})
	if r.Code != 0 {
		return nil, fmt.Errorf("%s", firstLine(string(r.Stderr), "gh api failed"))
	}
	var all []T
	dec := json.NewDecoder(bytes.NewReader(r.Stdout))
	for {
		var page []T
		if err := dec.Decode(&page); err != nil {
			if err == io.EOF {
				break
			}
			return nil, fmt.Errorf("unexpected gh output: %v", err)
		}
		all = append(all, page...)
	}
	return all, nil
}

// requestReviewers asks each login for a review, one `gh pr edit --add-reviewer` per login
// (@copilot for copilot). It returns the logins that worked and one "login - error" per failure.
func requestReviewers(ctx context.Context, c gh.Client, k Key, logins []string) (ok, failed []string) {
	for _, l := range logins {
		who := l
		if strings.EqualFold(l, "copilot") {
			who = "@copilot"
		}
		r := c.Run(ctx, []string{"pr", "edit", itoa(k.N), "--repo", k.Slug(), "--add-reviewer", who}, execx.Opts{Timeout: gh.JSONTimeout})
		if r.Code != 0 {
			failed = append(failed, l+" - "+firstLine(string(r.Stderr)+string(r.Stdout), "request failed"))
			continue
		}
		ok = append(ok, l)
	}
	return ok, failed
}

var reDigits = regexp.MustCompile(`^\d+$`)
