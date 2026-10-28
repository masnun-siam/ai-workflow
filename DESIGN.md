# Design system: framed sheet

The source of truth is `ui/src/styles/global.css` (tokens in `:root` and the two dark blocks).
This file states the rules those tokens serve. Mode: Operate — scanability and consistency over
expression.

## The move

The rail and the 48px top bar share one teal-grey frame (`--frame`) with no rule between them.
The page lives on a white sheet (`.content`, `--surface`) with a 1px `--line` edge, 16px corners
(`--r-sheet`) and no shadow, inset 8px from the window's right and bottom. The detail panel is a
second sheet beside it. On a phone the frame disappears and the sheet is the screen.

## Colour: two signals

| Token | Use |
| --- | --- |
| `--you` (#C2410C) | Needs you: the Inbox count, questions, a lane waiting on the user |
| `--bad` (#C4242A) | Failed, errors, destructive actions |
| `--accent` (teal #1B6C80) | Selection only: active tab underline, chosen option, focus ring, current stage, live dot, logo mark |
| `--primary` | The one primary button per screen: near-black in light, near-white in dark |

Stages carry no hue. `--plan`, `--build`, `--review` and `--ship` are a grey ramp that darkens as
work moves toward merged, and every stage chip renders neutral. Keep it that way: a new status gets
a label, not a colour.

## Type

- IBM Plex Sans 400/500/600 (self-hosted via `@fontsource`). 600 for titles, 500 for emphasis;
  no 700.
- IBM Plex Mono for IDs, commands, keys and figures (costs, durations, counts in tables, tab
  counts). Not for prose labels.
- Sizes: page title 22px (20 on phone), section 15px, body 14px, small 12–12.5px.
- Tabular figures everywhere; numeric table columns are `.num` (right-aligned, mono).

## Shape and density

- Radii: `--r-sheet` 16, `--r-card` 8, `--r-ctl` 6, pills fully round. Nothing else.
- Dense: 32px controls and nav rows, ~40px table rows, 10–12px list padding, 20px page gap.
- Surfaces separate by one tone step (`--bg` wells on the white sheet) or a 1px line. Shadows only
  on what floats: menus, dialogs, toasts, the sticky composer, the overlay panel.
- Selected or attention cards use a 1px inset outline, not a glow or ring shadow.

## The track

The feature track is the signature element: done planning stages fill in ink, the current one in
the accent, the rest stay pale; the build segment shows issues as the grey ramp toward merged.

## Away mode

Away mode changes the whole frame to `--away-frame` (warm stone light, warm near-black dark); the
sheet stays as it is.

## Bans

Gradients (except the functional table scroll-edge shadows), glass, icons in tinted squares,
unicode glyphs as icons, eyebrow labels, uppercase tracked labels, decorative dot grids, a second
filled primary on one screen.
