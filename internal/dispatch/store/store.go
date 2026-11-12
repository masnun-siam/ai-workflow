package store

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

var idRe = regexp.MustCompile(`^[0-9a-f]{12}$`)

// ValidID reports a well-formed dispatch id.
func ValidID(id string) bool { return idRe.MatchString(id) }

func dir(h *home.Home) string { return h.Path("dispatches") }

// Path is the record file of id.
func Path(h *home.Home, id string) (string, error) {
	if !ValidID(id) {
		return "", errs.Invalid("bad dispatch id: %q", id)
	}
	return filepath.Join(dir(h), id+".json"), nil
}

// Load reads one dispatch (errs.NotFound when absent, errs.Invalid for a bad id or a corrupt file).
func Load(h *home.Home, id string) (Dispatch, error) {
	p, err := Path(h, id)
	if err != nil {
		return Dispatch{}, err
	}
	b, err := os.ReadFile(p)
	if errors.Is(err, fs.ErrNotExist) {
		return Dispatch{}, errs.NotFound("no dispatch %s", id)
	}
	if err != nil {
		return Dispatch{}, err
	}
	var d Dispatch
	if err := json.Unmarshal(b, &d); err != nil {
		return Dispatch{}, errs.Invalid("dispatch %s is unreadable: %v", id, err)
	}
	if d.ID == "" {
		d.ID = id
	}
	return d, nil
}

// Save writes the record atomically (indent 1, as the old engine did).
func Save(h *home.Home, d *Dispatch) error {
	p, err := Path(h, d.ID)
	if err != nil {
		return err
	}
	b, err := json.MarshalIndent(d, "", " ")
	if err != nil {
		return err
	}
	return home.AtomicWrite(p, append(b, '\n'), 0o644)
}

// List reads every readable dispatch, newest created_at first. Unreadable files are skipped.
func List(h *home.Home) []Dispatch {
	ents, _ := os.ReadDir(dir(h))
	var out []Dispatch
	for _, e := range ents {
		n := e.Name()
		if e.IsDir() || !strings.HasSuffix(n, ".json") || !ValidID(strings.TrimSuffix(n, ".json")) {
			continue
		}
		if d, err := Load(h, strings.TrimSuffix(n, ".json")); err == nil {
			out = append(out, d)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

// Lock takes the cross-process lock of one dispatch (flock on <id>.lock). Not re-entrant.
func Lock(h *home.Home, id string) (func(), error) {
	if !ValidID(id) {
		return nil, errs.Invalid("bad dispatch id: %q", id)
	}
	return home.Lock(filepath.Join(dir(h), id))
}

// StoreLock is the store-wide lock (.store.lock): the "is this issue already a lane" check and the
// save of a new dispatch are one step.
func StoreLock(h *home.Home) (func(), error) { return home.Lock(filepath.Join(dir(h), ".store")) }

// OwnerOf is the id of the dispatch, not done or cancelled, that has a lane with this key.
func OwnerOf(h *home.Home, key string) string {
	for _, d := range List(h) {
		if d.State != Done && d.State != Cancelled {
			if _, ok := d.Lanes[key]; ok {
				return d.ID
			}
		}
	}
	return ""
}

// Create saves a new dispatch unless one of its lanes already belongs to a live dispatch
// (errs.Conflict carrying that id).
func Create(h *home.Home, d *Dispatch) error {
	unlock, err := StoreLock(h)
	if err != nil {
		return err
	}
	defer unlock()
	for _, k := range d.SortedKeys() {
		if owner := OwnerOf(h, k); owner != "" {
			return errs.Conflict(k+" is already a lane of dispatch "+owner, map[string]any{"id": owner})
		}
	}
	return Save(h, d)
}

// ActiveLane finds the live lane of a running or paused dispatch for issue (>0) or pr (>0),
// repo compared case-insensitively. grind autostart and the pr-grind re-entry leave such PRs to
// the dispatch.
func ActiveLane(h *home.Home, repo string, issue, pr int) (string, Lane, bool) {
	for _, d := range List(h) {
		if !Live(d.State) {
			continue
		}
		for _, k := range d.SortedKeys() {
			l := d.Lanes[k]
			if strings.EqualFold(l.Repo, repo) && Active(l.Stage) &&
				((issue > 0 && l.N == issue) || (pr > 0 && l.PR == pr)) {
				return d.ID, *l, true
			}
		}
	}
	return "", Lane{}, false
}

var prURL = regexp.MustCompile(`github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)`)

// GrindMode is "simple" or "deep" when a running or paused dispatch owns the PR (simple iff its
// grind setting is simple), ok false otherwise (the caller falls back to Settings).
func GrindMode(h *home.Home, prURLStr string) (string, bool) {
	m := prURL.FindStringSubmatch(prURLStr)
	if m == nil {
		return "", false
	}
	n, _ := strconv.Atoi(m[2])
	for _, d := range List(h) {
		if !Live(d.State) {
			continue
		}
		for _, l := range d.Lanes {
			if strings.EqualFold(l.Repo, m[1]) && l.PR == n {
				if d.Settings.Grind == "simple" {
					return "simple", true
				}
				return "deep", true
			}
		}
	}
	return "", false
}

// ArchiveDays is how long a finished dispatch stays in dispatches/.
const ArchiveDays = 30

// ArchiveOld moves done or cancelled dispatches that ended more than days ago to dispatches/archive/
// and returns their ids. Running and paused ones stay, and so does any record that cannot be read.
func ArchiveOld(h *home.Home, now, days float64) []string {
	cutoff := now - days*86400
	ents, _ := os.ReadDir(dir(h))
	var moved []string
	for _, e := range ents {
		n := e.Name()
		id := strings.TrimSuffix(n, ".json")
		if e.IsDir() || id == n || !ValidID(id) {
			continue
		}
		func() {
			unlock, err := Lock(h, id)
			if err != nil {
				return
			}
			defer unlock()
			d, err := Load(h, id) // re-read under the lock: the state may have changed
			if err != nil || (d.State != Done && d.State != Cancelled) {
				return
			}
			at := d.EndedAt
			if at == 0 {
				at = d.CreatedAt
			}
			if at >= cutoff {
				return
			}
			dest := filepath.Join(dir(h), "archive")
			if os.MkdirAll(dest, 0o755) != nil {
				return
			}
			if os.Rename(filepath.Join(dir(h), n), filepath.Join(dest, n)) == nil {
				moved = append(moved, id)
			}
		}()
	}
	return moved
}
