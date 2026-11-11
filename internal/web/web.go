// Package web embeds the built UI (internal/web/dist, committed).
package web

import (
	"embed"
	"io/fs"
)

//go:embed all:dist
var dist embed.FS

// FS is the dist directory: index.html at its root.
var FS fs.FS = mustSub()

func mustSub() fs.FS {
	s, err := fs.Sub(dist, "dist")
	if err != nil {
		panic(err)
	}
	return s
}
