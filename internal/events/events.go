// Package events is the in-process pub/sub behind the SSE stream.
package events

import (
	"sync"
	"sync/atomic"
)

type Topic string

const (
	TSessions Topic = "sessions"
	TInbox    Topic = "inbox"
	TProducts Topic = "products"
	TDispatch Topic = "dispatch"
	TUsage    Topic = "usage"
	TToast    Topic = "toast"
	// THello is only produced by the bus itself: a slow subscriber lost events and must refetch.
	THello Topic = "hello"
)

type Event struct {
	ID    uint64
	Topic Topic
	Data  any
}

type sub struct{ ch chan Event }

type Bus struct {
	mu   sync.Mutex
	subs map[*sub]struct{}
	seq  atomic.Uint64
}

func New() *Bus { return &Bus{subs: map[*sub]struct{}{}} }

// Publish never blocks. A subscriber whose buffer is full loses its queued events and
// receives a single hello{resync:true} instead.
func (b *Bus) Publish(t Topic, data any) {
	ev := Event{ID: b.seq.Add(1), Topic: t, Data: data}
	b.mu.Lock()
	defer b.mu.Unlock()
	for s := range b.subs {
		select {
		case s.ch <- ev:
			continue
		default:
		}
		for drained := false; !drained; { // full: drop everything queued, leave one resync marker
			select {
			case <-s.ch:
			default:
				drained = true
			}
		}
		select {
		case s.ch <- Event{ID: ev.ID, Topic: THello, Data: map[string]any{"resync": true}}:
		default:
		}
	}
}

// Subscribe returns a channel with the given buffer (min 2) and a cancel func that frees it.
// The channel is never closed.
func (b *Bus) Subscribe(buf int) (<-chan Event, func()) {
	if buf < 2 {
		buf = 2
	}
	s := &sub{ch: make(chan Event, buf)}
	b.mu.Lock()
	b.subs[s] = struct{}{}
	b.mu.Unlock()
	var once sync.Once
	return s.ch, func() {
		once.Do(func() {
			b.mu.Lock()
			delete(b.subs, s)
			b.mu.Unlock()
		})
	}
}

// Subscribers is the number of live subscribers; >0 means a UI is present.
func (b *Bus) Subscribers() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.subs)
}
