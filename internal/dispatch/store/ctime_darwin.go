//go:build darwin

package store

import "syscall"

func ctimeNano(st *syscall.Stat_t) int64 { return st.Ctimespec.Nano() }
