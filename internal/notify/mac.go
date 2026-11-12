package notify

import (
	"context"
	"os/exec"
	"strconv"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
)

func (s *Service) notifierPath() string {
	s.tnOnce.Do(func() { s.tn, _ = exec.LookPath("terminal-notifier") })
	return s.tn
}

func trunc(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// macArgv is the banner command; the body and title are always argv, never script text.
func macArgv(tn, title, body, link string) []string {
	title, body = trunc(title, 80), trunc(body, 200)
	if body == "" {
		body = title
	}
	if tn != "" {
		argv := []string{tn, "-title", title, "-message", body}
		if link != "" {
			argv = append(argv, "-open", link)
		}
		return argv
	}
	return []string{"osascript",
		"-e", "on run argv",
		"-e", "display notification (item 1 of argv) with title (item 2 of argv)",
		"-e", "end run", body, title}
}

// sendMac shows a macOS banner. "" on success, else a short error.
func (s *Service) sendMac(ctx context.Context, title, body, link string) string {
	if s.goos != "darwin" {
		return "Only on macOS"
	}
	if s.getenv("SETU_NO_MAC_BANNER") != "" || s.getenv("AIW_NO_MAC_BANNER") != "" {
		return "Turned off by SETU_NO_MAC_BANNER"
	}
	r := execx.Run(ctx, macArgv(s.notifierPath(), title, body, link), execx.Opts{Timeout: 10 * time.Second})
	if r.Code != 0 {
		s.warnf("macOS notification failed: exit %d", r.Code)
		return "exit " + strconv.Itoa(r.Code)
	}
	return ""
}
