// Package home owns the data dir (~/.setu), atomic JSON files and file locks.
package home

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

type Home struct{ Root string }

// Open returns the data dir: $SETU_HOME or ~/.setu, created with mode 0700.
func Open() (*Home, error) {
	root := os.Getenv("SETU_HOME")
	if root == "" {
		u, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		root = filepath.Join(u, ".setu")
	}
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	return &Home{Root: root}, nil
}

func (h *Home) Path(rel ...string) string {
	return filepath.Join(append([]string{h.Root}, rel...)...)
}

// OldDataDir is the ai-workflow plugin data dir the first start migrates from.
func OldDataDir() string {
	if d := os.Getenv("CLAUDE_PLUGIN_DATA"); d != "" {
		return d
	}
	u, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(u, ".claude", "plugins", "data", "ai-workflow")
}

const markerName = ".migrated"

// Migrate copies old into the home once. It never deletes anything in old. The marker
// .migrated is written only when the copy finished without error, so a failed copy is
// retried (files already copied with the same size are skipped). Lock files and sockets
// are not copied; file modes (e.g. 0600) are preserved; files are streamed.
func Migrate(h *Home, old string) (copied bool, err error) {
	marker := h.Path(markerName)
	if _, err := os.Stat(marker); err == nil {
		return false, nil
	}
	st, err := os.Stat(old)
	if old == "" || err != nil || !st.IsDir() {
		return false, writeMarker(marker, "")
	}
	if a, b := realpath(old), realpath(h.Root); a == b || strings.HasPrefix(b+string(os.PathSeparator), a+string(os.PathSeparator)) {
		return false, fmt.Errorf("home %s is inside the old data dir %s", h.Root, old)
	}
	var errs []error
	n := 0
	buf := make([]byte, 32<<10) // one copy buffer for the whole walk (io.Copy allocates one per file)
	walkErr := filepath.WalkDir(old, func(p string, d fs.DirEntry, werr error) error {
		if werr != nil {
			errs = append(errs, werr)
			if d != nil && d.IsDir() {
				return fs.SkipDir
			}
			return nil
		}
		rel, _ := filepath.Rel(old, p)
		if rel == "." {
			return nil
		}
		dst := filepath.Join(h.Root, rel)
		info, ierr := d.Info()
		if ierr != nil {
			errs = append(errs, ierr)
			return nil
		}
		mode := info.Mode()
		switch {
		case mode.IsDir():
			if err := os.MkdirAll(dst, mode.Perm()|0o700); err != nil {
				errs = append(errs, err)
				return fs.SkipDir
			}
		case mode&os.ModeSymlink != 0:
			target, err := os.Readlink(p)
			if err == nil {
				if _, lerr := os.Lstat(dst); lerr != nil {
					err = os.Symlink(target, dst)
				}
			}
			if err != nil {
				errs = append(errs, err)
			}
		case mode.IsRegular():
			if strings.HasSuffix(d.Name(), ".lock") {
				return nil
			}
			did, err := copyFile(p, dst, info, buf)
			if err != nil {
				errs = append(errs, err)
			} else if did {
				n++
			}
		}
		return nil // sockets, fifos, devices: skipped
	})
	if walkErr != nil {
		errs = append(errs, walkErr)
	}
	if len(errs) > 0 {
		return n > 0, fmt.Errorf("migrate: %d errors, first: %w", len(errs), errs[0])
	}
	return true, writeMarker(marker, "")
}

func realpath(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		return r
	}
	return filepath.Clean(p)
}

func writeMarker(path, body string) error {
	return AtomicWrite(path, []byte(body), 0o644)
}

// copyFile streams src to dst through a temp file, preserving the mode. A destination that
// already has the source's size is left alone (an interrupted migration resumes cheaply).
func copyFile(src, dst string, info fs.FileInfo, buf []byte) (bool, error) {
	if di, err := os.Lstat(dst); err == nil && di.Mode().IsRegular() && di.Size() == info.Size() {
		return false, nil
	}
	in, err := os.Open(src)
	if err != nil {
		return false, err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dst), 0o700); err != nil {
		return false, err
	}
	tmp, err := os.CreateTemp(filepath.Dir(dst), ".migrate-*")
	if err != nil {
		return false, err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.CopyBuffer(struct{ io.Writer }{tmp}, struct{ io.Reader }{in}, buf); err != nil {
		tmp.Close()
		return false, err
	}
	if err := tmp.Chmod(info.Mode().Perm()); err != nil {
		tmp.Close()
		return false, err
	}
	if err := tmp.Close(); err != nil {
		return false, err
	}
	_ = os.Chtimes(tmp.Name(), info.ModTime(), info.ModTime())
	return true, os.Rename(tmp.Name(), dst)
}

