// Package grind: the CLI half of the PR review grind. `setu grind ...` does the mechanics of the
// pr-grind skill (state file, reviewer resolution, Slack and GitHub transport, round parsing and the
// rails); the skill does the judgement. The exit codes are the contract (API.md §8).
//
// Files of this half: state.go (the state file), channels.go, resolve.go (reviewer resolver),
// mode.go, round.go (pure round evaluation), transport.go, ops.go (verbs), cli.go (parsing).
// The server half (re-entry tick, autostart, notify scan, routes) lives in separate files.
package grind

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/home"
)

// StateDir is the folder of the state files inside the home.
const StateDir = "pr-grind"

// Heartbeat is the headless re-entry period (W§6.2 PRGRIND_HEARTBEAT).
const Heartbeat = 1500 * time.Second

var (
	nameRE     = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
	threadRE   = regexp.MustCompile(`^https://\S+$`)
	keyLineRE  = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_-]*: `)
	doneLineRE = regexp.MustCompile(`^done: \d{4}-\d\d-\d\dT`)
	roundRE    = regexp.MustCompile(`^##+ Round [1-9]`)
	sepRE      = regexp.MustCompile(`^\s*[-\x{2014}\x{2013}]+\s+`)
)

// ValidName reports whether s can be an owner or repo part of a state file name.
func ValidName(s string) bool { return nameRE.MatchString(s) && s != "." && !strings.Contains(s, "..") }

// Key identifies one grind.
type Key struct {
	Owner, Repo string
	N           int
}

func (k Key) Slug() string { return k.Owner + "/" + k.Repo }
func (k Key) URL() string {
	return fmt.Sprintf("https://github.com/%s/%s/pull/%d", k.Owner, k.Repo, k.N)
}

func (k Key) base() string {
	return strings.ToLower(k.Owner) + "-" + strings.ToLower(k.Repo) + "-" + strconv.Itoa(k.N)
}

// Files locates state files under a home.
type Files struct{ H *home.Home }

// Dir is the state directory (not created).
func (f Files) Dir() string { return f.H.Path(StateDir) }

// Path is the state file of k: an existing file whose name matches ignoring case, else the
// lowercase name.
func (f Files) Path(k Key) string {
	want := k.base() + ".md"
	if ents, err := os.ReadDir(f.Dir()); err == nil {
		for _, e := range ents {
			if strings.EqualFold(e.Name(), want) {
				return filepath.Join(f.Dir(), e.Name())
			}
		}
	}
	return filepath.Join(f.Dir(), want)
}

// Exists reports whether k has a state file.
func (f Files) Exists(k Key) bool {
	_, err := os.Stat(f.Path(k))
	return err == nil
}

// lockKey is the path handed to home.Lock for read-modify-write. It is NOT the `<state>.lock` file:
// that one is held by a round's child process for the round's life (W§6.1), and a second open of it
// would block this very process.
func lockKey(statePath string) string { return strings.TrimSuffix(statePath, ".md") + ".rmw" }

// LastPath is the `.last.json` next to the state file.
func (f Files) LastPath(k Key) string { return strings.TrimSuffix(f.Path(k), ".md") + ".last.json" }

// Doc is a state file in memory: header lines above the first `## ` line, then rounds.
type Doc struct{ lines []string }

func parseDoc(b []byte) *Doc {
	s := strings.ReplaceAll(string(b), "\r\n", "\n")
	s = strings.TrimSuffix(s, "\n")
	if s == "" {
		return &Doc{}
	}
	return &Doc{lines: strings.Split(s, "\n")}
}

func (d *Doc) bytes() []byte {
	if len(d.lines) == 0 {
		return nil
	}
	return []byte(strings.Join(d.lines, "\n") + "\n")
}

func (d *Doc) headerEnd() int {
	for i, l := range d.lines {
		if strings.HasPrefix(l, "## ") {
			return i
		}
	}
	return len(d.lines)
}

