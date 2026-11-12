package review

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// Panel states and phases.
const (
	StRunning   = "running"
	StApproved  = "approved"
	StCap       = "cap reached"
	StFailed    = "failed"
	PhWaitRoot  = "waiting_root"
	PhLenses    = "lenses"
	PhRoot      = "root"
	PhDone      = "done"
	advWait     = "wait"
	advApproved = "approved"
	advNext     = "next"
	advCap      = "cap reached"
	advFailed   = "failed"
	panelDir    = "peer-review"
	panelFile   = "panel.json"
)

var panelIDRe = regexp.MustCompile(`^p-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$`)

// ValidID reports whether id is a panel id.
func ValidID(id string) bool { return panelIDRe.MatchString(id) }

// rec is panel.json (the Python layout; unknown keys are not kept).
type rec struct {
	ID          string            `json:"id"`
	Repo        string            `json:"repo"`
	Artifact    string            `json:"artifact"`
	Lenses      []string          `json:"lenses"`
	RootSession *string           `json:"root_session"`
	Round       int               `json:"round"`
	Dropped     []string          `json:"dropped"`
	Failed      []string          `json:"failed"`
	State       string            `json:"state"`
	Reason      *string           `json:"reason"`
	Phase       string            `json:"phase"`
	LensSession map[string]string `json:"lens_sessions"`
	MaxRounds   *int              `json:"max_rounds,omitempty"` // per-panel raise
}

func (p *rec) active() []string {
	var out []string
	for _, l := range p.Lenses {
		if !contains(p.Dropped, l) {
			out = append(out, l)
		}
	}
	return out
}

func (p *rec) max(cfg Config) int {
	if p.MaxRounds != nil && *p.MaxRounds > 0 {
		return *p.MaxRounds
	}
	return cfg.MaxRounds
}

func (p *rec) setReason(s string) { p.Reason = &s }

func (p *rec) markFailed(l string) {
	if !contains(p.Failed, l) {
		p.Failed = append(p.Failed, l)
	}
}

func (p *rec) unfail(l string) { p.Failed = remove(p.Failed, l) }

func (p *rec) dropLens(l string) {
	if !contains(p.Dropped, l) {
		p.Dropped = append(p.Dropped, l)
	}
	p.unfail(l)
}

func remove(l []string, s string) []string {
	out := l[:0:0]
	for _, x := range l {
		if x != s {
			out = append(out, x)
		}
	}
	return out
}

func (s *Service) panelsDir() string { return s.d.Home.Path(panelDir) }

func (s *Service) panelPath(id string) string {
	return filepath.Join(s.panelsDir(), id, panelFile)
}

func (s *Service) roundFile(id string, round int, lens string) string {
	return filepath.Join(s.panelsDir(), id, "round-"+itoa(round), lens+".md")
}

func itoa(n int) string { return strconv.Itoa(n) }

// load reads panel.json; a missing, empty or corrupt file is NotFound.
func (s *Service) load(id string) (rec, error) {
	if !ValidID(id) {
		return rec{}, errs.NotFound("panel %q not found", id)
	}
	var p rec
	if err := home.ReadJSON(s.panelPath(id), &p); err != nil {
		return rec{}, err
	}
	if p.ID != id {
		return rec{}, errs.NotFound("panel %q not found", id)
	}
	if p.Round < 1 {
		p.Round = 1
	}
	return p, nil
}

func (s *Service) save(p rec) error {
	if p.Lenses == nil {
		p.Lenses = []string{}
	}
	if p.Dropped == nil {
		p.Dropped = []string{}
	}
	if p.Failed == nil {
		p.Failed = []string{}
	}
	if p.LensSession == nil {
		p.LensSession = map[string]string{}
	}
	unlock, err := home.Lock(s.panelPath(p.ID))
	if err != nil {
		return err
	}
	defer unlock()
	return home.WriteJSON(s.panelPath(p.ID), p)
}

