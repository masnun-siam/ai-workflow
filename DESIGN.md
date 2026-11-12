# setu: design

Source of truth: `web/src/styles.css`, `web/src/state/prefs.ts`. The reference prototype is `docs/setu/prototype/`.

## Looks, modes, layouts

| Setting | Values | Default | Applied as |
|---|---|---|---|
| Look | Console, River | Console | `body.skin-console` / `body.skin-river` |
| Mode | System, Dark, Light | System | `html[data-theme]` (absent = follow the OS) |
| Layout | Rail + drawer (`drawer`), Tabs + split (`split`) | drawer | layout classes |

Stored in `localStorage` key `setu.prefs.v1` (per browser). Storage may be blocked; the page renders without it.

## Tokens

Each look defines the same variables, redefined for light mode: `--bg --p1 --p2 --line --tx --mu --dim --acc --accink --sel --q --bad --ok --warn`
plus `--font --hfont --r --rc` (radius, card radius).

| | Console dark | River dark |
|---|---|---|
| Fonts | JetBrains Mono everywhere | Inter body, Space Grotesk headings |
| Radius | 0 | 8px, cards 10px |
| `--bg` / `--p1` | `#0A0A09` / `#11110F` | `#0B1220` / `#111A2C` |
| `--tx` / `--mu` | `#ECE7D9` / `#A8A291` | `#E6ECF7` / `#A2AEC6` |
| `--acc` | `#FFB547` amber | `#5AB0FF` blue |

Light variants: Console on warm paper (`--bg #F3EEE2`, `--acc #8F5400`); River on cool white (`--bg #F3F6FB`, `--acc #1D66C9`).
`--bad`, `--ok`, `--warn` carry status; `--q` marks a live or question state. Contrast is tested (`web/src/contrast.test.ts`); keep every text token at AA on its panel.

## Principles

- Keyboard first: letter hints sit on buttons; one footer line lists the screen's keys; `?` shows the whole map.
- Server-built actions render as given. Tone classes `c-w c-q c-o c-b` (warn, query, ok, bad) colour tags.
- Density over decoration: flat panels and 1px `--line` borders; use shadow or gradient only where it marks layering.
- Never colour alone: pair status colour with a word or glyph.
- Respect `prefers-reduced-motion`; no motion is required to understand a state.
