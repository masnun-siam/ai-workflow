package settings

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// Save merges a partial settings body (S§4.1). Omitted keys keep their stored value.
func (s *Store) Save(patch json.RawMessage) (SettingsView, error) {
	var body map[string]json.RawMessage
	if err := json.Unmarshal(patch, &body); err != nil || body == nil {
		return SettingsView{}, errs.Invalid("body must be a JSON object")
	}
	unlock, err := home.Lock(s.path())
	if err != nil {
		return SettingsView{}, err
	}
	defer unlock()
	if _, err := home.BackupIfCorrupt(s.path()); err != nil {
		return SettingsView{}, err
	}
	raw, _, _ := s.readRaw()
	s.migrate(raw)
	raw = jsonNorm(raw)
	cur := normalize(raw)
	out, err := s.validate(cur, raw, body)
	if err != nil {
		return SettingsView{}, err
	}
	if err := home.WriteJSON(s.path(), out); err != nil {
		return SettingsView{}, err
	}
	s.mu.Lock()
	s.cur, s.key = normalize(jsonNorm(out)), s.key0()
	l := s.cur
	s.mu.Unlock()
	s.publish()
	return s.viewOf(l), nil
}

func bad(format string, a ...any) error { return errs.Invalid(format, a...) }

func decodeKey[T any](body map[string]json.RawMessage, key string, v *T) (present bool, err error) {
	r, ok := body[key]
	if !ok {
		return false, nil
	}
	if err := json.Unmarshal(r, v); err != nil {
		return true, bad("%s has the wrong type", key)
	}
	return true, nil
}

func trimStr(m map[string]any, k string) string {
	s, _ := m[k].(string)
	return strings.TrimSpace(s)
}

