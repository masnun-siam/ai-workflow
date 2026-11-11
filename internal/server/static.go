package server

import (
	"io"
	"io/fs"
	"net/http"
	"path"
	"strings"
	"time"
)

// static serves the embedded UI. Anything that is not a file and does not look like one
// (no extension) falls back to index.html so client routes work. Dot-dot segments, encoded
// escapes left over after decoding (%2e%2e, %252e) and NULs are 404.
func (s *Server) static(w http.ResponseWriter, r *http.Request) {
	p := r.URL.Path
	if strings.ContainsAny(p, "%\x00\\") || hasDotDot(p) {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
		return
	}
	clean := path.Clean("/" + p)
	name := strings.TrimPrefix(clean, "/")
	if name != "" {
		if f, ok := s.open(name); ok {
			s.send(w, r, name, f, clean)
			return
		}
		if path.Ext(name) != "" { // a missing asset is a 404, not the app shell
			writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
			return
		}
	}
	f, ok := s.open("index.html")
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]any{"error": "not found"})
		return
	}
	s.send(w, r, "index.html", f, "/index.html")
}

func hasDotDot(p string) bool {
	for _, seg := range strings.Split(p, "/") {
		if seg == ".." {
			return true
		}
	}
	return false
}

func (s *Server) open(name string) (fs.File, bool) {
	f, err := s.fs.Open(name)
	if err != nil {
		return nil, false
	}
	st, err := f.Stat()
	if err != nil || st.IsDir() {
		f.Close()
		return nil, false
	}
	return f, true
}

func (s *Server) send(w http.ResponseWriter, r *http.Request, name string, f fs.File, urlPath string) {
	defer f.Close()
	if strings.HasPrefix(urlPath, "/assets/") {
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
	} else {
		w.Header().Set("Cache-Control", "no-cache")
	}
	if rs, ok := f.(io.ReadSeeker); ok {
		http.ServeContent(w, r, name, time.Time{}, rs)
		return
	}
	b, err := io.ReadAll(f)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": "internal error"})
		return
	}
	http.ServeContent(w, r, name, time.Time{}, strings.NewReader(string(b)))
}