// Get is the value of a header key (split on the first ": ", first occurrence wins). A terminal
// `done: <ISO> - reason` line under a round counts as a header line (W§6.1).
func (d *Doc) Get(key string) string {
	end := d.headerEnd()
	p := key + ": "
	for _, l := range d.lines[:end] {
		if strings.HasPrefix(l, p) {
			return strings.TrimSpace(l[len(p):])
		}
	}
	if key == "done" {
		for _, l := range d.lines[end:] {
			if doneLineRE.MatchString(l) {
				return strings.TrimSpace(l[len(p):])
			}
		}
	}
	return ""
}

// All returns every header value of key (multi-line keys such as ci-attempt).
func (d *Doc) All(key string) []string {
	var out []string
	p := key + ": "
	for _, l := range d.lines[:d.headerEnd()] {
		if strings.HasPrefix(l, p) {
			out = append(out, strings.TrimSpace(l[len(p):]))
		}
	}
	return out
}

// Set replaces the first header line of key in place (dropping later duplicates) or inserts the
// line after the last header `key: value` line.
func (d *Doc) Set(key, val string) {
	line := key + ": " + oneLine(val)
	end := d.headerEnd()
	p := key + ": "
	first := -1
	var out []string
	for i, l := range d.lines {
		if i < end && strings.HasPrefix(l, p) {
			if first >= 0 {
				continue
			}
			first = len(out)
			out = append(out, line)
			continue
		}
		out = append(out, l)
	}
	if first >= 0 {
		d.lines = out
		return
	}
	d.lines = out
	d.insertHeader(line)
}

// Add appends one more header line of key (after the last header key line).
func (d *Doc) Add(key, val string) { d.insertHeader(key + ": " + oneLine(val)) }

func (d *Doc) insertHeader(line string) {
	end := d.headerEnd()
	at := -1
	for i := 0; i < end; i++ {
		if keyLineRE.MatchString(d.lines[i]) {
			at = i + 1
		}
	}
	if at < 0 {
		at = end
		for at > 0 && strings.TrimSpace(d.lines[at-1]) == "" {
			at--
		}
	}
	d.lines = append(d.lines[:at], append([]string{line}, d.lines[at:]...)...)
}

// Del removes every header line of key; for `done` also the terminal lines under a round.
func (d *Doc) Del(key string) {
	end := d.headerEnd()
	p := key + ": "
	var out []string
	for i, l := range d.lines {
		if strings.HasPrefix(l, p) && (i < end || (key == "done" && doneLineRE.MatchString(l))) {
			continue
		}
		out = append(out, l)
	}
	d.lines = out
}

// DelPrefix removes header lines whose text starts with prefix (e.g. "ci-attempt: <sha> ").
func (d *Doc) DelPrefix(prefix string) {
	end := d.headerEnd()
	var out []string
	for i, l := range d.lines {
		if i < end && strings.HasPrefix(l, prefix) {
			continue
		}
		out = append(out, l)
	}
	d.lines = out
}

// HasPrefix reports whether a header line starts with prefix.
func (d *Doc) HasPrefix(prefix string) bool {
	for _, l := range d.lines[:d.headerEnd()] {
		if strings.HasPrefix(l, prefix) {
			return true
		}
	}
	return false
}

// Append adds a line at the end of the file (under the newest round).
func (d *Doc) Append(lines ...string) { d.lines = append(d.lines, lines...) }

// Rounds counts `## Round <n>` sections (a legacy `### Round n` counts too; Round 0 does not).
func (d *Doc) Rounds() int {
	n := 0
	for _, l := range d.lines {
		if roundRE.MatchString(l) {
			n++
		}
	}
	return n
}

// Findings returns every recorded `- finding: <fp>` payload, oldest first.
func (d *Doc) Findings() []string {
	var out []string
	for _, l := range d.lines {
		if strings.HasPrefix(l, "- finding: ") {
			out = append(out, strings.TrimPrefix(l, "- finding: "))
		}
	}
	return out
}