func (s *Store) validate(cur *loaded, raw map[string]any, body map[string]json.RawMessage) (map[string]any, error) {
	out := map[string]any{}
	for k, v := range raw {
		out[k] = v
	}
	delete(out, "auto_grind")

	// ---- commands, default ----
	_, full := body["commands"]
	var cmdsIn []any
	var defIn *string
	if full {
		if _, err := decodeKey(body, "commands", &cmdsIn); err != nil || cmdsIn == nil {
			return nil, bad("commands must be a list")
		}
		if _, err := decodeKey(body, "default", &defIn); err != nil {
			return nil, err
		}
	} else {
		for _, a := range cur.Commands {
			m := map[string]any{"label": a.Label, "cmd": a.Cmd}
			if a.Builtin {
				m["builtin"] = true
			}
			cmdsIn = append(cmdsIn, m)
		}
		d := cur.Default
		defIn = &d
		if _, err := decodeKey(body, "default", &defIn); err != nil {
			return nil, err
		}
	}
	if len(cmdsIn) > MaxCommands {
		return nil, bad("at most %d commands", MaxCommands)
	}
	alias, builtins := cur.ClaudeLabel, 0
	for _, e := range cmdsIn {
		if m, ok := e.(map[string]any); ok && m["builtin"] == true {
			builtins++
			l, ok := m["label"].(string)
			if !ok || strings.TrimSpace(l) == "" || len(l) > 40 {
				return nil, bad("label must be a non-empty string of at most 40 characters")
			}
			alias = strings.TrimSpace(l)
		}
	}
	if builtins > 1 {
		return nil, bad("only one built-in command")
	}
	seen := map[string]bool{alias: true}
	used := map[string]bool{DefaultCmd: true}
	cmds := []map[string]any{}
	for _, e := range cmdsIn {
		m, _ := e.(map[string]any)
		if h, ok := m["harness"]; ok && h != "claude" {
			return nil, bad("harness must be claude")
		}
		if m["builtin"] == true {
			continue
		}
		label, _ := m["label"].(string)
		label = strings.TrimSpace(label)
		if label == "" || len([]rune(label)) > 40 {
			return nil, bad("label must be a non-empty string of at most 40 characters")
		}
		if seen[label] {
			return nil, bad("duplicate label: '%s'", label)
		}
		seen[label] = true
		cmd, ok := m["cmd"].(string)
		if !ok || len(cmd) > 200 {
			return nil, bad("cmd must be a string of at most 200 characters")
		}
		if _, err := ResolveCmd(cmd); err != nil {
			return nil, bad("%s", err.Error())
		}
		cmd = strings.TrimSpace(cmd)
		if full && used[cmd] {
			return nil, bad("each account needs its own command")
		}
		used[cmd] = true
		cmds = append(cmds, map[string]any{"label": label, "cmd": cmd})
	}
	var def any
	if defIn != nil {
		if !seen[*defIn] {
			return nil, bad("default must be one of the labels")
		}
		if *defIn != alias {
			def = *defIn
		}
	}
	out["claude_label"], out["commands"], out["default"] = alias, cmds, def

	// ---- scalar keys ----
	vault := cur.vaultRaw
	var vp *string
	if present, err := decodeKey(body, "vault_dir", &vp); err != nil {
		return nil, err
	} else if present {
		vault = ""
		if vp != nil {
			v := *vp
			if strings.ContainsRune(v, 0) || len(v) > 500 {
				return nil, bad("vault_dir must be a path of at most 500 characters")
			}
			vault = strings.TrimSpace(v)
			if vault != "" && !strings.HasPrefix(expandHome(vault), "/") {
				return nil, bad("vault_dir must be an absolute path (or start with ~)")
			}
		}
	}
	if vault == "" {
		out["vault_dir"] = nil
	} else {
		out["vault_dir"] = vault
	}
	mode := cur.GrindMode
	if _, err := decodeKey(body, "grind_mode", &mode); err != nil {
		return nil, err
	}
	if mode != "deep" && mode != "simple" {
		return nil, bad("grind_mode must be deep or simple")
	}
	jev := cur.UseJev
	if _, err := decodeKey(body, "use_jev", &jev); err != nil {
		return nil, err
	}
	rm, re := cur.RunModel, cur.RunEffort
	if _, err := decodeKey(body, "run_model", &rm); err != nil {
		return nil, err
	}
	if _, err := decodeKey(body, "run_effort", &re); err != nil {
		return nil, err
	}
	if err := CheckRun(deref(rm), deref(re)); err != nil {
		return nil, err
	}
	out["grind_mode"], out["use_jev"], out["run_model"], out["run_effort"] = mode, jev, nilIfEmpty(rm), nilIfEmpty(re)

	// ---- slack channels, reviewers ----
	oldIDs := map[string]bool{}
	for _, c := range cur.SlackChannels {
		oldIDs[c.ID] = true
	}
	chans := cur.SlackChannels
	if _, ok := body["slack_channels"]; ok {
		var in []any
		if _, err := decodeKey(body, "slack_channels", &in); err != nil || in == nil {
			return nil, bad("slack_channels must be a list")
		}
		var err error
		if chans, err = cleanChannels(in); err != nil {
			return nil, err
		}
	}
	ids := map[string]bool{}
	for _, c := range chans {
		ids[c.ID] = true
	}
	revs := cur.Reviewers
	if _, ok := body["reviewers"]; ok {
		var in []any
		if _, err := decodeKey(body, "reviewers", &in); err != nil || in == nil {
			return nil, bad("reviewers must be a list")
		}
		var err error
		if revs, err = cleanReviewers(in); err != nil {
			return nil, err
		}
	}
	rids := map[string]bool{}
	for _, r := range revs {
		rids[r.ID] = true
	}
	active := known(cur.ActiveReviewers, rids)
	if _, ok := body["active_reviewers"]; ok {
		var in any
		_, _ = decodeKey(body, "active_reviewers", &in)
		var err error
		if active, err = cleanIDs(in, rids, "active_reviewers must be a list of ids"); err != nil {
			return nil, err
		}
	}
	out["slack_channels"], out["reviewers"], out["active_reviewers"] = chans, revs, active

	// ---- repos ----
	var sent map[string]any
	if _, err := decodeKey(body, "repos", &sent); err != nil {
		return nil, bad("repos must be an object")
	}
	kept := map[string]RepoSettings{}
	for slug, r := range cur.Repos {
		if slugRE.MatchString(slug) {
			kept[slug] = r
		}
	}
	all := map[string]any{}
	for k := range kept {
		all[k] = nil
	}
	for k, v := range sent {
		all[k] = v
	}
	repos := map[string]any{}
	for slug := range all {
		r, isSent := sent[slug].(map[string]any)
		if !slugRE.MatchString(slug) || (hasKey(sent, slug) && !isSent) {
			return nil, bad("repos must map owner/repo to an object")
		}
		old := kept[slug]
		entry := RepoSettings{}
		if isSent {
			ch := r["slack_channel"]
			if ch == nil {
				ch = ""
			}
			chs, ok := ch.(string)
			if !ok || len(chs) > 100 {
				return nil, bad("slack_channel must be a string of at most 100 characters")
			}
			entry.SlackChannel = strings.TrimSpace(chs)
			entry.AutoGrind = r["auto_grind"] == true
			if rv, has := r["reviewers"]; has {
				if rv == nil {
					entry.Reviewers = nil
				} else {
					l, err := cleanIDs(rv, rids, "reviewers must be a list of ids or null")
					if err != nil {
						return nil, err
					}
					entry.Reviewers = l
				}
			} else if old.Reviewers != nil {
				entry.Reviewers = known(old.Reviewers, rids)
			}
			entry.ReleaseHead, entry.ReleaseBase = old.ReleaseHead, old.ReleaseBase
			for k, dst := range map[string]*string{"release_head": &entry.ReleaseHead, "release_base": &entry.ReleaseBase} {
				if v, has := r[k]; has {
					bs, ok := v.(string)
					bs = strings.TrimSpace(bs)
					if v != nil && (!ok || (bs != "" && !branchRE.MatchString(bs))) {
						return nil, bad("%s must be a branch name", k)
					}
					*dst = bs
				}
			}
		} else { // stored only: the Repositories table omitted it
			entry = old
			if old.Reviewers != nil {
				entry.Reviewers = known(old.Reviewers, rids)
			}
		}
		if ch := entry.SlackChannel; ch != "" && !ids[ch] {
			if oldIDs[ch] {
				return nil, bad("channel %s is used by %s", ch, slug)
			}
			if ch != old.SlackChannel {
				return nil, bad("slack_channel %s is not a listed channel", ch)
			}
		}
		repos[slug] = storedRepo(entry)
	}
	// a removed channel still used by a repo that was not touched
	for slug, v := range repos {
		ch := v.(map[string]any)["slack_channel"].(string)
		if ch != "" && !ids[ch] && oldIDs[ch] {
			return nil, bad("channel %s is used by %s", ch, slug)
		}
	}
	out["repos"] = repos

	// ---- new keys: grind_limits, release_note, server ----
	gl := cur.GrindLimits
	var glIn map[string]any
	if present, err := decodeKey(body, "grind_limits", &glIn); err != nil {
		return nil, err
	} else if present {
		targets := map[string]*int{"max_rounds": &gl.MaxRounds, "poll_interval": &gl.PollInterval, "max_wait": &gl.MaxWait,
			"max_idle_waits": &gl.MaxIdleWaits, "stuck_seen": &gl.StuckSeen, "ci_timeout": &gl.CITimeout, "ci_poll": &gl.CIPoll}
		for k, v := range glIn {
			p, ok := targets[k]
			n, isInt := intOf(v)
			if !ok {
				return nil, bad("unknown grind_limits key %s", k)
			}
			if !isInt || n < 1 || n > 86400 {
				return nil, bad("grind_limits.%s must be a whole number from 1 to 86400", k)
			}
			*p = n
		}
	}
	out["grind_limits"] = gl
	rn := cur.ReleaseNote
	var rnIn map[string]any
	if present, err := decodeKey(body, "release_note", &rnIn); err != nil {
		return nil, err
	} else if present {
		if v, ok := rnIn["channel_name"]; ok {
			n, isS := v.(string)
			n = strings.TrimSpace(n)
			if !isS || n == "" || len(n) > 80 {
				return nil, bad("release_note.channel_name must be 1 to 80 characters")
			}
			rn.ChannelName = n
		}
		if v, ok := rnIn["channel_id"]; ok {
			id, isS := v.(string)
			if !isS || !channelRE.MatchString(id) {
				return nil, bad("release_note.channel_id must look like C0123ABCD")
			}
			rn.ChannelID = id
		}
		if v, ok := rnIn["suffix"]; ok {
			sf, isS := v.(string)
			if !isS || len(sf) > 40 || strings.ContainsAny(sf, "\x00\n") {
				return nil, bad("release_note.suffix must be one line of at most 40 characters")
			}
			rn.Suffix = sf
		}
		if v, ok := rnIn["cc"]; ok {
			list, isL := v.([]any)
			if !isL || len(list) > MaxListed {
				return nil, bad("release_note.cc must be a list of at most %d", MaxListed)
			}
			rn.CC = []CC{}
			dup := map[string]bool{}
			for _, e := range list {
				m, _ := e.(map[string]any)
				n, id := trimStr(m, "name"), trimStr(m, "slack_id")
				if n == "" || len(n) > 60 || !slackIDRE.MatchString(id) {
					return nil, bad("each cc needs a name and a Slack id like U0123ABCD")
				}
				if dup[id] {
					return nil, bad("Slack id %s is already listed", id)
				}
				dup[id] = true
				rn.CC = append(rn.CC, CC{n, id})
			}
		}
	}
	out["release_note"] = rn
	sv := cur.Server
	var svIn map[string]any
	if present, err := decodeKey(body, "server", &svIn); err != nil {
		return nil, err
	} else if present {
		if v, ok := svIn["port"]; ok {
			n, isInt := intOf(v)
			if !isInt || n < 1 || n > 65535 {
				return nil, bad("server.port must be a port number")
			}
			sv.Port = n
		}
		if v, ok := svIn["tailscale"]; ok {
			b, isB := v.(bool)
			if !isB {
				return nil, bad("server.tailscale must be true or false")
			}
			sv.Tailscale = b
		}
		if v, ok := svIn["tailscale_https_port"]; ok {
			n, isInt := intOf(v)
			if !isInt || (n != 443 && n != 8443 && n != 10000) {
				return nil, bad("server.tailscale_https_port must be 443, 8443 or 10000")
			}
			sv.TailscaleHTTPSPort = n
		}
		if v, ok := svIn["allow_hosts"]; ok {
			list, isL := v.([]any)
			if !isL || len(list) > 20 {
				return nil, bad("server.allow_hosts must be a list of at most 20 hosts")
			}
			sv.AllowHosts = []string{}
			for _, e := range list {
				h, isS := e.(string)
				h = strings.ToLower(strings.TrimSpace(h))
				if !isS || !hostRE.MatchString(h) {
					return nil, bad("server.allow_hosts has an invalid host")
				}
				sv.AllowHosts = append(sv.AllowHosts, h)
			}
		}
	}
	out["server"] = sv
	return out, nil
}

