package settings

import (
	"errors"
	"os/exec"
	"path/filepath"
	"strings"
)

// Split is Python's shlex.split (POSIX mode, no comments).
func Split(s string) ([]string, error) {
	var toks []string
	var cur strings.Builder
	in := false
	rs := []rune(s)
	for i := 0; i < len(rs); i++ {
		c := rs[i]
		switch {
		case c == ' ' || c == '\t' || c == '\n' || c == '\r':
			if in {
				toks = append(toks, cur.String())
				cur.Reset()
				in = false
			}
		case c == '\\':
			if i+1 >= len(rs) {
				return nil, errors.New("No escaped character")
			}
			i++
			cur.WriteRune(rs[i])
			in = true
		case c == '\'':
			j := i + 1
			for j < len(rs) && rs[j] != '\'' {
				cur.WriteRune(rs[j])
				j++
			}
			if j >= len(rs) {
				return nil, errors.New("No closing quotation")
			}
			i = j
			in = true
		case c == '"':
			j := i + 1
			for j < len(rs) && rs[j] != '"' {
				if rs[j] == '\\' && j+1 < len(rs) && (rs[j+1] == '"' || rs[j+1] == '\\') {
					j++
				}
				cur.WriteRune(rs[j])
				j++
			}
			if j >= len(rs) {
				return nil, errors.New("No closing quotation")
			}
			i = j
			in = true
		default:
			cur.WriteRune(c)
			in = true
		}
	}
	if in {
		toks = append(toks, cur.String())
	}
	return toks, nil
}

// ResolveCmd is S§3.1 argv(): shlex split, a leading `cc` becomes `cc-profile`, the first
// token is resolved on PATH to an absolute path. The command is never run through a shell.
func ResolveCmd(cmd string) ([]string, error) {
	if strings.ContainsRune(cmd, 0) {
		return nil, errors.New("command must be a string")
	}
	toks, err := Split(cmd)
	if err != nil {
		return nil, errors.New("cannot parse command: " + err.Error())
	}
	if len(toks) == 0 {
		return nil, errors.New("command must not be empty")
	}
	if toks[0] == "cc" {
		toks[0] = "cc-profile"
	}
	exe, err := exec.LookPath(toks[0])
	if err != nil {
		return nil, errors.New("'" + toks[0] + "' not found on PATH")
	}
	if abs, err := filepath.Abs(exe); err == nil {
		exe = abs
	}
	toks[0] = exe
	return toks, nil
}
