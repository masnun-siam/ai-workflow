package dispatch

import (
	"bytes"
	"io"
	"strconv"
	"strings"
	"time"
)

func bytesReader(b []byte) io.Reader { return bytes.NewReader(b) }

func epoch(t time.Time) float64 { return float64(t.UnixNano()) / 1e9 }

func splitSlug(slug string) (owner, name string) {
	o, n, _ := strings.Cut(slug, "/")
	return o, n
}

func trunc(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func itoa(n int) string { return strconv.Itoa(n) }
