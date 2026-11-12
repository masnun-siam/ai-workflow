package notify

import (
	"net/http"
	"net/url"
	"os/exec"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps are the routes' dependencies.
type Deps struct{ Svc *Service }

// settingsView is NotifySettings (API §4) plus the ntfy status fields of W§4.4. Secrets are never returned.
type settingsView struct {
	Matrix      map[string]Cells `json:"matrix"`
	Events      []Event          `json:"events"`
	PublicURL   string           `json:"public_url"`
	Mac         macView          `json:"mac"`
	Push        pushView         `json:"push"`
	NtfyReady   bool             `json:"ntfy_ready"`
	Server      string           `json:"server"`
	Topic       string           `json:"topic"`
	User        string           `json:"user"`
	TokenSet    bool             `json:"token_set"`
	PasswordSet bool             `json:"password_set"`
	Env         []string         `json:"env"`
}

type macView struct {
	Available bool   `json:"available"`
	Notifier  string `json:"notifier"`
	Clickable bool   `json:"clickable"`
}

type pushView struct {
	Subscriptions int `json:"subscriptions"`
}

func (s *Service) View() settingsView {
	cfg := s.LoadConfig()
	mv := macView{Available: s.goos == "darwin", Notifier: "none"}
	if mv.Available {
		if s.notifierPath() != "" {
			mv.Notifier, mv.Clickable = "terminal-notifier", true
		} else if _, err := exec.LookPath("osascript"); err == nil {
			mv.Notifier = "osascript"
		}
	}
	env := cfg.EnvKeys
	if env == nil {
		env = []string{}
	}
	return settingsView{
		Matrix: cfg.Matrix(), Events: Events, PublicURL: cfg.PublicURL, Mac: mv,
		Push:      pushView{Subscriptions: s.subscriptions()},
		NtfyReady: cfg.Ntfy.Server != "" && cfg.Ntfy.Topic != "",
		Server:    cfg.Ntfy.Server, Topic: cfg.Ntfy.Topic, User: cfg.Ntfy.User,
		TokenSet: cfg.Ntfy.Token != "", PasswordSet: cfg.Ntfy.Password != "", Env: env,
	}
}

// Routes are the notification endpoints (API §5.7).
func Routes(d Deps) []server.Route {
	s := d.Svc
	return []server.Route{
		{Pattern: "GET /api/settings/notify", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			return 0, s.View(), nil
		})},
		{Pattern: "PUT /api/settings/notify", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var req struct {
				PublicURL *string `json:"public_url"`
				Cell      *struct {
					Event   string `json:"event"`
					Channel string `json:"channel"`
					On      *bool  `json:"on"`
				} `json:"cell"`
			}
			if err := server.Decode(r, &req); err != nil {
				return 0, nil, err
			}
			if req.PublicURL != nil {
				if err := validPublicURL(*req.PublicURL); err != nil {
					return 0, nil, err
				}
			}
			if c := req.Cell; c != nil {
				if !isEvent(c.Event) {
					return 0, nil, errs.Invalid("unknown event %q", c.Event)
				}
				if !isChannel(c.Channel) {
					return 0, nil, errs.Invalid("unknown channel %q", c.Channel)
				}
				if c.On == nil {
					return 0, nil, errs.Invalid("cell.on must be a boolean")
				}
			}
			if req.PublicURL != nil {
				if err := s.SetPublicURL(*req.PublicURL); err != nil {
					return 0, nil, err
				}
			}
			if c := req.Cell; c != nil {
				if err := s.SetCell(c.Event, c.Channel, *c.On); err != nil {
					return 0, nil, err
				}
			}
			return 0, s.View(), nil
		})},
		{Pattern: "POST /api/settings/notify/test", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var req struct {
				Channel string `json:"channel"`
			}
			if err := server.Decode(r, &req); err != nil {
				return 0, nil, err
			}
			if req.Channel != "push" && req.Channel != "mac" && req.Channel != "ntfy" {
				return 0, nil, errs.Invalid("channel must be push, mac or ntfy")
			}
			if err := s.Test(r.Context(), req.Channel); err != nil {
				return 0, map[string]any{"ok": false, "error": err.Error()}, nil
			}
			return 0, map[string]any{"ok": true}, nil
		})},
		{Pattern: "GET /api/push/key", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			k := s.VAPIDPublicKey()
			if k == "" {
				return 0, nil, errs.Upstream("cannot create the push key")
			}
			return 0, map[string]any{"public_key": k}, nil
		})},
		{Pattern: "POST /api/push/subscription", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var sub PushSubscription
			if err := server.Decode(r, &sub); err != nil {
				return 0, nil, err
			}
			if err := s.Subscribe(sub, r.UserAgent()); err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"ok": true}, nil
		})},
		{Pattern: "DELETE /api/push/subscription", Handler: server.Handle(func(r *http.Request) (int, any, error) {
			var req struct {
				Endpoint string `json:"endpoint"`
			}
			if err := server.Decode(r, &req); err != nil {
				return 0, nil, err
			}
			if req.Endpoint == "" {
				return 0, nil, errs.Invalid("endpoint is required")
			}
			if err := s.Unsubscribe(req.Endpoint); err != nil {
				return 0, nil, err
			}
			return 0, map[string]any{"ok": true}, nil
		})},
	}
}

func validPublicURL(u string) error {
	if u == "" {
		return nil
	}
	pu, err := url.Parse(u)
	if err != nil || (pu.Scheme != "http" && pu.Scheme != "https") || pu.Host == "" || len(u) > 300 {
		return errs.Invalid("public_url must be an http(s) URL")
	}
	return nil
}
