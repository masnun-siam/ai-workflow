package sessions

import (
	"context"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// Manager owns every session of one setu home.
type Manager struct {
	d Deps

	mu       sync.Mutex
	procs    map[string]*proc // live claude processes of this server (cmd nil: re-attached)
	stopping map[string]bool
	cache    map[string]cached
	all      []Record // last listAll result, valid for allVer and listFresh
	allVer   uint64
	allAt    time.Time
	metaSeen map[string]statKey // stat of meta.json after our last write, for live sessions
	streamAt map[string]time.Time
	usage    map[string]map[string]any // account cmd -> last rate_limit_info (warnings, in memory)

	poll, grace, stopGrace, stagger time.Duration

	batchMu  sync.Mutex
	resumeMu sync.Mutex
	startMu  sync.Mutex
	recent   map[string]recentStart
}

type recentStart struct {
	at time.Time
	id string
}

// New builds a Manager. Deps.Home is required.
func New(d Deps) *Manager {
	if d.BinDir == "" {
		if exe, err := os.Executable(); err == nil {
			d.BinDir = filepath.Dir(exe)
		}
	}
	return &Manager{
		d:        d,
		procs:    map[string]*proc{},
		stopping: map[string]bool{},
		cache:    map[string]cached{},
		metaSeen: map[string]statKey{},
		streamAt: map[string]time.Time{},
		usage:    map[string]map[string]any{},
		recent:   map[string]recentStart{},
		poll:     defPoll, grace: defAskedGrace, stopGrace: defStopGrace, stagger: defLimitStagger,
	}
}

// Alive reports whether this server holds a process (or re-attached watcher) for the session.
func (m *Manager) Alive(id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	_, ok := m.procs[id]
	return ok
}

func (m *Manager) isStopping(id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.stopping[id]
}

// Start runs the limit tick (30 s, first tick at once) and the meta watcher (1 s) until ctx ends.
func (m *Manager) Start(ctx context.Context) {
	go m.supervise(ctx, "limit tick", func(ctx context.Context) {
		m.limitTick(ctx)
		t := time.NewTicker(limitTickEvery)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				m.limitTick(ctx)
			}
		}
	})
	go m.supervise(ctx, "meta watcher", func(ctx context.Context) {
		t := time.NewTicker(time.Second)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				m.watchMeta()
			}
		}
	})
}

// supervise reruns fn after a panic (logged), never fatal.
func (m *Manager) supervise(ctx context.Context, name string, fn func(context.Context)) {
	for ctx.Err() == nil {
		panicked := false
		func() {
			defer func() {
				if r := recover(); r != nil {
					panicked = true
					logf("sessions: %s panicked: %v", name, r)
				}
			}()
			fn(ctx)
		}()
		if !panicked {
			return
		}
		select {
		case <-ctx.Done():
		case <-time.After(5 * time.Second):
		}
	}
}

// watchMeta notices meta.json changes made by another process (`setu ask` in a child) and turns
// them into the sessions event and the waiting notification, once.
func (m *Manager) watchMeta() {
	m.mu.Lock()
	ids := make([]string, 0, len(m.metaSeen))
	for id := range m.metaSeen {
		ids = append(ids, id)
	}
	m.mu.Unlock()
	for _, id := range ids {
		st := statOf(metaPath(m.d.Home, id))
		m.mu.Lock()
		seen, ok := m.metaSeen[id]
		m.mu.Unlock()
		if !ok || st == seen || st == (statKey{}) {
			continue
		}
		// changed behind our back: re-read, notify when it is a new waiting round
		rec, err := m.Get(id)
		if err != nil {
			continue
		}
		if rec.Status == StWaiting {
			if _, err := m.update(id, func(*Record) error { return nil }, true); err == nil {
				continue
			}
		}
		m.trackMeta(id, rec.Status, st)
		m.publishRecord(rec, "record")
	}
}

func logf(format string, a ...any) { log.Printf(format, a...) }
