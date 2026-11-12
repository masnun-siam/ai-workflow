package pollertest

import (
	"context"
	"testing"

	"github.com/masnun-siam/setu/internal/poller"
)

func TestFixedSnapshots(t *testing.T) {
	d := poller.EmptyData()
	d.Issues = []poller.Issue{{N: 3}}
	p := New(Fresh("o/r", d), Stale("o/old", poller.EmptyData()))
	if s := p.Snapshot("o/r"); !s.Fresh() || len(s.Data.Issues) != 1 {
		t.Fatalf("%v", s)
	}
	if s := p.Snapshot("o/old"); s.Fresh() {
		t.Fatalf("%v", s)
	}
	if s := p.Poll(context.Background(), "o/r", true); !s.Stale { // no network: the poll fails stale
		t.Fatalf("%v", s)
	}
}
