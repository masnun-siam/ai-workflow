package sessions

import (
	"context"
	"time"
)

// Reconcile is restart recovery (S§1.13): re-attach sessions whose claude outlived the server,
// close the ones that died meanwhile. Call once at start, before Start.
func (m *Manager) Reconcile(ctx context.Context) error {
	for _, rec := range m.listAll() {
		id := rec.ID
		func() {
			defer func() {
				if r := recover(); r != nil {
					logf("sessions: reconcile of %s failed: %v", id, r)
				}
			}()
			m.mu.Lock()
			_, tracked := m.procs[id]
			m.mu.Unlock()
			if rec.Status == StWaiting && rec.PidStarted != "" && rec.EndedAt == "" {
				if !tracked {
					m.watchWaiting(id, rec.PID, rec.PidStarted)
				}
				return
			}
			if (rec.Status != StStarting && rec.Status != StRunning) || tracked {
				return
			}
			if rec.PID == 0 {
				_, _ = m.Update(id, func(r *Record) error {
					r.Status, r.EndedAt = StFailed, isoNow(m.d.now())
					r.Error = "session never started (UI exited before spawn)"
					return nil
				})
				return
			}
			p := &proc{pid: rec.PID}
			cur, _ := psStart(ctx, rec.PID)
			if rec.PidStarted != "" && cur == rec.PidStarted {
				m.mu.Lock()
				m.procs[id] = p
				m.mu.Unlock()
				go m.follow(id, p, rec.PID, rec.PidStarted, rec.StreamOffset, false, false)
				return
			}
			// not ours any more or dead: judge from the stream, inline
			m.follow(id, p, rec.PID, rec.PidStarted, rec.StreamOffset, false, false)
		}()
	}
	return nil
}

// watchWaiting holds a waiting session's surviving claude in the process map, so no answer
// resumes a second process, and stamps ended_at once it exits (that unlocks the answer form).
// It never touches the status or the round.
func (m *Manager) watchWaiting(id string, pid int, started string) {
	closeIt := func() {
		if cur, err := m.Get(id); err == nil && cur.Status == StWaiting {
			_, _ = m.Update(id, func(r *Record) error { r.EndedAt = isoNow(m.d.now()); return nil })
		}
	}
	cur, failed := psStart(context.Background(), pid)
	if !failed && cur != started {
		closeIt()
		return
	}
	p := &proc{pid: pid}
	m.mu.Lock()
	m.procs[id] = p
	m.mu.Unlock()
	go func() {
		defer func() {
			if r := recover(); r != nil {
				logf("sessions: waiting watcher for %s failed: %v", id, r)
			}
			m.mu.Lock()
			if m.procs[id] == p {
				delete(m.procs, id)
				delete(m.stopping, id)
			}
			m.mu.Unlock()
		}()
		errors := 0
		for {
			cur, failed := psStart(context.Background(), pid)
			if failed {
				errors++
			} else {
				errors = 0
			}
			if (!failed && cur != started) || errors > 25 {
				break
			}
			time.Sleep(time.Second)
		}
		closeIt()
	}()
}
