//go:build linux

package store

import "syscall"

func ctimeNano(st *syscall.Stat_t) int64 { return st.Ctim.Nano() }