// newPanelID makes the folder exclusively, retrying on a collision.
func (s *Service) newPanelID() (string, error) {
	if err := os.MkdirAll(s.panelsDir(), 0o755); err != nil {
		return "", err
	}
	for i := 0; i < 20; i++ {
		var b [3]byte
		if _, err := rand.Read(b[:]); err != nil {
			return "", err
		}
		id := "p-" + s.now().UTC().Format("20060102T150405Z") + "-" + hex.EncodeToString(b[:])
		err := os.Mkdir(filepath.Join(s.panelsDir(), id), 0o755)
		if err == nil {
			return id, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return "", err
		}
	}
	return "", errors.New("could not allocate a panel id")
}

func (s *Service) now() time.Time {
	if s.d.Now != nil {
		return s.d.Now()
	}
	return time.Now()
}

// ---- verdicts ----

var verdictRe = regexp.MustCompile("(?im)^[\\s*_`>#-]*verdict:\\s*[*_`]*(approve|changes)")

// ParseVerdict returns "approve" or "changes" from a lens's final message: the last
// `Verdict: approve|changes` line wins (the word must not continue as `approved` or `changes-x`);
// text with no verdict line is "changes".
func ParseVerdict(text string) string {
	verdict := "changes"
	for _, m := range verdictRe.FindAllStringSubmatchIndex(text, -1) {
		end := m[1]
		if end < len(text) {
			r, _ := utf8.DecodeRuneInString(text[end:])
			if r == '-' || r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r) {
				continue
			}
		}
		verdict = strings.ToLower(text[m[2]:m[3]])
	}
	return verdict
}

// verdictOf reads the lens's verdict file of a round: "" = not reported.
func (s *Service) verdictOf(p rec, round int, lens string) string {
	b, err := os.ReadFile(s.roundFile(p.ID, round, lens))
	if err != nil {
		return ""
	}
	return ParseVerdict(string(b))
}

// recordVerdict writes the lens's raw final message for the panel's current round.
func (s *Service) recordVerdict(p *rec, lens, text string) error {
	if !contains(p.Lenses, lens) || contains(p.Dropped, lens) {
		return errs.Invalid("%q is not an active lens of panel %s", lens, p.ID)
	}
	f := s.roundFile(p.ID, p.Round, lens)
	if err := os.MkdirAll(filepath.Dir(f), 0o755); err != nil {
		return err
	}
	if err := home.AtomicWrite(f, []byte(text), 0o644); err != nil {
		return err
	}
	p.unfail(lens)
	return nil
}

// advance decides what a running panel does next and moves the round on "next".
func (s *Service) advance(p *rec, cfg Config) string {
	if p.State != StRunning {
		return advWait
	}
	active := p.active()
	if len(active) == 0 {
		p.State, p.Phase = StFailed, PhDone
		p.setReason("every lens was dropped")
		return advFailed
	}
	all := true
	for _, l := range active {
		switch s.verdictOf(*p, p.Round, l) {
		case "":
			return advWait
		case "changes":
			all = false
		}
	}
	if all {
		p.State, p.Phase = StApproved, PhDone
		p.Reason = nil
		return advApproved
	}
	if p.Round >= p.max(cfg) {
		p.State, p.Phase = StCap, PhDone
		p.setReason("round cap reached")
		return advCap
	}
	p.Round++
	return advNext
}

// Status is Panel.status (API §4).
type Status struct {
	Approved int               `json:"approved"`
	Total    int               `json:"total"`
	Lenses   map[string]string `json:"lenses"`
}

func (s *Service) status(p rec) Status {
	st := Status{Lenses: map[string]string{}}
	for _, l := range p.active() {
		st.Total++
		switch {
		case contains(p.Failed, l):
			st.Lenses[l] = "failed"
		default:
			switch s.verdictOf(p, p.Round, l) {
			case "approve":
				st.Lenses[l] = "approve"
				st.Approved++
			case "changes":
				st.Lenses[l] = "changes"
			default:
				st.Lenses[l] = "waiting"
			}
		}
	}
	return st
}
