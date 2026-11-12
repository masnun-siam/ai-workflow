package notify

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/hkdf"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// PushSubscription is the browser's PushSubscription JSON.
type PushSubscription struct {
	Endpoint string `json:"endpoint"`
	Keys     struct {
		P256dh string `json:"p256dh"`
		Auth   string `json:"auth"`
	} `json:"keys"`
}

type storedSub struct {
	Endpoint  string `json:"endpoint"`
	Keys      keys   `json:"keys"`
	UA        string `json:"ua"`
	CreatedAt string `json:"created_at"`
}

type keys struct {
	P256dh string `json:"p256dh"`
	Auth   string `json:"auth"`
}

type pushFile struct {
	VapidPublic   string      `json:"vapid_public"`
	VapidPrivate  string      `json:"vapid_private"`
	Subject       string      `json:"subject"`
	Subscriptions []storedSub `json:"subscriptions"`
}

const maxSubs = 20

var b64 = base64.RawURLEncoding

func (s *Service) pushPath() string { return s.h.Path("push.json") }

// loadPush reads push.json, generating the VAPID key pair once.
func (s *Service) loadPush() (pushFile, error) {
	return home.UpdateJSON(s.pushPath(), func(p *pushFile) error {
		if p.VapidPrivate != "" && p.VapidPublic != "" {
			return errNoWrite
		}
		k, err := ecdh.P256().GenerateKey(rand.Reader)
		if err != nil {
			return err
		}
		p.VapidPrivate = b64.EncodeToString(k.Bytes())
		p.VapidPublic = b64.EncodeToString(k.PublicKey().Bytes())
		if p.Subject == "" {
			p.Subject = "mailto:setu@localhost"
		}
		return nil
	})
}

var errNoWrite = errors.New("no write")

func (s *Service) readPush() pushFile {
	p, err := s.loadPush()
	if err != nil && !errors.Is(err, errNoWrite) {
		s.warnf("push.json: %v", err)
	}
	return p
}

// VAPIDPublicKey is the base64url application server key ("" if it cannot be created).
func (s *Service) VAPIDPublicKey() string { return s.readPush().VapidPublic }

func (s *Service) subscriptions() int { return len(s.readPush().Subscriptions) }

// Subscribe stores (or refreshes) a push subscription.
func (s *Service) Subscribe(sub PushSubscription, ua string) error {
	u, err := url.Parse(sub.Endpoint)
	if err != nil || u.Host == "" || (u.Scheme != "https" && !(u.Scheme == "http" && isLoopback(u.Hostname()))) {
		return errs.Invalid("endpoint must be an https URL")
	}
	pub, err := b64.DecodeString(strings.TrimRight(sub.Keys.P256dh, "="))
	if err != nil {
		return errs.Invalid("keys.p256dh is not base64url")
	}
	if _, err := ecdh.P256().NewPublicKey(pub); err != nil {
		return errs.Invalid("keys.p256dh is not a P-256 point")
	}
	auth, err := b64.DecodeString(strings.TrimRight(sub.Keys.Auth, "="))
	if err != nil || len(auth) != 16 {
		return errs.Invalid("keys.auth must be 16 bytes, base64url")
	}
	if len(ua) > 300 {
		ua = ua[:300]
	}
	if _, err := s.loadPush(); err != nil && !errors.Is(err, errNoWrite) {
		return err
	}
	_, err = home.UpdateJSON(s.pushPath(), func(p *pushFile) error {
		ns := storedSub{sub.Endpoint, keys{sub.Keys.P256dh, sub.Keys.Auth}, ua, s.now().UTC().Format(time.RFC3339)}
		for i, x := range p.Subscriptions {
			if x.Endpoint == sub.Endpoint {
				ns.CreatedAt = x.CreatedAt
				p.Subscriptions[i] = ns
				return nil
			}
		}
		if len(p.Subscriptions) >= maxSubs {
			p.Subscriptions = p.Subscriptions[len(p.Subscriptions)-maxSubs+1:]
		}
		p.Subscriptions = append(p.Subscriptions, ns)
		return nil
	})
	return err
}

// Unsubscribe removes a subscription by endpoint (a missing one is fine).
func (s *Service) Unsubscribe(endpoint string) error {
	_, err := home.UpdateJSON(s.pushPath(), func(p *pushFile) error {
		out := p.Subscriptions[:0]
		for _, x := range p.Subscriptions {
			if x.Endpoint != endpoint {
				out = append(out, x)
			}
		}
		if len(out) == len(p.Subscriptions) {
			return errNoWrite
		}
		p.Subscriptions = out
		return nil
	})
	if errors.Is(err, errNoWrite) {
		return nil
	}
	return err
}

func isLoopback(h string) bool { return h == "localhost" || h == "127.0.0.1" || h == "::1" }

type pushPayload struct {
	Event string `json:"event"`
	Title string `json:"title"`
	Body  string `json:"body"`
	Path  string `json:"path"`
	Tag   string `json:"tag"`
}

