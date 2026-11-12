// Package inboxtest checks server-built actions against the route table of docs/setu/API.md.
package inboxtest

import (
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
)

type pattern struct {
	method string
	segs   []string // "{x}" = any one segment; "a|b" = alternatives
}

var (
	once     sync.Once
	patterns []pattern
)

var rowRe = regexp.MustCompile("^\\|\\s*([A-Z/ ]+?)\\s*\\|\\s*(.+?)\\s*\\|")
var pathRe = regexp.MustCompile("`(/api/[^`]*)`")

func load() {
	_, file, _, _ := runtime.Caller(0)
	b, err := os.ReadFile(filepath.Join(filepath.Dir(file), "..", "..", "..", "docs", "setu", "API.md"))
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(b), "\n") {
		m := rowRe.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		methods := strings.Split(strings.ReplaceAll(m[1], " ", ""), "/")
		for _, pm := range pathRe.FindAllStringSubmatch(line, -1) {
			p := pm[1]
			if i := strings.IndexByte(p, '?'); i >= 0 {
				p = p[:i]
			}
			if strings.Contains(p, "...") {
				continue
			}
			var segs []string
			for _, s := range strings.Split(strings.Trim(p, "/"), "/") {
				s = strings.ReplaceAll(s, `\|`, "|")
				if strings.HasPrefix(s, "{") && strings.HasSuffix(s, "}") && strings.Contains(s, "|") {
					s = strings.Trim(s, "{}")
				}
				segs = append(segs, s)
			}
			for _, me := range methods {
				patterns = append(patterns, pattern{me, segs})
			}
		}
	}
}

// Known reports whether API.md lists a route that serves method and path.
func Known(method, path string) bool {
	once.Do(load)
	segs := strings.Split(strings.Trim(path, "/"), "/")
	for _, p := range patterns {
		if p.method != method || len(p.segs) != len(segs) {
			continue
		}
		ok := true
		for i, ps := range p.segs {
			switch {
			case strings.HasPrefix(ps, "{") && strings.HasSuffix(ps, "}"):
			case strings.Contains(ps, "|"):
				found := false
				for _, alt := range strings.Split(ps, "|") {
					found = found || alt == segs[i]
				}
				ok = ok && found
			default:
				ok = ok && ps == segs[i]
			}
		}
		if ok {
			return true
		}
	}
	return false
}

// Count is the number of patterns read (0 means API.md was not found).
func Count() int { once.Do(load); return len(patterns) }
