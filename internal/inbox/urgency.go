package inbox

import (
	"context"
	"sync"
)

// Urgency (G§4.3): an optional jev score, 1 to 5, read from jev's cache only. Without jev the
// ranking is group, then newest first.

const (
	urgencyQuestion = "How urgent is this item for the person running these coding sessions?"
	passMax         = 3
	hourlySkip      = 400
)

var urgencyLevels = []string{
	"cosmetic, can wait",
	"minor, can be handled later today",
	"work is waiting on it, but nothing is lost by waiting",
	"blocking work in progress or about to affect other people",
	"irreversible, outward-facing or blocking work right now",
}

type scorer struct {
	b        *Builder
	mu       sync.Mutex
	inflight map[string]bool
}

func newScorer(b *Builder) *scorer { return &scorer{b: b, inflight: map[string]bool{}} }

// UrgencyOf maps a jev score to 1..5 (round half up).
func UrgencyOf(score float64) int {
	n := int(score+0.5) + 1
	if n < 1 {
		n = 1
	}
	if n > 5 {
		n = 5
	}
	return n
}

// of reads the cache; it never calls jev.
func (s *scorer) of(it Item) *int {
	if s.b.d.Jev == nil || it.text == "" {
		return nil
	}
	a := s.b.d.Jev.Peek("urgency", "score", urgencyQuestion, it.text, nil, urgencyLevels)
	if a == nil || a.Status != "ok" {
		return nil
	}
	n := UrgencyOf(a.Score)
	return &n
}

// scan scores up to passMax uncached distinct texts and reports whether any was scored.
func (s *scorer) scan(ctx context.Context) bool {
	j := s.b.d.Jev
	if j == nil || j.Status() != "ok" || j.Spent() >= hourlySkip {
		return false
	}
	list := s.b.Build(ctx, "", "")
	var texts []string
	seen := map[string]bool{}
	s.mu.Lock()
	for _, it := range list.Items {
		if it.text == "" || it.Urgency != nil || seen[it.text] || s.inflight[it.text] {
			continue
		}
		seen[it.text] = true
		texts = append(texts, it.text)
		if len(texts) == passMax {
			break
		}
	}
	for _, t := range texts {
		s.inflight[t] = true
	}
	s.mu.Unlock()
	var wg sync.WaitGroup
	var mu sync.Mutex
	scored := false
	for _, t := range texts {
		wg.Add(1)
		go func(t string) {
			defer wg.Done()
			a := j.Ask(ctx, "urgency", "score", urgencyQuestion, t, nil, urgencyLevels)
			s.mu.Lock()
			delete(s.inflight, t)
			s.mu.Unlock()
			if a.Status == "ok" {
				mu.Lock()
				scored = true
				mu.Unlock()
			}
		}(t)
	}
	wg.Wait()
	return scored
}
