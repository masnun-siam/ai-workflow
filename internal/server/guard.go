package server

import (
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

// SetTailnet registers the tailnet host names and the node owner login. Requests whose Host is
// not loopback are accepted only for these hosts (or Config.AllowHosts) and only when the
// Tailscale-User-Login header names the owner.
func (s *Server) SetTailnet(hosts []string, owner string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.tsHosts = nil
	for _, h := range hosts {
		s.tsHosts = append(s.tsHosts, strings.ToLower(h))
	}
	s.tsOwner = strings.ToLower(owner)
}

func (s *Server) loopbackPort() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if s.port != 0 {
		return s.port
	}
	return s.cfg.Port
}

func (s *Server) allowed(r *http.Request) bool {
	host := strings.ToLower(r.Host)
	if host == "" {
		return false
	}
	p := strconv.Itoa(s.loopbackPort())
	loopback := host == net.JoinHostPort("127.0.0.1", p) || host == net.JoinHostPort("localhost", p)
	if !loopback {
		s.mu.RLock()
		ok := false
		for _, h := range s.tsHosts {
			ok = ok || h == host
		}
		for _, h := range s.cfg.AllowHosts {
			ok = ok || strings.ToLower(h) == host
		}
		owner := s.tsOwner
		s.mu.RUnlock()
		if !ok || owner == "" || strings.ToLower(r.Header.Get("Tailscale-User-Login")) != owner {
			return false
		}
	}
	if o := r.Header.Get("Origin"); o != "" {
		u, err := url.Parse(o)
		if err != nil || strings.ToLower(u.Host) != host {
			return false
		}
	}
	return true
}