// AtomicWrite writes data to a temp file in the same dir, fsyncs and renames it over path.
func AtomicWrite(path string, data []byte, perm fs.FileMode) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	fail := func(err error) error {
		tmp.Close()
		os.Remove(name)
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		return fail(err)
	}
	if err := tmp.Chmod(perm); err != nil {
		return fail(err)
	}
	if err := tmp.Sync(); err != nil {
		return fail(err)
	}
	if err := tmp.Close(); err != nil {
		os.Remove(name)
		return err
	}
	if err := os.Rename(name, path); err != nil {
		os.Remove(name)
		return err
	}
	return nil
}

// ReadJSON decodes path into v. A missing, empty or corrupt file leaves v untouched and
// returns nil; an I/O error is returned.
func ReadJSON(path string, v any) error {
	b, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil
		}
		return err
	}
	if len(bytes.TrimSpace(b)) == 0 || !json.Valid(b) {
		return nil
	}
	// decode into a fresh value first so a type mismatch cannot leave v half-filled
	return decodeInto(b, v)
}

func decodeInto(b []byte, v any) error {
	if err := json.Unmarshal(b, v); err != nil {
		var te *json.UnmarshalTypeError
		if errors.As(err, &te) {
			return nil // wrong shape counts as corrupt
		}
		return err
	}
	return nil
}

// WriteJSON writes v as indent-2 JSON plus a newline, atomically. ui.json and push.json are 0600.
func WriteJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	perm := fs.FileMode(0o644)
	switch filepath.Base(path) {
	case "ui.json", "push.json":
		perm = 0o600
	}
	return AtomicWrite(path, append(b, '\n'), perm)
}

// UpdateJSON is a locked read-modify-write: Lock, BackupIfCorrupt, read, fn, WriteJSON.
// If fn returns an error nothing is written and the (possibly modified) value is returned with it.
func UpdateJSON[T any](path string, fn func(*T) error) (T, error) {
	var v T
	unlock, err := Lock(path)
	if err != nil {
		return v, err
	}
	defer unlock()
	if _, err := BackupIfCorrupt(path); err != nil {
		return v, err
	}
	if err := ReadJSON(path, &v); err != nil {
		return v, err
	}
	if err := fn(&v); err != nil {
		return v, err
	}
	return v, WriteJSON(path, v)
}

// Lock takes a blocking exclusive flock on <path>.lock.
func Lock(path string) (unlock func(), err error) {
	f, err := openLock(path)
	if err != nil {
		return nil, err
	}
	for {
		err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX)
		if err != syscall.EINTR {
			break
		}
	}
	if err != nil {
		f.Close()
		return nil, err
	}
	var done bool
	return func() {
		if !done {
			done = true
			f.Close() // closing releases the flock
		}
	}, nil
}

// TryLock is the non-blocking Lock. The caller keeps the returned file open to hold the
// lock (it can be inherited by a child via ExtraFiles) and closes it to release.
func TryLock(path string) (*os.File, bool, error) {
	f, err := openLock(path)
	if err != nil {
		return nil, false, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		if err == syscall.EWOULDBLOCK {
			return nil, false, nil
		}
		return nil, false, err
	}
	return f, true, nil
}

func openLock(path string) (*os.File, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	return os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0o600)
}

// BackupIfCorrupt renames a non-empty file that is not valid JSON to <path>.corrupt-<unix>
// and returns the new name ("" when nothing was done).
func BackupIfCorrupt(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return "", nil
		}
		return "", err
	}
	if len(bytes.TrimSpace(b)) == 0 || json.Valid(b) {
		return "", nil
	}
	dst := fmt.Sprintf("%s.corrupt-%d", path, time.Now().Unix())
	for i := 1; ; i++ {
		if _, err := os.Lstat(dst); errors.Is(err, fs.ErrNotExist) {
			break
		}
		dst = fmt.Sprintf("%s.corrupt-%d-%d", path, time.Now().Unix(), i)
	}
	return dst, os.Rename(path, dst)
}
