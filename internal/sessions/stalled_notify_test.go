package sessions

import "testing"

// A run the idle guard marked stalled sends `stalled` once instead of `done`; a lane's run sends
// nothing (its lane notifies); a resumed run that stalls again notifies again.
func TestStalledNotification(t *testing.T) {
	e := newEnv(t)
	set := func(id string, fn func(*Record)) {
		t.Helper()
		_, err := e.m.Update(id, func(r *Record) error { fn(r); return nil })
		mustNoErr(t, err)
	}
	rec, err := e.m.create(Record{Status: StRunning, Command: "/blubird:implement-issue 5"})
	mustNoErr(t, err)
	set(rec.ID, func(r *Record) { r.Stalled = "stopped twice without asking or finishing" })
	set(rec.ID, func(r *Record) { r.Status = StDone })
	set(rec.ID, func(r *Record) { r.Command += " " }) // the same stall re-read
	if s, d := e.notes.count("stalled"), e.notes.count("done"); s != 1 || d != 0 {
		t.Fatalf("stalled %d done %d", s, d)
	}
	if n := e.notes.items[0].Note; n.Text != "stopped twice without asking or finishing" || n.ID != rec.ID {
		t.Fatalf("%+v", n)
	}

	set(rec.ID, func(r *Record) { r.Status, r.Stalled = StRunning, "" }) // resumed
	set(rec.ID, func(r *Record) { r.Stalled, r.Status = "stopped again", StDone })
	if s := e.notes.count("stalled"); s != 2 {
		t.Fatalf("re-stall: stalled %d", s)
	}

	set(rec.ID, func(r *Record) { r.Status, r.Stalled = StRunning, "" }) // resumed, finishes
	set(rec.ID, func(r *Record) { r.Status = StDone })
	if s, d := e.notes.count("stalled"), e.notes.count("done"); s != 2 || d != 1 {
		t.Fatalf("clean finish: stalled %d done %d", s, d)
	}

	lane, err := e.m.create(Record{Status: StRunning, Kind: "lane"})
	mustNoErr(t, err)
	set(lane.ID, func(r *Record) { r.Stalled, r.Status = "stopped twice", StDone })
	if s, d := e.notes.count("stalled"), e.notes.count("done"); s != 2 || d != 1 {
		t.Fatalf("lane: stalled %d done %d", s, d)
	}
}
