package sessions

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
)

var idRe = regexp.MustCompile(`^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}$`)

// ValidID reports whether id is a session id (also the path-traversal guard).
func ValidID(id string) bool { return idRe.MatchString(id) }

func sessionsDir(h *home.Home) string { return h.Path("sessions") }

func sessionDir(h *home.Home, id string) string { return h.Path("sessions", id) }

func metaPath(h *home.Home, id string) string { return filepath.Join(sessionDir(h, id), "meta.json") }

func streamPath(h *home.Home, id string) string {
	return filepath.Join(sessionDir(h, id), "stream.jsonl")
}

// lockDir is the flock target shared with the Python engine: sessions/<id>/.lock.
func lockDir(h *home.Home, id string) (func(), error) {
	return home.Lock(sessionDir(h, id) + string(os.PathSeparator))
}

func newID(t time.Time) string {
	t = t.UTC()
	var b [4]byte
	_, _ = rand.Read(b[:])
	return fmt.Sprintf("%s%06dZ-%s", t.Format("20060102T150405"), t.Nanosecond()/1000, hex.EncodeToString(b[:]))
}

func isoNow(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05Z") }

// readRecord loads meta.json. A missing session is errs.NotFound.
func readRecord(h *home.Home, id string) (Record, error) {
	if !ValidID(id) {
		return Record{}, errs.NotFound("no such session: %s", id)
	}
	b, err := os.ReadFile(metaPath(h, id))
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return Record{}, errs.NotFound("no such session: %s", id)
		}
		return Record{}, err
	}
	var r Record
	if err := json.Unmarshal(b, &r); err != nil {
		return Record{}, errs.NotFound("no such session: %s", id)
	}
	r.ID = id
	return r, nil
}

type statKey struct {
	mtime int64
	size  int64
}

// updateRecord is the flock read-modify-write of meta.json. fn's error aborts without writing.
// It returns the record before and after, and the stat of the written file.
//
// fn gets the stat of meta.json as read (to spot a write by another process); post runs under the
// lock right after a successful write.
func updateRecord(h *home.Home, id string, fn func(*Record, statKey) error, post func(Record, statKey)) (prev, next Record, st statKey, err error) {
	if !ValidID(id) {
		return prev, next, st, errs.NotFound("no such session: %s", id)
	}
	if _, serr := os.Stat(metaPath(h, id)); serr != nil {
		return prev, next, st, errs.NotFound("no such session: %s", id)
	}
	unlock, err := lockDir(h, id)
	if err != nil {
		return prev, next, st, err
	}
	defer unlock()
	path := metaPath(h, id)
	if _, err := home.BackupIfCorrupt(path); err != nil {
		return prev, next, st, err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return prev, next, st, errs.NotFound("no such session: %s", id)
	}
	if err := json.Unmarshal(b, &prev); err != nil {
		return prev, next, st, errs.NotFound("no such session: %s", id)
	}
	prev.ID = id
	next = prev
	if err := fn(&next, statOf(path)); err != nil {
		return prev, next, st, err
	}
	next.ID = id
	if err := home.WriteJSON(path, next); err != nil {
		return prev, next, st, err
	}
	st = statOf(path)
	if post != nil {
		post(next, st)
	}
	return prev, next, st, nil
}

// ---- Manager storage methods ----

type cached struct {
	st  statKey
	idx int // position in Manager.all
}

func (m *Manager) create(rec Record) (Record, error) {
	if err := os.MkdirAll(sessionsDir(m.d.Home), 0o700); err != nil {
		return rec, err
	}
	for i := 0; ; i++ {
		rec.ID = newID(m.d.now())
		if err := os.Mkdir(sessionDir(m.d.Home, rec.ID), 0o700); err == nil {
			break
		} else if !errors.Is(err, fs.ErrExist) || i > 5 {
			return rec, err
		}
	}
	f, err := os.OpenFile(streamPath(m.d.Home, rec.ID), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return rec, err
	}
	f.Close()
	rec.StartedAt = isoNow(m.d.now())
	if err := home.WriteJSON(metaPath(m.d.Home, rec.ID), rec); err != nil {
		return rec, err
	}
	m.publishRecord(rec, "record")
	m.trackMeta(rec.ID, rec.Status, statOf(metaPath(m.d.Home, rec.ID)))
	return rec, nil
}

