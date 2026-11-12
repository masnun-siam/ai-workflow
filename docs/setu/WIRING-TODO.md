# Follow-ups for the wiring task (O)

- release: auto-start the grind after a successful cut (the approved flow is cut → grind automatically); fill `prs_waiting` (PRs merged to the head branch since the last release, from poller/gh).
- release: adapter for grind.Service (`Get(repo, pr)`, `StartGrind(ctx, repo, pr, by)`).
- sessions: adapters for settings (`AccountCmd/DefaultCmd/LabelFor/CheckRun/RunDefaults/VaultDir`), prompts, products, notify; implement `pin_account` routing.
- products: Deps.ScanRoots (settings), Deps.Merged (poller).
- gh/poller: wire `Commands()`, `Routes(Deps)`, `Poller.Start`, injected Repoll/OpenChildren/ProductRepos.
- away: notify.SetAway(away.Active); pass dispatch adapter implementing away.Lanes{Stuck, Retry}.
- review: Routes/Start/Commands; sessions.Deps.PanelState = review.Service.State. Check peer-reviewer.md's verdict format matches the parser (`**Verdict:** approve` parses as changes).
- web: Go registry JSON tags must be id, source, skill, runs_in, stage, args_hint, command, available, reason. NotifySettings needs ntfy fields (server, topic, token_set, ntfy_ready) for the Settings form. Push subscribe in the browser (P4-P).
- inbox/views: adapt dispatch/release/away/grind/review via inbox.Convert[T]; dispatch public view needs seen_done; provide cleanup Flags(repo); share one Builder.