func oneLine(s string) string {
	s = strings.NewReplacer("\r\n", " ", "\n", " ", "\r", " ").Replace(s)
	return strings.TrimSpace(s)
}

// stamp is the ISO-8601 UTC form every state timestamp uses.
func stamp(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05Z") }

// afterStamp strips the leading ISO timestamp and the `-`/em dash separator of a paused:/done: value.
func afterStamp(v string) string {
	if len(v) >= 20 && v[10] == 'T' {
		v = v[20:]
		if i := sepRE.FindStringIndex(v); i != nil {
			return strings.TrimSpace(v[i[1]:])
		}
		return strings.TrimSpace(v)
	}
	if i := sepRE.FindStringIndex(v); i != nil {
		return strings.TrimSpace(v[i[1]:])
	}
	return strings.TrimSpace(v)
}

// ParseTime reads an ISO-8601 stamp (with or without fractional seconds or an offset).
func ParseTime(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	for _, layout := range []string{time.RFC3339, "2006-01-02T15:04:05Z", "2006-01-02T15:04:05"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

// Read loads the state file of k. A missing file is (nil, fs.ErrNotExist).
func (f Files) Read(k Key) (*Doc, error) {
	b, err := os.ReadFile(f.Path(k))
	if err != nil {
		return nil, err
	}
	return parseDoc(b), nil
}

// Update is a locked read-modify-write; the file must exist. fn may call d.Set etc. `updated:` is
// refreshed when the doc changed.
func (f Files) Update(k Key, now time.Time, fn func(d *Doc) error) error {
	return f.update(k, now, false, fn)
}

// Create is Update for a file that may not exist yet (it starts empty).
func (f Files) Create(k Key, now time.Time, fn func(d *Doc) error) error {
	return f.update(k, now, true, fn)
}

func (f Files) update(k Key, now time.Time, create bool, fn func(d *Doc) error) error {
	path := f.Path(k)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	unlock, err := home.Lock(lockKey(path))
	if err != nil {
		return err
	}
	defer unlock()
	var d *Doc
	b, err := os.ReadFile(path)
	switch {
	case err == nil:
		d = parseDoc(b)
	case errors.Is(err, fs.ErrNotExist) && create:
		d = &Doc{}
	default:
		return err
	}
	before := string(d.bytes())
	if err := fn(d); err != nil {
		return err
	}
	if string(d.bytes()) == before {
		return nil
	}
	if d.Get("updated") != "" || len(d.lines) > 0 {
		d.Set("updated", stamp(now))
	}
	return home.AtomicWrite(path, d.bytes(), 0o600)
}

// ---------- status ----------

// State values of Status.State.
const (
	StNone     = "none"
	StIdle     = "idle"
	StRunning  = "running"
	StPaused   = "paused"
	StApproved = "approved"
	StDone     = "done"
)

// Status is the public view of one grind (API §4 GrindStatus).
type Status struct {
	Repo     string  `json:"repo"`
	PR       int     `json:"pr"`
	State    string  `json:"state"`
	Mode     *string `json:"mode"`
	Rounds   int     `json:"rounds"`
	Reason   *string `json:"reason"`
	Thread   *string `json:"thread"`
	Updated  *string `json:"updated"`
	NextPoll *string `json:"next_poll"`
	Session  *string `json:"session"`
	// QueuedPush is the `queued-push:` header (fix commits held back because CI is not green); the
	// pr-grind prompt reads it from `status --json` on re-entry.
	QueuedPush *string `json:"queued_push,omitempty"`
}

func strp(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// ModeOf maps a stored mode to deep|simple (the old `full` is deep); "" when unset or unknown.
func ModeOf(v string) string {
	switch strings.TrimSpace(v) {
	case "simple":
		return "simple"
	case "deep", "full":
		return "deep"
	}
	return ""
}

// StatusOfDoc derives the offline status. The CLI cannot tell a live session from an idle loop, so
// any active file is "running"; the server half downgrades it to "idle" without a live session.
func StatusOfDoc(k Key, d *Doc, modeFallback string, fileMod time.Time) Status {
	st := Status{Repo: k.Slug(), PR: k.N, State: StNone}
	if d == nil {
		return st
	}
	if o, r := d.Get("owner"), d.Get("repo"); o != "" && r != "" {
		st.Repo = o + "/" + r
	}
	done, paused := d.Get("done"), d.Get("paused")
	switch {
	case done != "":
		st.State = StDone
		reason := afterStamp(done)
		st.Reason = strp(reason)
		if strings.HasPrefix(reason, "approved") {
			st.State = StApproved
		}
	case paused != "":
		st.State = StPaused
		st.Reason = strp(afterStamp(paused))
	default:
		st.State = StRunning
	}
	m := ModeOf(d.Get("mode"))
	if m == "" {
		m = ModeOf(modeFallback)
	}
	st.Mode = strp(m)
	st.Rounds = d.Rounds()
	if t := d.Get("thread"); threadRE.MatchString(t) {
		st.Thread = &t
	}
	u := d.Get("updated")
	if u == "" && !fileMod.IsZero() {
		u = stamp(fileMod)
	}
	st.Updated = strp(u)
	st.NextPoll = strp(d.Get("next-poll"))
	st.QueuedPush = strp(d.Get("queued-push"))
	return st
}

// validDoc applies the index validity rules (W§6.1) and accepts `thread: github`.
func validDoc(d *Doc) (Key, bool) {
	o, r, n := d.Get("owner"), d.Get("repo"), d.Get("number")
	if !ValidName(o) || !ValidName(r) || n == "" {
		return Key{}, false
	}
	num, err := strconv.Atoi(n)
	if err != nil || num < 1 || strconv.Itoa(num) != n {
		return Key{}, false
	}
	if t := d.Get("thread"); t != "github" && !threadRE.MatchString(t) {
		return Key{}, false
	}
	return Key{o, r, num}, true
}

// ReadStatus is the offline status of one grind; ok is false when it has no state file.
func ReadStatus(f Files, k Key, modeFallback string) (Status, bool) {
	d, err := f.Read(k)
	if err != nil {
		return Status{Repo: k.Slug(), PR: k.N, State: StNone}, false
	}
	var mod time.Time
	if fi, err := os.Stat(f.Path(k)); err == nil {
		mod = fi.ModTime()
	}
	return StatusOfDoc(k, d, modeFallback, mod), true
}

// Index lists every valid state file's status, sorted by repo then PR.
func Index(f Files, modeFallback string) []Status {
	ents, err := os.ReadDir(f.Dir())
	if err != nil {
		return nil
	}
	var out []Status
	for _, e := range ents {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		b, err := os.ReadFile(filepath.Join(f.Dir(), e.Name()))
		if err != nil {
			continue
		}
		d := parseDoc(b)
		k, ok := validDoc(d)
		if !ok {
			continue
		}
		var mod time.Time
		if fi, err := e.Info(); err == nil {
			mod = fi.ModTime()
		}
		out = append(out, StatusOfDoc(k, d, modeFallback, mod))
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Repo != out[j].Repo {
			return out[i].Repo < out[j].Repo
		}
		return out[i].PR < out[j].PR
	})
	return out
}

// FindByThread returns the key of the state file whose `thread:` equals url (query string ignored).
func (f Files) FindByThread(url string) (Key, bool) {
	url, _, _ = strings.Cut(strings.TrimSpace(url), "?")
	ents, err := os.ReadDir(f.Dir())
	if err != nil || url == "" {
		return Key{}, false
	}
	for _, e := range ents {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		b, err := os.ReadFile(filepath.Join(f.Dir(), e.Name()))
		if err != nil {
			continue
		}
		d := parseDoc(b)
		if d.Get("thread") != url {
			continue
		}
		if k, ok := validDoc(d); ok {
			return k, true
		}
	}
	return Key{}, false
}
