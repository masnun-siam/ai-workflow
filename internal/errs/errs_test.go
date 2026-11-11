package errs

import (
	"fmt"
	"testing"
)

func TestStatusAndBody(t *testing.T) {
	cases := []struct {
		name   string
		err    error
		status int
		msg    string
	}{
		{"invalid", Invalid("bad %d", 1), 400, "bad 1"},
		{"notfound", NotFound("nope"), 404, "nope"},
		{"conflict", Conflict("busy", map[string]any{"id": "x"}), 409, "busy"},
		{"upstream", Upstream("gh down"), 502, "gh down"},
		{"forbidden", Forbidden("no"), 403, "no"},
		{"413", WithStatus(413, "body too large"), 413, "body too large"},
		{"wrapped", fmt.Errorf("ctx: %w", NotFound("gone")), 404, "gone"},
		{"unknown", fmt.Errorf("boom"), 500, "internal error"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := Status(c.err); got != c.status {
				t.Errorf("status = %d want %d", got, c.status)
			}
			if got := Body(c.err)["error"]; got != c.msg {
				t.Errorf("msg = %v want %q", got, c.msg)
			}
		})
	}
	if Body(Conflict("busy", map[string]any{"id": "x"}))["id"] != "x" {
		t.Error("extra not merged")
	}
	if KindOf(fmt.Errorf("x")) != 0 || KindOf(Invalid("x")) != KInvalid {
		t.Error("KindOf")
	}
}
