# aiw ui (frontend)

Covers: `run-engine/ui_static/`, `run-engine/test_ui_static.py`

A no-build single-page app: native ES modules, vendored Preact plus htm, one stylesheet. The server serves this directory at `/static/` ([ui.md](ui.md)). It talks only to the routes in [ui-api.md](ui-api.md).

## Layout

| Path | What |
|---|---|
| `index.html` | Shell: `#app`, `app.css`, `app.js` as a module, manifest, icons. Registers `/sw.js`. |
| `app.js` | Router (`parseRoute`), `App` shell (header, nav, badges, dialogs), the shared `poll()` helper, `NAV`, `limitChips` |
| `app.css` | All styles. Dark only. Colour tokens on `:root` (`--bg`, `--card`, `--fg`, ...). `@font-face` for the vendored fonts. |
| `vendor/preact.mjs`, `vendor/htm.mjs` | Preact 11.0.0 and htm 3.1.1, vendored unmodified except a header, with `LICENSE-*.txt` |
| `vendor/fonts/` | IBM Plex Sans 400/500/600 and JetBrains Mono 400/500 (`.woff2`) |
| `icons/` | `icon.svg`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` |
| `manifest.webmanifest` | PWA manifest: standalone, shortcuts to `#/dispatch` and `#/new` |
| `sw.js` | Installability only. It caches nothing. A failed navigation gets an offline page ("Can't reach aiw ui"). |

## Routes and views

Hash routes, parsed by `parseRoute` in `app.js`. Hash input is untrusted, so ids are matched by regex.

| Hash | Component (module) | View |
|---|---|---|
| `#/` | `Board` (`board.js`) | Board: columns, search, facet filters, need-you filter |
| `#/new` | `Launcher` (`launcher.js`) | New run: grouped commands (`GROUPS`), custom prompt, worklog dates, peer review lenses |
| `#/sessions` | `History` (`history.js`) | Session list, resume actions |
| `#/session/<id>` | `Session` (`session.js`) | Transcript stream, prompt box |
| `#/answer/<sid>` | `Answer` (`answer.js`) | Answer an `aiw ask` round |
| `#/run/<owner>/<repo>/<n>` | `RunDetail` (`run.js`) | Run page: station timeline, sessions tab, grind controls, options |
| `#/flow`, `#/flow/new`, `#/flow/<f-id>` | `Flow` (`flow.js`) | Guided Flow stepper ([planning](features/planning.md)) |
| `#/dispatch` | `Dispatch` (`dispatch.js`) | New pipeline form, pipeline list ([dispatch](features/dispatch.md)) |
| `#/dispatch/<p-id>` | `PipelineDetail` (`dispatch.js`) | Pipeline rows, merge order |
| `#/settings` | `Settings` (`settings.js`) | Claude commands, vault, repo scan |

## Shared modules

| Module | Owns |
|---|---|
| `afk.js` | Header AFK control and end-of-window summary (`AfkControl`, `AfkSummary`). Posts to `/api/afk`. |
| `cleanup.js` | Cleanup dialog (`CleanupDialog`), opened by the `aiw:cleanup` event (`openCleanup`) |
| `flowside.js` | Flow side panes: vault note viewer (`NotePane`), issue rows, flow switcher |
| `fmt.js` | Formatters (time, cost, tokens, labels) and `loadPref`/`savePref` (safe `localStorage`) |
| `ghstatus.js` | Card GitHub chips, issue/PR links, failing checks (`GhChips`, `GhLinks`, `FailingChecks`) |
| `issue.js` | Issue link and popup (`IssueLink`, `IssueDialog`) |
| `keys.js` | Keyboard shortcuts (`SHORTCUTS`, `keyIntent`, `moveFocus`), command palette (`Palette`) |
| `limits.js` | Banner on a limited run: resume time, Resume now, Cancel auto-resume, another account (`LimitBanner`) |
| `linked.js` | Plain text with URLs turned into links (`Linked`) |
| `notify.js` | Browser notifications and page title for waiting sessions. It reads only ids, command and repo. |
| `peek.js` | Issue/PR popup host, opened by the `aiw:peek` event (`openPeek`) |
| `pr.js` | PR link, popup and merge dialog (`PrLink`, `PrDialog`, `MergeDialog`, `mergeWarnings`) |
| `repopicker.js` | The one repo picker used by New run, Flow, Dispatch and the Board (`RepoPicker`) |
| `toast.js` | Fire-and-forget toast outside the Preact tree. A no-op without a document. |
| `usage.js` | Header plan-usage gauge per account (`UsageGauge`) |
| `vault.js` | No-repo work: folder chooser, Create repo, Publish to GitHub, new idea panel |

## Conventions

- **No build step.** Modules import each other by relative path (`./vendor/preact.mjs`). No `package.json` or `node_modules` (the test enforces this).
- **No hooks.** Hooks are not vendored. Views are `Component` classes, and stateless parts are plain functions. Templates use `const html = htm.bind(h)`.
- **Pure helpers are exported** next to each view (e.g. `parseRoute`, `filterColumns`, `itemActions`, `buildBody`), so `test_ui_static.py` can test them under node without a DOM. Modules must import without a `document`.
- **Polling, not sockets.** `poll(url, ms, onResult)` in `app.js` has an 8 s fetch timeout, never overlaps a request in flight, and pauses while the tab is hidden. Lists and pages poll every 3 s. A live transcript stream polls every 1 s with a byte `offset`.
- **Cross-view dialogs open by event:** `aiw:cleanup`, `aiw:peek`, `aiw:flow`, `aiw:afk`, `aiw:afk-back`. No props travel through the router.
- **HTML only through `mdToHtml`** (`run.js`). Every `dangerouslySetInnerHTML` must wrap `mdToHtml(...)`. Issue and PR bodies arrive as GitHub-rendered HTML.
- **No absolute URLs, no `console.log`, no `debugger`** in modules (`index.html` uses one `console.warn` for a failed service-worker registration).
- **Lenses and commands come from the server** (`/api/peer-review`, `/api/settings`). No lens is hardcoded.
- **`localStorage` is optional.** Use `loadPref`/`savePref` (or try/catch): it may be missing or throw. Keys are prefixed `aiw.` (e.g. `aiw.boardRepo`, `aiw.lastRepo`).
- **Mobile:** tap targets are at least 44px and no fixed width exceeds 390px. The test checks `app.css` for both.

## Testing

`run-engine/test_ui_static.py` is a plain assert script ([development.md](development.md)).

- It starts a real `ui_server._Server` on port 0 and checks static serving: content types, 404s and path escapes.
- It reads each module's source to check import allow-lists, hygiene and the vendored headers and exports.
- It runs the pure helpers under `node --input-type=module`, importing the real files by `file://` URL and asserting with `node:assert`. Views render through a small vnode walker (`norm`, `T`, `txt`), with no DOM.
- Node is optional. Without it, each node block prints `note: node not found, skipping ...` and passes.
- Views: `python3 test_ui_static.py --view <name>` runs one block (`shell`, `run`, `launcher`, `launcher-all`, `board`, `answer`, `notify`, `history`, `afk`). The plain run (what `run_tests.sh` and CI call) runs every view in a subprocess, plus the `flow.js` checks.
- When you add a module or view, add its pure helpers to a node block and its file to the import allow-list the tests check.