func statOf(path string) statKey {
	fi, err := os.Stat(path)
	if err != nil {
		return statKey{}
	}
	return statKey{fi.ModTime().UnixNano(), fi.Size()}
}

// Get returns one record.
func (m *Manager) Get(id string) (Record, error) { return readRecord(m.d.Home, id) }

// Update is the flock read-modify-write. It publishes the sessions event and, when the status
// (or the pending round) changed, sends the deduped notification.
func (m *Manager) Update(id string, fn func(*Record) error) (Record, error) {
	return m.update(id, fn, false)
}

func (m *Manager) update(id string, fn func(*Record) error, external bool) (Record, error) {
	var note string
	_, next, _, err := updateRecord(m.d.Home, id, func(r *Record, pre statKey) error {
		before := *r
		m.mu.Lock()
		seen, tracked := m.metaSeen[id]
		m.mu.Unlock()
		if external || (tracked && pre != seen) {
			// another process (`setu ask`) wrote since our last write: judge the status as new
			before.Status = ""
			before.PendingQuestion = nil
		}
		if err := fn(r); err != nil {
			return err
		}
		note = dedupe(before, r)
		return nil
	}, func(r Record, st statKey) { m.trackMeta(id, r.Status, st) })
	if err != nil {
		return next, err
	}
	m.publishRecord(next, "record")
	if note != "" {
		m.sendNotify(note, next)
	}
	return next, nil
}

// dedupe maintains rec.Notified and returns the event to send ("" = none). Keys: waiting:<round>,
// done, failed, stalled. Moving to starting or running forgets done, failed and stalled so a resumed
// run notifies again. A run the idle guard marked stalled ends as stalled instead of done; a lane's
// session sends nothing for it, since its lane notifies.
func dedupe(prev Record, r *Record) string {
	if r.Status == StStarting || r.Status == StRunning {
		if prev.Status != r.Status {
			r.Notified = without(r.Notified, "done", "failed", "stalled")
		}
		return ""
	}
	var key, event string
	switch r.Status {
	case StWaiting:
		event, key = "waiting", "waiting"
		if r.PendingQuestion != nil && r.PendingQuestion.ID != "" {
			key = "waiting:" + r.PendingQuestion.ID
		}
		pid, rid := "", ""
		if prev.PendingQuestion != nil {
			pid = prev.PendingQuestion.ID
		}
		if r.PendingQuestion != nil {
			rid = r.PendingQuestion.ID
		}
		if prev.Status == StWaiting && pid == rid {
			return ""
		}
	case StDone, StFailed:
		event, key = string(r.Status), string(r.Status)
		if prev.Status == r.Status {
			return ""
		}
		if r.Status == StDone && r.Stalled != "" {
			if r.Kind == "lane" {
				return ""
			}
			event, key = "stalled", "stalled"
		}
	default:
		return ""
	}
	if r.Role == "away-answerer" {
		return ""
	}
	for _, k := range r.Notified {
		if k == key {
			return ""
		}
	}
	r.Notified = append(r.Notified, key)
	return event
}

func without(list []string, drop ...string) []string {
	var out []string
	for _, s := range list {
		keep := true
		for _, d := range drop {
			if s == d {
				keep = false
			}
		}
		if keep {
			out = append(out, s)
		}
	}
	return out
}