// sendPush delivers payload to every subscription; "" if at least one accepted it (or there are
// none and quiet), else a short error. 404/410 drop the subscription.
func (s *Service) sendPush(ctx context.Context, pl pushPayload, urgency string) string {
	p := s.readPush()
	if len(p.Subscriptions) == 0 {
		return "no push subscription"
	}
	body, _ := json.Marshal(pl)
	ok, last := 0, ""
	for _, sub := range p.Subscriptions {
		code, err := s.pushOne(ctx, p, sub, body, urgency)
		switch {
		case err != nil:
			last = err.Error()
		case code == http.StatusNotFound || code == http.StatusGone:
			_ = s.Unsubscribe(sub.Endpoint)
			last = "subscription expired"
		case code/100 != 2:
			last = "HTTP " + strconv.Itoa(code)
		default:
			ok++
		}
	}
	if ok > 0 {
		return ""
	}
	s.warnf("web push failed: %s", last)
	return last
}

func (s *Service) pushOne(ctx context.Context, p pushFile, sub storedSub, payload []byte, urgency string) (int, error) {
	u, err := url.Parse(sub.Endpoint)
	if err != nil {
		return 0, errors.New("bad endpoint")
	}
	data, err := encryptAES128GCM(payload, sub.Keys.P256dh, sub.Keys.Auth)
	if err != nil {
		return 0, errors.New("encryption failed")
	}
	jwt, err := vapidJWT(p, u.Scheme+"://"+u.Host, s.now())
	if err != nil {
		return 0, errors.New("vapid signing failed")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, sub.Endpoint, bytes.NewReader(data))
	if err != nil {
		return 0, errors.New("bad endpoint")
	}
	req.Header.Set("Content-Encoding", "aes128gcm")
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("TTL", "86400")
	req.Header.Set("Urgency", urgency)
	req.Header.Set("Authorization", "vapid t="+jwt+", k="+p.VapidPublic)
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		return 0, errors.New("request failed")
	}
	resp.Body.Close()
	return resp.StatusCode, nil
}

func vapidJWT(p pushFile, aud string, now time.Time) (string, error) {
	raw, err := b64.DecodeString(p.VapidPrivate)
	if err != nil {
		return "", err
	}
	priv, err := ecdsa.ParseRawPrivateKey(elliptic.P256(), raw)
	if err != nil {
		return "", err
	}
	hdr := b64.EncodeToString([]byte(`{"typ":"JWT","alg":"ES256"}`))
	claims, _ := json.Marshal(map[string]any{"aud": aud, "exp": now.Add(12 * time.Hour).Unix(), "sub": p.Subject})
	in := hdr + "." + b64.EncodeToString(claims)
	sum := sha256.Sum256([]byte(in))
	r, sg, err := ecdsa.Sign(rand.Reader, priv, sum[:])
	if err != nil {
		return "", err
	}
	sig := make([]byte, 64)
	r.FillBytes(sig[:32])
	sg.FillBytes(sig[32:])
	return in + "." + b64.EncodeToString(sig), nil
}

// encryptAES128GCM is RFC 8291 (Web Push message encryption) with a single RFC 8188 record.
func encryptAES128GCM(payload []byte, p256dh, authSecret string) ([]byte, error) {
	uaPubRaw, err := b64.DecodeString(strings.TrimRight(p256dh, "="))
	if err != nil {
		return nil, err
	}
	auth, err := b64.DecodeString(strings.TrimRight(authSecret, "="))
	if err != nil {
		return nil, err
	}
	if len(payload) > 3993 {
		return nil, errors.New("payload too large")
	}
	curve := ecdh.P256()
	uaPub, err := curve.NewPublicKey(uaPubRaw)
	if err != nil {
		return nil, err
	}
	as, err := curve.GenerateKey(rand.Reader)
	if err != nil {
		return nil, err
	}
	shared, err := as.ECDH(uaPub)
	if err != nil {
		return nil, err
	}
	asPub := as.PublicKey().Bytes()
	prkKey, err := hkdf.Extract(sha256.New, shared, auth)
	if err != nil {
		return nil, err
	}
	keyInfo := append(append([]byte("WebPush: info\x00"), uaPubRaw...), asPub...)
	ikm, err := hkdf.Expand(sha256.New, prkKey, string(keyInfo), 32)
	if err != nil {
		return nil, err
	}
	salt := make([]byte, 16)
	if _, err := rand.Read(salt); err != nil {
		return nil, err
	}
	prk, err := hkdf.Extract(sha256.New, ikm, salt)
	if err != nil {
		return nil, err
	}
	cek, err := hkdf.Expand(sha256.New, prk, "Content-Encoding: aes128gcm\x00", 16)
	if err != nil {
		return nil, err
	}
	nonce, err := hkdf.Expand(sha256.New, prk, "Content-Encoding: nonce\x00", 12)
	if err != nil {
		return nil, err
	}
	blk, err := aes.NewCipher(cek)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(blk)
	if err != nil {
		return nil, err
	}
	ct := gcm.Seal(nil, nonce, append(append([]byte{}, payload...), 0x02), nil)
	out := make([]byte, 0, 16+4+1+len(asPub)+len(ct))
	out = append(out, salt...)
	out = binary.BigEndian.AppendUint32(out, 4096)
	out = append(out, byte(len(asPub)))
	out = append(out, asPub...)
	return append(out, ct...), nil
}
