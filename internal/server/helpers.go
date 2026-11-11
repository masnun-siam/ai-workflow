package server

import (
	"bytes"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"regexp"
	"strconv"

	"github.com/masnun-siam/setu/internal/errs"
)

const maxBody = 65536

// HandlerFunc returns the status (0 = 200), the JSON body and an error. An error is mapped by
// errs to a status and {"error": msg, ...Extra}.
type HandlerFunc func(r *http.Request) (status int, body any, err error)

func Handle(f HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		status, body, err := f(r)
		if err != nil {
			writeJSON(w, errs.Status(err), errs.Body(err))
			return
		}
		if status == 0 {
			status = http.StatusOK
		}
		if status == http.StatusNoContent {
			w.WriteHeader(status)
			return
		}
		writeJSON(w, status, body)
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	b, err := json.Marshal(body)
	if err != nil {
		status, b = http.StatusInternalServerError, []byte(`{"error":"internal error"}`)
	}
	h := w.Header()
	h.Set("Content-Type", "application/json; charset=utf-8")
	h.Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_, _ = w.Write(append(b, '\n'))
}

// Decode reads a JSON object body into v. Order of checks: 415 content type, 400 Content-Length,
// 413 size, 400 not an object / invalid JSON.
func Decode(r *http.Request, v any) error {
	mt, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || mt != "application/json" {
		return errs.WithStatus(http.StatusUnsupportedMediaType, "Content-Type must be application/json")
	}
	if r.ContentLength < 0 {
		return errs.Invalid("bad Content-Length")
	}
	if r.ContentLength > maxBody {
		return errs.WithStatus(http.StatusRequestEntityTooLarge, "body too large")
	}
	b, err := io.ReadAll(io.LimitReader(r.Body, maxBody+1))
	if err != nil {
		return errs.Invalid("bad body")
	}
	if len(b) > maxBody {
		return errs.WithStatus(http.StatusRequestEntityTooLarge, "body too large")
	}
	if t := bytes.TrimSpace(b); len(t) == 0 || t[0] != '{' {
		return errs.Invalid("body must be a JSON object")
	}
	if err := json.Unmarshal(b, v); err != nil {
		var te *json.UnmarshalTypeError
		if asTypeErr(err, &te) {
			return errs.Invalid("field %q has the wrong type", te.Field)
		}
		return errs.Invalid("body must be a JSON object")
	}
	return nil
}

func asTypeErr(err error, te **json.UnmarshalTypeError) bool {
	e, ok := err.(*json.UnmarshalTypeError)
	if ok {
		*te = e
	}
	return ok
}

// PathInt parses a positive integer path value.
func PathInt(r *http.Request, name string) (int, error) {
	n, err := strconv.Atoi(r.PathValue(name))
	if err != nil || n <= 0 {
		return 0, errs.Invalid("%s must be a positive integer", name)
	}
	return n, nil
}

var pathSeg = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

// Slug returns "owner/name" from the {owner} and {name} path values.
func Slug(r *http.Request) (string, error) {
	o, n := r.PathValue("owner"), r.PathValue("name")
	if !pathSeg.MatchString(o) || !pathSeg.MatchString(n) {
		return "", errs.Invalid("bad repo name")
	}
	return o + "/" + n, nil
}
