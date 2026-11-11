// Package execx runs subprocesses. Run never returns an error: failures are in Result.
package execx

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

type Opts struct {
	Dir        string
	Env        []string // appended to os.Environ
	Stdin      io.Reader
	Timeout    time.Duration
	ExtraFiles []*os.File
	Detach     bool // Setsid
}

type Result struct {
	Code           int
	Stdout, Stderr []byte
	Err            error
}

// Run executes argv. A missing binary gives Code 127 (Stderr = the error); a timeout gives
// Code 124 and Stderr "timed out after Ns".
func Run(ctx context.Context, argv []string, o Opts) Result {
	if len(argv) == 0 {
		return Result{Code: 127, Stderr: []byte("empty command"), Err: errors.New("empty command")}
	}
	if o.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, o.Timeout)
		defer cancel()
	}
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Dir = o.Dir
	if len(o.Env) > 0 {
		cmd.Env = append(os.Environ(), o.Env...)
	}
	cmd.Stdin = o.Stdin
	cmd.ExtraFiles = o.ExtraFiles
	attr := &syscall.SysProcAttr{}
	if o.Detach {
		attr.Setsid = true
	} else {
		attr.Setpgid = true
	}
	cmd.SysProcAttr = attr
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		if o.Detach {
			return cmd.Process.Kill()
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL) // whole group, so grandchildren do not hold the pipes
	}
	cmd.WaitDelay = 2 * time.Second
	var so, se bytes.Buffer
	cmd.Stdout, cmd.Stderr = &so, &se
	err := cmd.Run()
	r := Result{Stdout: so.Bytes(), Stderr: se.Bytes()}
	if err == nil {
		return r
	}
	r.Err = err
	var ee *exec.ExitError
	switch {
	case o.Timeout > 0 && errors.Is(ctx.Err(), context.DeadlineExceeded):
		r.Code = 124
		r.Stderr = []byte(fmt.Sprintf("timed out after %ds", int(o.Timeout.Seconds())))
	case errors.As(err, &ee):
		r.Code = ee.ExitCode()
		if r.Code < 0 { // killed by signal
			r.Code = 128
			if ws, ok := ee.Sys().(syscall.WaitStatus); ok && ws.Signaled() {
				r.Code = 128 + int(ws.Signal())
			}
		}
	case errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) || errors.Is(err, os.ErrPermission):
		r.Code = 127
		r.Stderr = []byte(err.Error())
	default:
		r.Code = 1
		if len(r.Stderr) == 0 {
			r.Stderr = []byte(err.Error())
		}
	}
	return r
}

// LastLine is the last non-blank line of stderr, else stdout, at most 200 chars.
func (r Result) LastLine() string {
	for _, b := range [][]byte{r.Stderr, r.Stdout} {
		lines := strings.Split(strings.TrimRight(string(b), "\r\n \t"), "\n")
		for i := len(lines) - 1; i >= 0; i-- {
			if l := strings.TrimSpace(lines[i]); l != "" {
				if len(l) > 200 {
					l = l[:200]
				}
				return l
			}
		}
	}
	return ""
}
