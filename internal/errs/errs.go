// Package errs maps error kinds to HTTP statuses.
package errs

import (
	"errors"
	"fmt"
	"net/http"
)

type Kind int

const (
	KInvalid Kind = iota + 1
	KNotFound
	KConflict
	KUpstream
	KForbidden
)

// Error is a typed error. Extra is merged into the JSON body (e.g. id, href).
// Status, when non-zero, overrides the status derived from Kind (413, 415).
type Error struct {
	Kind   Kind
	Msg    string
	Extra  map[string]any
	Status int
}

func (e *Error) Error() string { return e.Msg }

func Invalid(format string, a ...any) error  { return &Error{Kind: KInvalid, Msg: sprintf(format, a)} }
func NotFound(format string, a ...any) error { return &Error{Kind: KNotFound, Msg: sprintf(format, a)} }
func Upstream(format string, a ...any) error { return &Error{Kind: KUpstream, Msg: sprintf(format, a)} }
func Forbidden(format string, a ...any) error {
	return &Error{Kind: KForbidden, Msg: sprintf(format, a)}
}

func Conflict(msg string, extra map[string]any) error {
	return &Error{Kind: KConflict, Msg: msg, Extra: extra}
}

// WithStatus is a KInvalid error that reports a specific 4xx status.
func WithStatus(status int, msg string) error {
	return &Error{Kind: KInvalid, Msg: msg, Status: status}
}

func sprintf(format string, a []any) string {
	if len(a) == 0 {
		return format
	}
	return fmt.Sprintf(format, a...)
}

// KindOf returns the kind of the first *Error in err's chain, 0 if none.
func KindOf(err error) Kind {
	var e *Error
	if errors.As(err, &e) {
		return e.Kind
	}
	return 0
}

// As returns the first *Error in err's chain.
func As(err error) (*Error, bool) {
	var e *Error
	ok := errors.As(err, &e)
	return e, ok
}

// Status is the HTTP status for err. Unknown errors are 500.
func Status(err error) int {
	e, ok := As(err)
	if !ok {
		return http.StatusInternalServerError
	}
	if e.Status != 0 {
		return e.Status
	}
	switch e.Kind {
	case KInvalid:
		return http.StatusBadRequest
	case KNotFound:
		return http.StatusNotFound
	case KConflict:
		return http.StatusConflict
	case KUpstream:
		return http.StatusBadGateway
	case KForbidden:
		return http.StatusForbidden
	}
	return http.StatusInternalServerError
}

// Body is the JSON body for err: {"error": msg, ...Extra}. Unknown errors give "internal error".
func Body(err error) map[string]any {
	e, ok := As(err)
	if !ok || e.Kind == 0 {
		return map[string]any{"error": "internal error"}
	}
	m := map[string]any{}
	for k, v := range e.Extra {
		m[k] = v
	}
	m["error"] = e.Msg
	return m
}
