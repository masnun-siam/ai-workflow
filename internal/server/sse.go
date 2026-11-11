package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/masnun-siam/setu/internal/events"
)

// serveEvents is GET /api/events (API.md §6). Last-Event-ID is ignored: the UI refetches on hello.
func (s *Server) serveEvents(w http.ResponseWriter, r *http.Request) {
	rc := http.NewResponseController(w)
	ch, cancel := s.bus.Subscribe(64)
	defer cancel()
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)
	_ = rc.SetWriteDeadline(time.Time{})
	if _, err := fmt.Fprint(w, "retry: 3000\n\n"); err != nil {
		return
	}
	if !s.writeEvent(w, rc, 0, "hello", map[string]any{"version": s.cfg.Version, "boot_id": s.bootID, "resync": false}) {
		return
	}
	tick := time.NewTicker(s.pingEvery)
	defer tick.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-s.quit:
			return
		case <-tick.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil || rc.Flush() != nil {
				return
			}
		case ev := <-ch:
			name, data := string(ev.Topic), ev.Data
			if ev.Topic == events.THello {
				data = map[string]any{"version": s.cfg.Version, "boot_id": s.bootID, "resync": true}
			}
			if !s.writeEvent(w, rc, ev.ID, name, data) {
				return
			}
		}
	}
}

func (s *Server) writeEvent(w http.ResponseWriter, rc *http.ResponseController, id uint64, name string, data any) bool {
	b, err := json.Marshal(data)
	if err != nil {
		b = []byte("null")
	}
	if _, err := fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", id, name, b); err != nil {
		return false
	}
	return rc.Flush() == nil
}
