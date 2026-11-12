package notify

import (
	"context"
	"encoding/base64"
	"errors"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const ntfyTimeout = 5 * time.Second

// sendNtfy posts one push. "" on success, else a short error that never contains the URL
// (it holds the topic) or a credential.
func (s *Service) sendNtfy(ctx context.Context, cfg Config, h Headers, text string) string {
	n := cfg.Ntfy
	if n.Server == "" || n.Topic == "" {
		return "ntfy is not set up"
	}
	if u, err := url.Parse(n.Server); err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		s.warnf("ntfy server must be an http(s) URL; push skipped")
		return "ntfy server must be an http(s) URL"
	}
	target := strings.TrimRight(n.Server, "/") + "/" + url.PathEscape(n.Topic)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(text))
	if err != nil {
		return "bad ntfy url"
	}
	for k, v := range h {
		req.Header.Set(k, v)
	}
	// Cloudflare's Browser Integrity Check rejects a default User-Agent.
	req.Header.Set("User-Agent", "setu (ntfy publisher)")
	if n.Token != "" {
		req.Header.Set("Authorization", "Bearer "+n.Token)
	} else if n.User != "" && n.Password != "" {
		req.Header.Set("Authorization", "Basic "+base64.StdEncoding.EncodeToString([]byte(n.User+":"+n.Password)))
	}
	cl := &http.Client{Timeout: ntfyTimeout}
	resp, err := cl.Do(req)
	if err != nil {
		var ne net.Error
		msg := "request failed"
		if errors.As(err, &ne) && ne.Timeout() {
			msg = "timeout"
		}
		s.warnf("ntfy push failed: %s", msg)
		return msg
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		s.warnf("ntfy push failed: HTTP %d", resp.StatusCode)
		return "HTTP " + strconv.Itoa(resp.StatusCode)
	}
	return ""
}
