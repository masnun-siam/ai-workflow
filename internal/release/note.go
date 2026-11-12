package release

import (
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/sessions"
)

// MaxNote is the longest note PUT accepts.
const MaxNote = 8000

// readNote returns the note file (capped), ok=false when there is none.
func (s *Service) readNote(id string) (string, bool) {
	f, err := os.Open(s.noteFile(id))
	if err != nil {
		return "", false
	}
	defer f.Close()
	b, _ := io.ReadAll(io.LimitReader(f, maxNoteBytes))
	return string(b), true
}

func (s *Service) live(sid *string) bool {
	if sid == nil {
		return false
	}
	rec, err := s.d.Sessions.Get(*sid)
	return err == nil && rec.Status.Live()
}

// startDraft launches the release-note session in draft mode. A live draft is left alone.
func (s *Service) startDraft(ctx context.Context, id string) (record, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	r, err := s.load(id)
	if err != nil {
		return r, err
	}
	if r.Stage != StNotify || r.PRURL == nil {
		return r, errs.Conflict("the release is not merged yet", nil)
	}
	if r.PostAttemptedAt != "" || r.PostedAt != nil {
		return r, errs.Conflict("the release note was already posted", nil)
	}
	if s.live(r.NoteSess) {
		return r, nil
	}
	file := s.noteFile(id)
	if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
		return r, err
	}
	_ = os.Remove(file)
	args := *r.PRURL + " --draft " + file
	p, err := s.d.Prompts.BuildIn("release-note", args, "")
	if err != nil {
		return r, err
	}
	rec, err := s.d.Sessions.Launch(ctx, sessions.Spec{Prompt: sessions.Prompt(p), Args: args,
		Cwd: filepath.Dir(file), Kind: "release-note", Fields: map[string]any{"release": id}})
	if err != nil {
		return r, err
	}
	return s.mutate(id, func(x *record) error {
		x.NoteSess, x.NoteFile, x.DraftNotified, x.Error = sp(rec.ID), file, false, nil
		return nil
	})
}

// DraftNote starts (or redoes) the release-note draft session.
func (s *Service) DraftNote(ctx context.Context, id string) (Release, error) {
	r, err := s.startDraft(ctx, id)
	if err != nil {
		return Release{}, err
	}
	return s.Public(r), nil
}

// SaveNote stores the edited note (Slack mrkdwn, at most 8000 characters).
func (s *Service) SaveNote(id, text string) (Release, error) {
	if strings.TrimSpace(text) == "" {
		return Release{}, errs.Invalid("text must not be empty")
	}
	if utf8.RuneCountInString(text) > MaxNote || strings.ContainsRune(text, 0) {
		return Release{}, errs.Invalid("text must be at most %d characters", MaxNote)
	}
	r, err := s.mutate(id, func(x *record) error {
		if x.Stage != StNotify {
			return errs.Conflict("the release is not waiting for a note (stage "+x.Stage+")", nil)
		}
		if x.PostAttemptedAt != "" {
			return errs.Conflict("the release note was already posted", nil)
		}
		file := s.noteFile(x.ID)
		if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
			return err
		}
		if err := home.AtomicWrite(file, []byte(text), 0o644); err != nil {
			return err
		}
		x.NoteFile, x.Error = file, nil
		return nil
	})
	if err != nil {
		return Release{}, err
	}
	return s.Public(r), nil
}

// Post sends the note to Slack with slackcli. It sends exactly once: the attempt is recorded
// before slackcli runs, a failure keeps the error and is never retried, and a second call is a 409.
func (s *Service) Post(ctx context.Context, id string) (Release, error) {
	var channel string
	r, err := s.mutate(id, func(x *record) error {
		if x.Stage != StNotify {
			return errs.Conflict("the release is not waiting for its note (stage "+x.Stage+")", nil)
		}
		if x.PostAttemptedAt != "" {
			return errs.Conflict("the release note was already posted or the post was attempted; it is never retried", nil)
		}
		if s.live(x.NoteSess) {
			return errs.Conflict("the note draft is still being written", nil)
		}
		t, ok := s.readNote(x.ID)
		if !ok || strings.TrimSpace(t) == "" {
			return errs.Conflict("the release has no note to post", nil)
		}
		ch := s.d.Settings.Get().ReleaseNote.ChannelID
		if ch == "" {
			return errs.Conflict("no release-note channel is set in Settings", nil)
		}
		channel = ch
		x.PostAttemptedAt, x.Error = ts(s.now()), nil
		return nil
	})
	if err != nil {
		return Release{}, err
	}
	// The note is sent from the file as saved, so what was previewed is what is posted.
	res := execx.Run(ctx, []string{"slackcli", "messages", "send", "--recipient-id", channel,
		"--message-file", s.noteFile(id), "--json"}, execx.Opts{Timeout: 60 * time.Second})
	if res.Code != 0 {
		msg := "slack post failed: " + res.LastLine()
		r, _ = s.mutate(id, func(x *record) error { x.Error = sp(msg); return nil })
		s.toast("error", "Release note not posted", msg, "#/releases/"+id)
		return s.Public(r), errs.Upstream("%s", msg)
	}
	link := permalink(res.Stdout)
	r, err = s.mutate(id, func(x *record) error {
		x.Stage, x.PostedAt, x.Error = StDone, sp(ts(s.now())), nil
		if link != "" {
			x.Permalink = sp(link)
		}
		return nil
	})
	if err != nil {
		return Release{}, err
	}
	s.toast("info", "Release note posted", r.Repo+" release note is in Slack", "#/releases/"+id)
	if s.d.Notify != nil {
		s.d.Notify.Notify("release", notify.Note{ID: "release-posted-" + id, Repo: r.Repo, Step: "release-note",
			Text: r.Repo + " release note posted"})
	}
	return s.Public(r), nil
}

func (s *Service) toast(level, title, body, path string) {
	if s.d.Bus == nil {
		return
	}
	s.d.Bus.Publish(events.TToast, map[string]any{"id": time.Now().UnixNano(), "event": level,
		"title": title, "body": body, "path": path, "level": level})
}

// permalink finds the first "permalink" (else "url") string in slackcli's JSON output.
func permalink(out []byte) string {
	var v any
	if json.Unmarshal(out, &v) != nil {
		return ""
	}
	if s := find(v, "permalink"); s != "" {
		return s
	}
	return find(v, "url")
}

func find(v any, key string) string {
	switch x := v.(type) {
	case map[string]any:
		if s, ok := x[key].(string); ok && strings.HasPrefix(s, "http") {
			return s
		}
		for _, c := range x {
			if s := find(c, key); s != "" {
				return s
			}
		}
	case []any:
		for _, c := range x {
			if s := find(c, key); s != "" {
				return s
			}
		}
	}
	return ""
}
