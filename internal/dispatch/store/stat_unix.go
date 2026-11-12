//go:build linux || darwin

package store

import (
	"io/fs"
	"syscall"
)

// statExtra returns the change time and inode of a stat result (0, 0 when unavailable).
func statExtra(fi fs.FileInfo) (int64, uint64) {
	if st, ok := fi.Sys().(*syscall.Stat_t); ok {
		return ctimeNano(st), uint64(st.Ino)
	}
	return 0, 0
}
