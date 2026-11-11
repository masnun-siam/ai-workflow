package server

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/execx"
)

// tailscaleUp exposes the loopback port with `tailscale serve --bg --https=<p>`, registers the
// node's DNS name and owner login with the guard, and returns a func that removes the handler.
// It refuses to overwrite a foreign handler on that port and adopts one already pointing here.
func (s *Server) tailscaleUp(ctx context.Context) (func(), error) {
	r := execx.Run(ctx, []string{"tailscale", "status", "--json"}, execx.Opts{Timeout: 5 * time.Second})
	if r.Code != 0 {
		return nil, fmt.Errorf("not available: %s", r.LastLine())
	}
	var st struct {
		BackendState string
		Self         struct {
			DNSName string
			UserID  int64
		}
		User map[string]struct{ LoginName string }
	}
	if err := json.Unmarshal(r.Stdout, &st); err != nil {
		return nil, fmt.Errorf("bad status output: %v", err)
	}
	if st.BackendState != "Running" {
		return nil, fmt.Errorf("not running (%s)", st.BackendState)
	}
	dns := strings.TrimSuffix(strings.ToLower(st.Self.DNSName), ".")
	login := st.User[strconv.FormatInt(st.Self.UserID, 10)].LoginName
	if dns == "" || login == "" {
		return nil, fmt.Errorf("no node name or owner in status")
	}
	hp := s.cfg.TailscaleHTTPSPort
	if hp == 0 {
		hp = 443
	}
	target := "http://127.0.0.1:" + strconv.Itoa(s.loopbackPort())

	sr := execx.Run(ctx, []string{"tailscale", "serve", "status", "--json"}, execx.Opts{Timeout: 5 * time.Second})
	var serve struct {
		Web map[string]struct {
			Handlers map[string]struct{ Proxy string }
		}
	}
	_ = json.Unmarshal(sr.Stdout, &serve)
	if w, ok := serve.Web[dns+":"+strconv.Itoa(hp)]; ok && len(w.Handlers) > 0 {
		if h, ok := w.Handlers["/"]; !ok || strings.TrimSuffix(h.Proxy, "/") != target {
			return nil, fmt.Errorf("port %d already serves something else; not overwriting", hp)
		}
	} else if r := execx.Run(ctx, []string{"tailscale", "serve", "--bg", "--https=" + strconv.Itoa(hp), target}, execx.Opts{Timeout: 15 * time.Second}); r.Code != 0 {
		return nil, fmt.Errorf("serve failed: %s", r.LastLine())
	}
	host := dns
	if hp != 443 {
		host = dns + ":" + strconv.Itoa(hp)
	}
	s.SetTailnet([]string{host}, login)
	s.logf("tailscale: serving https://%s", host)
	return func() {
		execx.Run(context.Background(), []string{"tailscale", "serve", "--https=" + strconv.Itoa(hp), "off"}, execx.Opts{Timeout: 10 * time.Second})
	}, nil
}
