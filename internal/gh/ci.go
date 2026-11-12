package gh

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
)

// CIPollInterval is the --watch re-check cadence (G§6.1). A variable so tests can shrink it.
var CIPollInterval = 30 * time.Second

const (
	runViewTimeout = 300 * time.Second
	logExcerptLen  = 4000
)

// CI states.
const (
	CIGreen    = "green"
	CIRed      = "red"
	CIPending  = "pending"
	CIError    = "error"
	CIConflict = "conflict"
)

// CI is a PR's check status. JSON key order matches `aiw ci status`.
type CI struct {
	State       string   `json:"state"`
	HeadSHA     string   `json:"head_sha"`
	Failing     []CIFail `json:"failing"`
	Note        string   `json:"note,omitempty"`
	CIAttempted bool     `json:"ci_attempted,omitempty"`
}

// MarshalJSON writes head_sha null when unknown and failing [] when empty.
func (c CI) MarshalJSON() ([]byte, error) {
	type out struct {
		State       string   `json:"state"`
		HeadSHA     *string  `json:"head_sha"`
		Failing     []CIFail `json:"failing"`
		Note        string   `json:"note,omitempty"`
		CIAttempted bool     `json:"ci_attempted,omitempty"`
	}
	o := out{State: c.State, Failing: c.Failing, Note: c.Note, CIAttempted: c.CIAttempted}
	if c.HeadSHA != "" {
		o.HeadSHA = &c.HeadSHA
	}
	if o.Failing == nil {
		o.Failing = []CIFail{}
	}
	return json.Marshal(o)
}

// CIFail is a failing check. From CISnapshot it has Name, State, Bucket and Link; after
// ExpandFailing it has Name, RunID, Link and LogExcerpt (the shape the CLI prints).
type CIFail struct {
	Name       string `json:"name"`
	State      string `json:"state,omitempty"`
	Bucket     string `json:"bucket,omitempty"`
	RunID      string `json:"run_id,omitempty"`
	Link       string `json:"link"`
	LogExcerpt string `json:"log_excerpt,omitempty"`

	expanded bool
}

// MarshalJSON: an expanded entry always has name, run_id, link and log_excerpt (empty strings
// included), like `aiw ci status`; a raw entry has name, state, bucket and link.
func (f CIFail) MarshalJSON() ([]byte, error) {
	if f.expanded {
		return json.Marshal(struct {
			Name       string `json:"name"`
			RunID      string `json:"run_id"`
			Link       string `json:"link"`
			LogExcerpt string `json:"log_excerpt"`
		}{f.Name, f.RunID, f.Link, f.LogExcerpt})
	}
	return json.Marshal(struct {
		Name   string `json:"name"`
		State  string `json:"state"`
		Bucket string `json:"bucket"`
		Link   string `json:"link"`
	}{f.Name, f.State, f.Bucket, f.Link})
}

type checkRow struct {
	Name   string `json:"name"`
	State  string `json:"state"`
	Bucket string `json:"bucket"`
	Link   string `json:"link"`
}

// StateOf: pending beats red beats green; empty, pass and skipping rows are green.
func StateOf(rows []checkRow) string {
	red := false
	for _, r := range rows {
		switch strings.ToLower(r.Bucket) {
		case "pending":
			return CIPending
		case "fail":
			red = true
		}
	}
	if red {
		return CIRed
	}
	return CIGreen
}

// RunIDOf is the text between /runs/ and the next / of a check link.
func RunIDOf(link string) string {
	_, after, ok := strings.Cut(link, "/runs/")
	if !ok {
		return ""
	}
	id, _, _ := strings.Cut(after, "/")
	return id
}

// CISnapshot reads the PR's mergeable state and checks once (G§6.1).
func CISnapshot(ctx context.Context, c Client, p PRRef) CI {
	slug := p.Slug()
	var view struct {
		HeadRefOid string `json:"headRefOid"`
		Mergeable  string `json:"mergeable"`
	}
	_, _ = c.JSON(ctx, []string{"pr", "view", itoa(p.N), "--repo", slug, "--json", "headRefOid,mergeable"}, 0, &view)
	head := view.HeadRefOid
	if view.Mergeable == "CONFLICTING" {
		// GitHub runs no CI on a conflicting PR, so its "no checks" must not read as green.
		return CI{State: CIConflict, HeadSHA: head, Note: "merge conflict with the base branch"}
	}
	res := c.Run(ctx, []string{"pr", "checks", itoa(p.N), "--repo", slug, "--json", "name,state,bucket,link"}, execx.Opts{Timeout: JSONTimeout})
	var rows []checkRow
	// gh exits non-zero for red or pending checks while still writing the JSON: read stdout either way.
	if !decodeRows(res.Stdout, &rows) {
		text := strings.TrimSpace(string(res.Stderr) + string(res.Stdout))
		if strings.Contains(strings.ToLower(text), "no checks") {
			return CI{State: CIGreen, HeadSHA: head, Note: "no checks configured"}
		}
		return CI{State: CIError, HeadSHA: head, Note: trunc(text, 300)}
	}
	var failing []CIFail
	for _, r := range rows {
		if strings.ToLower(r.Bucket) == "fail" {
			failing = append(failing, CIFail{Name: r.Name, State: r.State, Bucket: r.Bucket, Link: r.Link})
		}
	}
	return CI{State: StateOf(rows), HeadSHA: head, Failing: failing}
}

// decodeRows parses a JSON list of check rows (non-object entries are dropped).
func decodeRows(b []byte, rows *[]checkRow) bool {
	var raw []json.RawMessage
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(b))), &raw); err != nil || raw == nil {
		return false
	}
	*rows = (*rows)[:0]
	for _, m := range raw {
		var r checkRow
		if json.Unmarshal(m, &r) == nil {
			*rows = append(*rows, r)
		}
	}
	return true
}

// CIWatch snapshots, then re-snapshots every CIPollInterval while the state is pending or error and
// before the timeout. On expiry with checks still pending/error, Note says so. It does not read logs:
// call ExpandFailing on the result.
func CIWatch(ctx context.Context, c Client, p PRRef, timeout time.Duration) CI {
	deadline := time.Now().Add(timeout)
	res := CISnapshot(ctx, c, p)
	for (res.State == CIPending || res.State == CIError) && time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return res
		case <-time.After(CIPollInterval):
		}
		res = CISnapshot(ctx, c, p)
	}
	if res.State == CIPending || res.State == CIError {
		res.Note = "wall-clock cap of " + itoa(int(timeout/time.Second)) + "s expired with checks still " + res.State
	}
	return res
}

// ExpandFailing turns each failing check into {name, run_id, link, log_excerpt}: the last 4000
// characters of `gh run view <id> --log-failed`.
func ExpandFailing(ctx context.Context, c Client, p PRRef, ci CI) CI {
	out := make([]CIFail, 0, len(ci.Failing))
	for _, f := range ci.Failing {
		id := RunIDOf(f.Link)
		excerpt := ""
		if id != "" {
			r := c.Run(ctx, []string{"run", "view", id, "--repo", p.Slug(), "--log-failed"}, execx.Opts{Timeout: runViewTimeout})
			text := strings.TrimSpace(string(r.Stdout))
			if text == "" {
				text = strings.TrimSpace(string(r.Stderr))
			}
			excerpt = tail(text, logExcerptLen)
		}
		out = append(out, CIFail{Name: f.Name, RunID: id, Link: f.Link, LogExcerpt: excerpt, expanded: true})
	}
	ci.Failing = out
	return ci
}

func itoa(n int) string { return strconv.Itoa(n) }