func hasKey(m map[string]any, k string) bool { _, ok := m[k]; return ok }

func storedRepo(r RepoSettings) map[string]any {
	m := map[string]any{"auto_grind": r.AutoGrind, "slack_channel": r.SlackChannel}
	if r.Reviewers == nil {
		m["reviewers"] = nil
	} else {
		m["reviewers"] = r.Reviewers
	}
	if r.ReleaseHead != "" {
		m["release_head"] = r.ReleaseHead
	}
	if r.ReleaseBase != "" {
		m["release_base"] = r.ReleaseBase
	}
	return m
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func nilIfEmpty(p *string) any {
	if p == nil || *p == "" {
		return nil
	}
	return *p
}

func cleanChannels(in []any) ([]Channel, error) {
	if len(in) > MaxListed {
		return nil, bad("at most %d", MaxListed)
	}
	out := []Channel{}
	seen := map[string]bool{}
	for _, e := range in {
		m, _ := e.(map[string]any)
		id, name := trimStr(m, "id"), trimStr(m, "name")
		if !channelRE.MatchString(id) {
			return nil, bad("channel id must look like C0123ABCD")
		}
		if n := len([]rune(name)); n < 1 || n > 60 {
			return nil, bad("channel name must be 1 to 60 characters")
		}
		if seen[id] {
			return nil, bad("channel %s is already listed", id)
		}
		seen[id] = true
		out = append(out, Channel{id, name})
	}
	return out, nil
}

func cleanReviewers(in []any) ([]Reviewer, error) {
	if len(in) > MaxListed {
		return nil, bad("at most %d", MaxListed)
	}
	out := []Reviewer{}
	slackIDs, logins := map[string]bool{}, map[string]bool{}
	sent := map[string]bool{}
	for _, e := range in {
		m, ok := e.(map[string]any)
		if !ok {
			return nil, bad("a reviewer must be an object")
		}
		name, sid, login := trimStr(m, "name"), trimStr(m, "slack_id"), trimStr(m, "github_login")
		if n := len([]rune(name)); n < 1 || n > 60 {
			return nil, bad("reviewer name must be 1 to 60 characters")
		}
		if sid == "" && login == "" {
			return nil, bad("add a Slack id or a GitHub login")
		}
		if sid != "" && !slackIDRE.MatchString(sid) {
			return nil, bad("Slack id must look like U0123ABCD")
		}
		if login != "" && !loginRE.MatchString(login) {
			return nil, bad("not a GitHub login")
		}
		if sid != "" && slackIDs[sid] {
			return nil, bad("Slack id %s is already listed", sid)
		}
		if login != "" && logins[strings.ToLower(login)] {
			return nil, bad("login %s is already listed", strings.ToLower(login))
		}
		slackIDs[sid], logins[strings.ToLower(login)] = true, true
		var id string
		if v, has := m["id"]; has && v != nil {
			id, ok = v.(string)
			if !ok || !reviewerIDRE.MatchString(id) {
				return nil, bad("reviewer id must be r-<8 hex>")
			}
			if sent[id] {
				return nil, bad("duplicate reviewer id")
			}
			sent[id] = true
		}
		out = append(out, Reviewer{id, name, sid, login})
	}
	taken := map[string]bool{}
	for id := range sent {
		taken[id] = true
	}
	for i := range out {
		if out[i].ID == "" {
			out[i].ID = newReviewerID(taken)
		}
	}
	return out, nil
}

func cleanIDs(in any, ids map[string]bool, msg string) ([]string, error) {
	list, ok := in.([]any)
	if !ok {
		return nil, bad("%s", msg)
	}
	out := []string{}
	seen := map[string]bool{}
	for _, e := range list {
		id, ok := e.(string)
		if !ok {
			return nil, bad("%s", msg)
		}
		if !ids[id] {
			return nil, bad("unknown reviewer id %s", id)
		}
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out, nil
}

var _ = fmt.Sprintf
