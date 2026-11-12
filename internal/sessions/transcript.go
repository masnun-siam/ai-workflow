package sessions

import (
	"bufio"
	"bytes"
	"errors"
	"io"
	"io/fs"
	"os"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
)

const streamChunk = 4 << 20

// Stream returns the transcript events from byte offset, up to the last newline (a partial last
// line is withheld). For a terminal session an unterminated tail is parsed too. At most about
// 4 MiB per call; the client echoes next.
func (m *Manager) Stream(id string, offset int64) ([]TranscriptEvent, int64, error) {
	rec, err := m.Get(id)
	if err != nil {
		return nil, 0, err
	}
	if offset < 0 {
		return nil, 0, errs.Invalid("bad offset")
	}
	f, err := os.Open(streamPath(m.d.Home, id))
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return []TranscriptEvent{}, offset, nil
		}
		return nil, 0, err
	}
	defer f.Close()
	if _, err := f.Seek(offset, io.SeekStart); err != nil {
		return nil, 0, errs.Invalid("bad offset")
	}
	r := bufio.NewReaderSize(f, 64<<10)
	out := []TranscriptEvent{}
	next := offset
	var read int
	for read < streamChunk {
		line, err := r.ReadBytes('\n')
		if len(line) > 0 && line[len(line)-1] == '\n' {
			next += int64(len(line))
			read += len(line)
			out = appendTranscript(out, line)
			continue
		}
		if len(line) > 0 && rec.Status.Terminal() {
			next += int64(len(line))
			out = appendTranscript(out, line)
		}
		if err != nil {
			break
		}
	}
	return out, next, nil
}

func appendTranscript(out []TranscriptEvent, line []byte) []TranscriptEvent {
	for _, ev := range parseLine(line) {
		if te, ok := ev.transcript(); ok {
			out = append(out, te)
		}
	}
	return out
}

// FinalText is the last result text of the stream, else the last assistant text, else "".
func (m *Manager) FinalText(id string) string {
	f, err := os.Open(streamPath(m.d.Home, id))
	if err != nil {
		return ""
	}
	defer f.Close()
	r := bufio.NewReaderSize(f, 64<<10)
	var lastResult, lastText string
	haveResult := false
	for {
		line, err := r.ReadBytes('\n')
		if len(bytes.TrimSpace(line)) > 0 {
			for _, ev := range parseLine(line) {
				switch ev.Kind {
				case "result":
					if ev.ResultText != nil {
						lastResult, haveResult = *ev.ResultText, true
					}
				case "text":
					lastText = ev.Text
				}
			}
		}
		if err != nil {
			break
		}
	}
	if haveResult {
		return lastResult
	}
	return lastText
}

// ---- cleanup ----

// CleanupTarget is a finished session that can be deleted.
type CleanupTarget struct {
	Key   string   `json:"key"`
	Label string   `json:"label"`
	Repo  string   `json:"repo"`
	Flags []string `json:"flags"`
}

// CleanupTargets lists finished sessions, newest first.
func (m *Manager) CleanupTargets() []CleanupTarget {
	out := []CleanupTarget{}
	for _, r := range m.listAll() {
		if r.Status.Live() {
			continue
		}
		label := strings.TrimSpace(r.Command)
		if label == "" {
			label = "session"
		}
		out = append(out, CleanupTarget{Key: r.ID, Label: label, Repo: r.Repo, Flags: []string{}})
	}
	return out
}

// Cleanup deletes the directories of the given keys that are still finished sessions.
func (m *Manager) Cleanup(keys []string) []string {
	removed := []string{}
	valid := map[string]bool{}
	for _, t := range m.CleanupTargets() {
		valid[t.Key] = true
	}
	for _, k := range keys {
		if !valid[k] || !ValidID(k) {
			continue
		}
		if r, err := m.Get(k); err != nil || r.Status.Live() {
			continue
		}
		recWrites.Add(1)
		if err := os.RemoveAll(sessionDir(m.d.Home, k)); err != nil {
			continue
		}
		recWrites.Add(1)
		m.mu.Lock()
		delete(m.cache, k)
		m.mu.Unlock()
		removed = append(removed, k)
		m.publishRecord(Record{ID: k}, "removed")
	}
	return removed
}
