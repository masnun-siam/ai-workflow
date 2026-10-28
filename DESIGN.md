# Design system: teal pipeline

The source of truth is `ui/src/styles/global.css` (tokens in `:root` and the two dark blocks) and
`ui/src/features/features.css` (the Features screens). This file states the rules those tokens
serve. Mode: Operate, with a bold first read: a page should say what needs you before it is read.

## The shell

A dark rail (`--rail`) beside a light page (`--frame`); work sits in white panels (`.pane`, 16px
corners, a 1px `--line` edge, no shadow). The rail redefines the surface tokens for everything inside
it, so its nav, Away card, usage meters and buttons need no rules of their own. Away mode warms the
rail (`--away-rail`). On a phone the rail folds into the bottom bar.

## Colour

| Token | Use |
| --- | --- |
| `--st0`…`--st5` | The six stages, pale to deep teal, Shipped in ink. Stage tiles, the stage blocks, card tops |
| `--ship`, `--review`, `--build`, `--plan` | Issue states on the same ramp: merged, in review, building, ready |
| `--you` (#C2410C) | Needs you, and only that: counts, alerts, cards and squares that wait on the user |
| `--bad` | Failed, errors, destructive actions |
| `--accent` (#0F6E64) | Create actions (`variant="accent"`), focus, selection, the current stage |
| `--primary` | Next-step buttons: near-black in light, near-white in dark |

## Type

- Geist 400–700 and Geist Mono (self-hosted via `@fontsource`).
- Page titles `.display` 44px/700 (32px on a phone), feature titles 40px, section heads 20px/600,
  body 14px. Large figures (stage counts, merged/total) are 34–40px/600.
- Mono for IDs, commands, issue numbers, metadata lines and money. Not for prose.
- Tabular figures everywhere.

## Shape and density

- Radii: `--r-sheet` 16 (panels, cards), `--r-card` 14, `--r-ctl` 9 (controls), 8 for small chips,
  pills fully round.
- Buttons 34px (28px small), capture controls 44px. Section gap 28px.
- Shadows only on what floats: menus, dialogs, toasts, the composer, the overlay panel.

## Signature elements

- **The pipeline:** six stage tiles; empty stages are dashed outlines with a faint zero.
- **Issue squares:** one square per issue, coloured by state; needs-refining is a dashed outline,
  needs-you is orange.
- **The build map:** issues in dependency waves, left to right, with arrows between columns.
- **The capture box:** one input for a feature or a fix, routed by Auto (jev), Feature or Small change.

## Bans

Gradients (except the functional table scroll-edge shadows), glass, icons in tinted squares, unicode
glyphs as icons, eyebrow labels, uppercase tracked labels, orange on anything that does not need the
user, a second solid-orange element competing with the needs-you alert.
