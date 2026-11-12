package dispatch

import (
	"strings"

	"github.com/masnun-siam/setu/internal/dispatch/store"
)

// InboxRow is what the inbox builder (L8) needs of a dispatch lane or a finished dispatch. The
// builder maps Group/Key/Reason to its own item and adds the actions (W§2.7).
type InboxRow struct {
	Key           string
	Group         string // answer | fix | decide | wait
	Type          string // dispatch_lane | dispatch_done
	Reason        string
	Repo          string
	Dispatch      string
	Lane          string
	Issue         int
	Title         string
	Stage         string
	PR            int
	ResetsAt      float64
	Epic          *string
	FeatureBranch string
	FinalPRs      map[string]string
}

// InboxRows lists the rows for live dispatches (and done ones not yet seen): per lane needs_you,
// held, a PR waiting for the merge, an unexpired usage limit; a done dispatch gets a decide row.
func InboxRows(ds []store.Dispatch, now float64) []InboxRow {
	var out []InboxRow
	for i := range ds {
		d := &ds[i]
		if !store.Live(d.State) && !(d.State == store.Done && !d.SeenDone) {
			continue
		}
		for _, k := range d.SortedKeys() {
			x := d.Lanes[k]
			row := InboxRow{Repo: x.Repo, Dispatch: d.ID, Lane: k, Issue: x.N, Title: x.Title, Stage: x.Stage, PR: x.PR,
				Type: "dispatch_lane"}
			pre := "dispatch:" + d.ID + ":" + k + ":"
			switch {
			case x.NeedsYou != "":
				row.Key, row.Group, row.Reason = pre+"needs", "answer", x.NeedsYou
			case x.Held != "":
				row.Key, row.Group, row.Reason = pre+"held", "fix", x.Held
			case x.Stage == store.StAwaitingMerge:
				row.Key, row.Group, row.Reason = pre+"merge", "decide", "PR #"+itoa(x.PR)+" is ready to merge"
			case x.LimitedUntil > now:
				row.Key, row.Group, row.Reason, row.ResetsAt = pre+"limited", "wait", "Claude usage limit", x.LimitedUntil
			default:
				continue
			}
			out = append(out, row)
		}
		if d.State == store.Done {
			out = append(out, InboxRow{Key: "dispatch:" + d.ID + ":done", Group: "decide", Type: "dispatch_done",
				Repo: d.Repo(), Dispatch: d.ID, Title: d.Title, Epic: d.Epic,
				FeatureBranch: store.Str(d.Settings.FeatureBranch), FinalPRs: d.FinalPRs})
		}
	}
	return out
}

// Duplicated are the generic inbox types a lane's own row replaces.
var Duplicated = map[string]bool{"pr_ready": true, "pr_conflict": true, "grind_paused": true, "session_failed": true}

// OwnedSet is the (repo, issue/pr) pairs a live dispatch's active lane owns.
type OwnedSet map[string]bool

func ownedKey(repo, kind string, n int) string {
	return strings.ToLower(repo) + "|" + kind + "|" + itoa(n)
}

// OwnedBy lists what running or paused dispatches' active lanes own.
func OwnedBy(ds []store.Dispatch) OwnedSet {
	o := OwnedSet{}
	for i := range ds {
		if !store.Live(ds[i].State) {
			continue
		}
		for _, x := range ds[i].Lanes {
			if store.Active(x.Stage) {
				o[ownedKey(x.Repo, "issue", x.N)] = true
				if x.PR != 0 {
					o[ownedKey(x.Repo, "pr", x.PR)] = true
				}
			}
		}
	}
	return o
}

// Drops reports whether a generic inbox row (type, repo, issue, pr) is replaced by a lane's row.
func (o OwnedSet) Drops(typ, repo string, issue, pr int) bool {
	return Duplicated[typ] && (o[ownedKey(repo, "issue", issue)] || (pr != 0 && o[ownedKey(repo, "pr", pr)]))
}