func (m *Manager) sendNotify(event string, r Record) {
	if m.d.Notify == nil {
		return
	}
	n := Note{ID: r.ID, Repo: m.slugOf(r), Command: r.Command, SessionID: r.SessionID, Error: r.Error, Step: m.stepOf(r), Link: r.Link}
	if event == "stalled" {
		n.Text = r.Stalled
	}
	if event == "waiting" && r.PendingQuestion != nil && len(r.PendingQuestion.Questions) > 0 {
		q := r.PendingQuestion.Questions[0]
		n.Question = q.Question
		if n.Question == "" {
			n.Question = q.Header
		}
		if q.Recommended != nil {
			n.Recommended = *q.Recommended
		}
	}
	m.d.Notify.Notify(event, n)
}

func (m *Manager) publishRecord(r Record, change string) {
	if m.d.Bus == nil {
		return
	}
	m.d.Bus.Publish(events.TSessions, map[string]any{"id": r.ID, "status": r.Status, "change": change})
}

func (m *Manager) trackMeta(id string, status Status, st statKey) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if status.Terminal() || status == "" {
		delete(m.metaSeen, id)
		return
	}
	m.metaSeen[id] = st
}

// racyWindow: a file whose mtime is this close to the scan may be rewritten within the same
// filesystem timestamp tick with the same size, so its stat key proves nothing and it is re-read.
const racyWindow = 2 * time.Second

// listAll returns every record, newest first, as a slice shared with the next callers: range over
// it, never modify it. Every call validates each meta.json by stat, so a write by any process
// (the child's `setu ask`, the CLI) shows on the next read.
func (m *Manager) listAll() []Record { return m.scanAll() }

// scanAll reads every record, newest first. A record whose meta.json is unchanged (stat key) is
// taken from the previous result instead of being parsed again; the cache holds only the stat key
// and the index there, so a record is in memory once.
func (m *Manager) scanAll() []Record {
	ents, err := os.ReadDir(sessionsDir(m.d.Home))
	if err != nil {
		return nil
	}
	names := make([]string, 0, len(ents))
	for _, e := range ents {
		if e.IsDir() && ValidID(e.Name()) {
			names = append(names, e.Name())
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(names)))
	m.mu.Lock()
	prev, old := m.all, m.cache
	m.mu.Unlock()
	now := time.Now()
	out := make([]Record, 0, len(names))
	next := make(map[string]cached, len(names))
	for _, id := range names {
		p := metaPath(m.d.Home, id)
		st := statOf(p)
		if st == (statKey{}) {
			continue
		}
		if c, ok := old[id]; ok && c.st == st && now.Sub(time.Unix(0, st.mtime)) > racyWindow && c.idx < len(prev) && prev[c.idx].ID == id {
			next[id] = cached{st, len(out)}
			out = append(out, prev[c.idx])
			continue
		}
		b, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		var r Record
		if json.Unmarshal(b, &r) != nil {
			continue
		}
		r.ID = id
		next[id] = cached{st, len(out)}
		out = append(out, r)
	}
	m.mu.Lock()
	m.cache, m.all = next, out
	m.mu.Unlock()
	return out
}

// List returns records newest first, filtered.
func (m *Manager) List(f Filter) []Record {
	all := m.listAll()
	var out []Record
	if f.Limit > 0 {
		out = make([]Record, 0, min(f.Limit, len(all)))
	}
	for _, r := range all {
		if r.Role == "away-answerer" && !f.Answerers {
			continue
		}
		if f.Before != "" && r.ID >= f.Before {
			continue
		}
		if len(f.Statuses) > 0 {
			ok := false
			for _, s := range f.Statuses {
				ok = ok || s == r.Status
			}
			if !ok {
				continue
			}
		}
		if f.Repo != "" && !equalFold(m.slugOf(r), f.Repo) {
			continue
		}
		if f.Step != "" && m.stepOf(r) != f.Step {
			continue
		}
		out = append(out, r)
		if f.Limit > 0 && len(out) >= f.Limit {
			break
		}
	}
	return out
}
