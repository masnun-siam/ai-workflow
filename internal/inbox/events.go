package inbox

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log"
	"time"

	"github.com/masnun-siam/setu/internal/events"
)

const (
	debounce  = 500 * time.Millisecond
	scanEvery = 30 * time.Second
)

// Fingerprint hashes the (key, content) set of a list.
func Fingerprint(l List) string {
	h := sha256.New()
	b, _ := json.Marshal(l.Items)
	h.Write(b)
	return hex.EncodeToString(h.Sum(nil))
}

// relevant reports whether an event can change the inbox.
func relevant(e events.Event) bool {
	switch e.Topic {
	case events.TSessions, events.TProducts, events.TDispatch:
		return true
	case events.TUsage:
		b, _ := json.Marshal(e.Data)
		var d struct {
			Kind string `json:"kind"`
		}
		_ = json.Unmarshal(b, &d)
		return d.Kind == "away" || d.Kind == "gh"
	}
	return false
}

// Start publishes `inbox{count}` whenever the item set changes. It recomputes 500 ms (debounced)
// after a sessions, products, dispatch or usage{away,gh} event, and scores urgency every 30 s.
// It returns at once.
func (b *Builder) Start(ctx context.Context) {
	if b.d.Bus == nil {
		return
	}
	go func() {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("inbox: loop panic: %v", r)
			}
		}()
		ch, cancel := b.d.Bus.Subscribe(64)
		defer cancel()
		last := Fingerprint(b.Build(ctx, "", ""))
		var timer <-chan time.Time
		scan := time.NewTicker(scanEvery)
		defer scan.Stop()
		recompute := func() {
			l := b.Build(ctx, "", "")
			if fp := Fingerprint(l); fp != last {
				last = fp
				b.d.Bus.Publish(events.TInbox, map[string]any{"count": l.Count})
			}
		}
		for {
			select {
			case <-ctx.Done():
				return
			case e, ok := <-ch:
				if !ok {
					return
				}
				if relevant(e) && timer == nil {
					timer = time.After(debounce)
				}
			case <-timer:
				timer = nil
				recompute()
			case <-scan.C:
				if b.urg.scan(ctx) {
					recompute()
				}
			}
		}
	}()
}
