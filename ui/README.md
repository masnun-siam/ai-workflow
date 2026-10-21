# aiw ui (React + TypeScript + Vite)

- Dev: `npm ci && npm run dev` (proxies `/api` to the aiw server on 127.0.0.1:8420; start it with `aiw ui`).
- Test: `npm run typecheck && npm test`.
- Build: `npm run build` writes to `../run-engine/ui_dist/` (hashed assets, no timestamps).
- `run-engine/ui_dist/` is committed so plugin users never need Node; CI fails if it is stale, so rebuild before you commit.
- Screens live in `src/pages/`, panels in `src/panels/`, the Start dialog in `src/start/`; shared pieces in `src/components/`, `src/api/`, `src/lib/`.
