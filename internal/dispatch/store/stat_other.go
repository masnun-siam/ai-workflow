//go:build !linux && !darwin

package store

import "io/fs"

func statExtra(fi fs.FileInfo) (int64, uint64) { return 0, 0 }
