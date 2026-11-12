package store

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

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

type listEntry struct {
	mtime, ctime, size int64
	ino                uint64
	d                  Dispatch
}

// racyWindow: a file whose mtime is this close to the scan may be rewritten within the same
// filesystem timestamp tick, so its stat key proves nothing and it is parsed again.
const racyWindow = 2 * time.Second

var listCache struct {
	sync.Mutex
	root  string
	m     map[string]listEntry
	lanes map[string]string // valid until a scan sees any change
}

// ListShared is List for read-only callers (liveLanes, Repos, tick scans): every call stats each
// record (so a write by any process shows at once) and re-parses only a record whose file
// changed (mtime, ctime, size, inode) or is too young to trust. The returned values share maps
// with the cache: callers must not modify them.
func ListShared(h *home.Home) []Dispatch {
	listCache.Lock()
	defer listCache.Unlock()
	return slices.Clone(listLocked(h))
}

// listLocked needs listCache locked.
func listLocked(h *home.Home) []Dispatch {
	if listCache.root != h.Root || listCache.m == nil {
		listCache.root, listCache.m, listCache.lanes = h.Root, map[string]listEntry{}, nil
	}
	ents, _ := os.ReadDir(dir(h))
	now := time.Now()
	seen := make(map[string]bool, len(ents))
	changed := false
	var out []Dispatch
	for _, e := range ents {
		n := e.Name()
		id := strings.TrimSuffix(n, ".json")
		if e.IsDir() || !strings.HasSuffix(n, ".json") || !ValidID(id) {
			continue
		}
		fi, err := os.Stat(filepath.Join(dir(h), n))
		if err != nil {
			continue
		}
		seen[id] = true
		k := listEntry{mtime: fi.ModTime().UnixNano(), size: fi.Size()}
		k.ctime, k.ino = statExtra(fi)
		c, ok := listCache.m[id]
		if !ok || c.mtime != k.mtime || c.size != k.size || c.ctime != k.ctime || c.ino != k.ino || now.Sub(fi.ModTime()) < racyWindow {
			d, err := Load(h, id)
			if err != nil {
				delete(listCache.m, id)
				changed = true
				continue
			}
			k.d = d
			if !ok || !reflect.DeepEqual(c.d, d) {
				changed = true
			}
			c = k
			listCache.m[id] = c
		}
		out = append(out, c.d)
	}
	for id := range listCache.m {
		if !seen[id] {
			delete(listCache.m, id)
			changed = true
		}
	}
	if changed {
		listCache.lanes = nil
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
	for _, d := range ListShared(h) {
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
	for _, d := range ListShared(h) {
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
	mode, ok := liveLanes(h)[strings.ToLower(m[1])+"#"+strconv.Itoa(n)]
	return mode, ok
}

// liveLanes maps "owner/repo#pr" to the grind mode of the live dispatch that owns it. The grind
// index asks once per PR, so the map is built once per state of dispatches/.
func liveLanes(h *home.Home) map[string]string {
	listCache.Lock()
	defer listCache.Unlock()
	list := listLocked(h)
	if listCache.lanes != nil {
		return listCache.lanes
	}
	out := map[string]string{}
	for _, d := range list {
		if !Live(d.State) {
			continue
		}
		mode := "deep"
		if d.Settings.Grind == "simple" {
			mode = "simple"
		}
		for _, l := range d.Lanes {
			k := strings.ToLower(l.Repo) + "#" + strconv.Itoa(l.PR)
			if _, dup := out[k]; !dup {
				out[k] = mode
			}
		}
	}
	listCache.lanes = out
	return out
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
