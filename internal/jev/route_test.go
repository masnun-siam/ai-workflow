package jev

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func ptr[T any](v T) *T { return &v }

func sameRoute(a, b RouteAnswer) bool {
	eqS := (a.Route == nil) == (b.Route == nil) && (a.Route == nil || *a.Route == *b.Route)
	eqP := (a.P == nil) == (b.P == nil) && (a.P == nil || *a.P == *b.P)
	return eqS && eqP && a.Status == b.Status
}

func show(a RouteAnswer) string {
	route, p := "nil", "nil"
	if a.Route != nil {
		route = *a.Route
	}
	if a.P != nil {
		p = fmt.Sprint(*a.P)
	}
	return fmt.Sprintf("{route:%s p:%s status:%s}", route, p, a.Status)
}

func TestRouteAnswers(t *testing.T) {
	tests := []struct {
		name, out string
		exit      int
		want      RouteAnswer
	}{
		{"bug", `{"choice":"bug","probabilities":{"bug":0.82}}`, 0, RouteAnswer{ptr("bug"), ptr(0.82), "ok"}},
		{"feature", `{"choice":"feature","probabilities":{"feature":0.7}}`, 0, RouteAnswer{ptr("feature"), ptr(0.7), "ok"}},
		{"small", `{"choice":"small","probabilities":{"small":0.55}}`, 0, RouteAnswer{ptr("small"), ptr(0.55), "ok"}},
		{"exactly 0.4", `{"choice":"bug","probabilities":{"bug":0.4}}`, 0, RouteAnswer{ptr("bug"), ptr(0.4), "ok"}},
		{"under 0.4", `{"choice":"bug","probabilities":{"bug":0.39}}`, 0, RouteAnswer{nil, ptr(0.39), "unsure"}},
		{"unclear high", `{"choice":"unclear","probabilities":{"unclear":0.95}}`, 0, RouteAnswer{nil, ptr(0.95), "unsure"}},
		{"no probability", `{"choice":"bug"}`, 0, RouteAnswer{nil, ptr(0.0), "unsure"}},
		{"unknown choice", `{"choice":"epic","probabilities":{"epic":0.9}}`, 0, RouteAnswer{Status: "unreadable"}},
		{"bad json", `nope`, 0, RouteAnswer{Status: "unreadable"}},
		{"nonzero exit", ``, 2, RouteAnswer{Status: "failed"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: tc.out, Exit: tc.exit}})
			if got := c.Route(context.Background(), "the app crashes on start"); !sameRoute(got, tc.want) {
				t.Fatalf("got %s want %s", show(got), show(tc.want))
			}
		})
	}
}

func TestRouteOffMissingTimeout(t *testing.T) {
	c, bin, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"bug"}`, SleepMs: 1500}})
	c.enabled = func() bool { return false }
	if got := c.Route(context.Background(), "text"); !sameRoute(got, RouteAnswer{Status: "off"}) {
		t.Fatalf("off: %s", show(got))
	}
	if n := len(fakebin.Calls(t, bin)); n != 0 {
		t.Fatalf("off must never exec jev: %d calls", n)
	}

	c.enabled = func() bool { return true }
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if got := c.Route(ctx, "text"); !sameRoute(got, RouteAnswer{Status: "no_answer"}) {
		t.Fatalf("timeout: %s", show(got))
	}

	t.Setenv("PATH", t.TempDir())
	if got := c.Route(context.Background(), "text"); !sameRoute(got, RouteAnswer{Status: "missing"}) {
		t.Fatalf("missing: %s", show(got))
	}
}

func TestRouteIsNotCachedOrCounted(t *testing.T) {
	c, bin, h := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"bug","probabilities":{"bug":0.9}}`}})
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	c.Start(ctx) // server mode: cached points would be cached now
	c.Route(ctx, "same text")
	c.Route(ctx, "same text")
	if n := len(fakebin.Calls(t, bin)); n != 2 {
		t.Fatalf("a repeated call must run jev again: %d calls", n)
	}
	if c.Spent() != 0 {
		t.Fatalf("route must not count: spent %d", c.Spent())
	}
	c.Flush()
	if _, err := os.Stat(filepath.Join(h.Root, "jev_cache.json")); !os.IsNotExist(err) {
		t.Fatalf("route must not write the cache: %v", err)
	}
}

func TestRouteSendsRedactedCutText(t *testing.T) {
	c, bin, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"bug","probabilities":{"bug":0.9}}`}})
	text := "crash token ghp_" + strings.Repeat("Q", 24) + " " + strings.Repeat("y ", 3000)
	c.Route(context.Background(), text)
	calls := fakebin.Calls(t, bin)
	if len(calls) != 1 {
		t.Fatalf("calls %d", len(calls))
	}
	in := calls[0].Stdin
	if strings.Contains(in, "ghp_") || !strings.Contains(in, "[redacted]") || len([]rune(in)) > MaxChars {
		t.Fatalf("stdin not redacted/cut (len %d)", len([]rune(in)))
	}
	args := strings.Join(calls[0].Args, " ")
	for _, o := range []string{"--option bug=", "--option feature=", "--option small=", "--option unclear="} {
		if !strings.Contains(args, o) {
			t.Fatalf("argv missing %q: %s", o, args)
		}
	}
}
