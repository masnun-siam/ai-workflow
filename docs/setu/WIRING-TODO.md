# Follow-ups for the wiring task (O)

- release: auto-start the grind after a successful cut (the approved flow is cut → grind automatically); fill `prs_waiting` (PRs merged to the head branch since the last release, from poller/gh).
- release: adapter for grind.Service (`Get(repo, pr)`, `StartGrind(ctx, repo, pr, by)`).
- sessions: adapters for settings (`AccountCmd/DefaultCmd/LabelFor/CheckRun/RunDefaults/VaultDir`), prompts, products, notify; implement `pin_account` routing.
- products: Deps.ScanRoots (settings), Deps.Merged (poller).
- gh/poller: wire `Commands()`, `Routes(Deps)`, `Poller.Start`, injected Repoll/OpenChildren/ProductRepos.
- away: notify.SetAway(away.Active); pass dispatch adapter implementing away.Lanes{Stuck, Retry}.
