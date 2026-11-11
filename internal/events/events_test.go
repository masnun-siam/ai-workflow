package events

import (
	"testing"
	"time"
)

func recv(t *testing.T, ch <-chan Event) Event {
	t.Helper()
	select {
	case e := <-ch:
		return e
	case <-time.After(time.Second):
		t.Fatal("no event")
		return Event{}
	}
}

func TestFanOut(t *testing.T) {
	b := New()
	var chans []<-chan Event
	for i := 0; i < 5; i++ {
		ch, cancel := b.Subscribe(8)
		defer cancel()
		chans = append(chans, ch)
	}
	if b.Subscribers() != 5 {
		t.Fatal(b.Subscribers())
	}
	b.Publish(TSessions, "a")
	b.Publish(TInbox, "b")
	for _, ch := range chans {
		e1, e2 := recv(t, ch), recv(t, ch)
		if e1.Topic != TSessions || e1.Data != "a" || e2.Topic != TInbox || e2.ID <= e1.ID {
			t.Fatalf("%+v %+v", e1, e2)
		}
	}
}

func TestSlowSubscriberGetsResync(t *testing.T) {
	b := New()
	slow, cancel := b.Subscribe(2)
	defer cancel()
	fast, cancelFast := b.Subscribe(100)
	defer cancelFast()
	for i := 0; i < 10; i++ {
		b.Publish(TToast, i)
	}
	e := recv(t, slow)
	if e.Topic != THello || e.Data.(map[string]any)["resync"] != true {
		t.Fatalf("%+v", e)
	}
	for i := 0; i < 10; i++ { // the fast one lost nothing
		if got := recv(t, fast); got.Data != i {
			t.Fatalf("%+v", got)
		}
	}
	if e := recv(t, slow); e.Data != 9 { // events after the marker still arrive
		t.Fatalf("%+v", e)
	}
	b.Publish(TToast, "after") // and it keeps working afterwards
	if e := recv(t, slow); e.Data != "after" {
		t.Fatalf("%+v", e)
	}
}

func TestUnsubscribeFrees(t *testing.T) {
	b := New()
	_, cancel := b.Subscribe(4)
	cancel()
	cancel() // idempotent
	if b.Subscribers() != 0 {
		t.Fatal("not freed")
	}
	b.Publish(TToast, 1) // no subscribers: must not panic or block
}
