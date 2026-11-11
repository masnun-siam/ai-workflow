# Rules for every setu build task

1. Read `docs/setu/ARCHITECTURE.md` and `docs/setu/API.md` fully, then the engine spec sections your task names (`docs/setu/engine/*.md`). API.md is the contract; ARCHITECTURE.md decisions win over it.
2. Own only the packages/dirs your task lists. Do not edit other packages. `cmd/setu/main.go` is edited only by the P0 and wiring tasks. If you need something from a package that does not exist yet, code against the API.md §2 signature and, if you must, add a minimal stub in that package marked `// STUB(owner-task)` and say so in your report.
3. Go: std lib only (the one exception listed in API.md §1). `gofmt`, `go vet ./...` clean. Tests: `go test ./internal/<yours>/...` green, table tests, fake binaries via `internal/testutil/fakebin`, `t.Setenv("HOME", t.TempDir())` and `SETU_HOME`. Never touch the network or the real home dir in tests.
4. Web: Preact + @preact/signals + Vite + TypeScript in `web/`. `npm run typecheck`, `npm test` green. Exact dependency versions, nothing that is not needed.
5. Resource budget matters: no busy loops, no unbounded buffers, stream large files.
6. When API.md is ambiguous or wrong, decide, and append one line to `docs/setu/DECISIONS.md`: `- [<task>] <decision> — <why>`.
7. Do not commit, push, or touch git state. Do not run `make install` or touch launchd unless your task says so.
8. Final reply ≤150 words: what is done, test results (counts), deviations from API.md, anything left undone.
