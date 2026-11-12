package dispatch

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/sessions"
)

func write(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func coordFixture(t *testing.T, e *env) (root, liveDir, deadDir string) {
	root = e.svc.coordRoot()
	liveDir = filepath.Join(root, "runs", "acme-widgets", "20261111-213742")
	deadDir = filepath.Join(root, "runs", "acme-widgets", "20261101-100000")
	write(t, filepath.Join(liveDir, "config.json"), `{"repo":"acme/widgets","source":"https://github.com/users/acme/projects/28/views/12","destination":"https://dest","max":2,"launch_path":"/x","started":"2026-11-11 21:37:42"}`)
	write(t, filepath.Join(liveDir, "queue.tsv"), "6321\tok\tFast CI: Ops\n6330\tblocked:#6329\tLight tier\n6333\tblocked:#6326,#6321,#6323\tImage\tworkflow\nbad line\nxx\tok\tnope\n")
	write(t, filepath.Join(liveDir, "prs.json"), `{"6357":{"state":"OPEN","merged":false,"checks":"PENDING"}}`)
	write(t, filepath.Join(liveDir, "poll_stats.json"), `{"calls":251,"last":1794428559,"last_ok":1794428559,"result":"ok","every":60}`)
	var ev []string
	for i := 1; i <= 25; i++ {
		ev = append(ev, fmt.Sprintf("2026-11-12 01:%02d:00\tPICKED\t-\tpicked #%d", i, i))
	}
	write(t, filepath.Join(liveDir, "events.log"), strings.Join(ev, "\n")+"\n")
	write(t, filepath.Join(liveDir, "loop.pid"), fmt.Sprintf("%d\n", os.Getpid()))
	write(t, filepath.Join(root, "claims", "acme-widgets", "6321", "run"), liveDir)
	write(t, filepath.Join(root, "claims", "acme-widgets", "6330", "run"), liveDir)
	write(t, filepath.Join(root, "claims", "acme-widgets", "6999", "run"), deadDir)
	write(t, filepath.Join(deadDir, "config.json"), `{"repo":"acme/widgets","source":"5","destination":"d","started":"2026-11-01 10:00:00"}`)
	write(t, filepath.Join(deadDir, "loop.pid"), "2147483646\n")
	return
}

func TestCoordinatorReader(t *testing.T) {
	e := newEnv(t)
	coordFixture(t, e)
	started, _ := time.ParseInLocation("2006-01-02 15:04:05", "2026-11-11 21:37:42", time.Local)
	e.sess.recs["S9"] = &sessions.Record{ID: "S9", Step: "project-coordinator", StartedAt: started.Add(-90 * time.Second).UTC().Format(time.RFC3339)}
	e.sess.recs["S8"] = &sessions.Record{ID: "S8", Step: "project-coordinator", StartedAt: started.Add(-3 * time.Hour).UTC().Format(time.RFC3339)}
	e.sess.recs["S7"] = &sessions.Record{ID: "S7", Step: "implement-issue", StartedAt: started.Add(-time.Second).UTC().Format(time.RFC3339)}
	cs := e.svc.Coordinators()
	if len(cs) != 2 || cs[0].Run != "20261111-213742" || cs[1].Run != "20261101-100000" {
		t.Fatalf("newest first: %+v", cs)
	}
	c := cs[0]
	if c.Repo != "acme/widgets" || c.Source != "https://github.com/users/acme/projects/28/views/12" || c.Destination != "https://dest" || !c.Live {
		t.Fatalf("%+v", c)
	}
	if len(c.Queue) != 3 || c.Queue[0] != (CoordQueue{6321, "ok", "Fast CI: Ops"}) || c.Queue[1].State != "blocked:#6329" || c.Queue[2].State != "blocked:#6326,#6321,#6323" || c.Queue[2].Title != "Image\tworkflow" {
		t.Fatalf("%+v", c.Queue)
	}
	if fmt.Sprint(c.Claims) != "[6321 6330]" {
		t.Fatal(c.Claims)
	}
	if c.PRs["6357"] == nil || c.Poll == nil || c.Poll.Calls != 251 || c.Poll.Every != 60 || c.Poll.Result != "ok" || c.Poll.Last != 1794428559 {
		t.Fatalf("%+v %+v", c.PRs, c.Poll)
	}
	if len(c.Events) != 20 || !strings.HasSuffix(c.Events[19], "picked #25") || !strings.HasSuffix(c.Events[0], "picked #6") {
		t.Fatal(c.Events)
	}
	if c.Session == nil || *c.Session != "S9" {
		t.Fatal("session match", c.Session)
	}
	d := cs[1]
	if d.Live || fmt.Sprint(d.Claims) != "[6999]" || d.Session != nil || d.Queue == nil || d.Events == nil || d.PRs == nil {
		t.Fatalf("%+v", d)
	}
	// no root: empty, not an error
	e2 := newEnv(t)
	if cs := e2.svc.Coordinators(); cs == nil || len(cs) != 0 {
		t.Fatal(cs)
	}
}

func TestStopCoordinator(t *testing.T) {
	e := newEnv(t)
	_, liveDir, _ := coordFixture(t, e)
	skill := filepath.Join(t.TempDir(), "project-coordinator")
	log := filepath.Join(t.TempDir(), "args.txt")
	write(t, filepath.Join(skill, "scripts", "coordinator.sh"), "#!/bin/sh\necho \"$@\" > "+log+"\n")
	if err := os.Chmod(filepath.Join(skill, "scripts", "coordinator.sh"), 0o755); err != nil {
		t.Fatal(err)
	}
	e.svc.d.SkillDir = func(s string) (string, bool) { return skill, s == "project-coordinator" }
	if err := e.svc.StopCoordinator(e.ctx(), "20261111-213742"); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(log)
	if strings.TrimSpace(string(b)) != "stop "+liveDir {
		t.Fatalf("argv: %q", b)
	}
	if got := StopArgv("/s", "/r"); strings.Join(got, " ") != "/s/scripts/coordinator.sh stop /r" {
		t.Fatal(got)
	}
	for _, bad := range []string{"", "..", "a/b", "nope"} {
		if err := e.svc.StopCoordinator(e.ctx(), bad); errs.KindOf(err) != errs.KNotFound {
			t.Errorf("%q: %v", bad, err)
		}
	}
	// the script fails: 502
	write(t, filepath.Join(skill, "scripts", "coordinator.sh"), "#!/bin/sh\necho oops >&2\nexit 3\n")
	if err := e.svc.StopCoordinator(e.ctx(), "20261111-213742"); errs.KindOf(err) != errs.KUpstream || !strings.Contains(err.Error(), "oops") {
		t.Fatal(err)
	}
	// blubird missing: 502
	e.svc.d.SkillDir = func(string) (string, bool) { return "", false }
	if err := e.svc.StopCoordinator(e.ctx(), "20261111-213742"); errs.KindOf(err) != errs.KUpstream {
		t.Fatal(err)
	}
}

func TestStartCoordinatorSession(t *testing.T) {
	e := newEnv(t)
	rec, err := e.svc.StartCoordinator(e.ctx(), "acme/docs", "https://github.com/orgs/acme/projects/1 --max 3")
	if err != nil {
		t.Fatal(err)
	}
	sp := e.sess.Launched[0]
	if rec.ID != "S1" || sp.Prompt.Step != "project-coordinator" || sp.Prompt.Text != "/blubird:project-coordinator https://github.com/orgs/acme/projects/1 --max 3" ||
		sp.Cwd != "acme/docs" || sp.Kind != "coordinator" {
		t.Fatalf("%+v", sp)
	}
	e.svc.d.Prompts = fakePrompts{Unavailable: errs.Conflict("blubird is not installed", nil)}
	if _, err := e.svc.StartCoordinator(e.ctx(), "acme/docs", "5"); errs.KindOf(err) != errs.KConflict {
		t.Fatal(err)
	}
}
