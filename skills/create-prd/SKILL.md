---
name: create-prd
description: Turn a feature idea into a product requirements document, with its technical design, every decision settled by interviewing the user, and on approval one GitHub epic per PRD. Use when asked to write, draft, update or approve a PRD, or to spec a feature before it is broken into tasks and issues.
---

# Create a PRD

Produces the source of truth for a feature: what it does, why, and how it is built. Every issue is derived from it, so a question left open here comes back in the middle of implementation and can change issues that are already in progress. The aim is a PRD that leaves nothing to ask.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings" for the base branch and which guides and templates win, the PRDs section, and "GitHub: project, epics and dependencies"), the template `../../templates/prd.md`, and the repo's docs for the areas the feature touches.

## Steps

1. **Restate the request** in one or two sentences and confirm you have the source material: a design, a BRD, a customer request, an earlier discussion. Ask for what is missing. If `docs/prds/<slug>.md` already exists, you are updating it: read it first and go to "Changing an approved PRD" when its status is `Approved`.

2. **Ground it in the codebase.** Find what exists today that the feature touches: models, endpoints, pages, jobs, realtime channels, and any other service in the repo that reads or writes the same data. Use GitNexus or another code-graph tool when its index is available, otherwise read the code. This reading is what makes your questions and recommendations sound; it is not copied into the PRD. Find the closest existing feature that sets the pattern. When the request names an existing feature to match, record how that feature actually behaves and what it lets users configure, and ask once whether to mirror it exactly before asking about any extras the request lists. Check for overlap with existing PRDs (`docs/prds/`, the repo wiki) and open issues.

3. **Interview the user until nothing is open.** Use `AskUserQuestion` for every decision the code and the source material do not already settle. Do not decide quietly on the user's behalf.
   - Every question puts the recommended option first, labelled as recommended, and its description says why you recommend it: the precedent in the code, the cost, the risk. The other options say what they would cost. The team should be able to choose in seconds.
   - Research before asking, so the options are concrete and the recommendation is grounded in this codebase. Never ask what the repository can answer.
   - For visual or layout decisions, give each option an ASCII mockup in the `AskUserQuestion` preview, so the user compares pictures, not adjectives.
   - Cover the product: who uses it and which roles may do what; visibility (per user, per tenant or account, admin); limits and validation rules; what is out for this version; billing or cost impact; whether other users must see changes live; rollout (everyone at once, or gated); priority; how many epics (one unless the user wants more).
   - Cover the technical design too, since it lives in this PRD: which store and the shape of the data, the API contract, sync or queued, realtime events, changes to other services, migration of existing data, and how each requirement is tested.
   - Ask in short rounds, related questions together, and let each round's answers shape the next. Stop only when you can fill every section of the template with no open question.

4. **Write the PRD** from the template, in plain language.
   - Requirements are numbered `FR-n`, each with an acceptance line that someone could test. They describe behaviour.
   - "Technical design" records the decisions about how each requirement is built, names the `FR-n` it serves, and follows the repo's docs. The API contract is exact enough for the frontend to be built against it before the backend is merged.
   - **Decisions, not code.** Keep the PRD at the level of contracts and behaviour: data shape, endpoints and their fields, what each part is responsible for, how it behaves under concurrency and failure. Leave out file paths, class and method names, signatures, step-by-step logic, query keys, styling classes, test file names and line numbers. They are noise to a reviewer, go stale as the base branch moves, and are worked out by `/refine-issues` against the current code. Describe existing code by what it does ("notes are capped at 12 per conversation"), not by where it lives.
   - **Use diagrams.** The team reads and discusses a PRD more easily with pictures beside the text. Add a Mermaid diagram wherever one is clearer than prose, and always for a big feature: a flowchart for a user flow, a sequence diagram for an exchange between parts or a race between two requests, a state diagram for a lifecycle, an entity diagram for the data. Place each next to the text it supports with a one-line caption. A diagram never replaces a requirement or its acceptance line, and a small change needs none.
   - Every answer from the interview goes under "Decisions" with its reason.
   - "Edge cases" always covers concurrency, empty states, limits reached and existing data, and data isolation when the project is multi-tenant or holds per-user data.
   - Non-goals are specific enough that nobody builds them by accident.
   - "Epics" lists one epic unless the user asked for more, each with the `FR-n` it covers.

5. **Check it before showing it.**
   - Could a tester write a test from each acceptance line alone?
   - Could an engineer start any part of the technical design without asking a question? If not, go back to step 3.
   - Is "Open questions" empty? If an answer needs someone who is not in the session, leave the question there with that person's name and keep the status `Draft`.
   - Is every codebase claim backed by a path you opened in this session?
   - Does it name a file, class, method or line number, or spell out logic step by step? Take it out unless the name is part of a contract (an endpoint, a field, a table or collection, a command operations must run).
   - Is there a flow, lifecycle, data model or race that takes a paragraph to explain? Give it a diagram, and check each diagram agrees with the text beside it.
   - Where data isolation applies, is it stated, not assumed?
   - Does anything contradict a rule in the repo's `CLAUDE.md` or `AGENTS.md` or a convention in its docs?

6. **Save it** as `docs/prds/<slug>.md` (or where the repo's `CLAUDE.md` or `AGENTS.md` says PRDs live) with status `Draft`, where `<slug>` is short kebab-case (for example `conversation-tags`). Show the user the path, the decisions made, and anything still open. Do not commit, push or publish it unless the user asks; when they do, the team reviews it in a pull request into the base branch and the status becomes `In review`.

7. **Approve it, when the user says the team has reviewed it.** Approval is the user's call, never yours.
   - Refuse while "Open questions" has an entry; resolve those first.
   - Fold in the review's changes, then set the status to `Approved`.
   - Draft one epic issue per entry under "Epics" from `../../templates/epic.md`, and find the GitHub project by the rule in the guide.
   - Show the user each epic's title, labels and project, and ask with `AskUserQuestion` whether to create them. Create nothing without an explicit yes.
   - Create them with `gh issue create`, then write each number into the PRD's "Epics" section.

8. **Hand off.** State the next stage: `/create-tasks` splits the PRD into parallel tasks and creates them as sub-issues of the epic with their dependencies, then `/refine-issues` fills each one. Do not start it unless asked.

## Changing an approved PRD

A decision that changes after approval is changed here first, never only in an issue or a pull request. Update the affected sections, add a "Change log" line with the date, the reason and the issues affected, then tell the user which issues must be updated to match. Ask before editing any issue.

## Stop and ask when

- The request is a solution with no stated problem.
- Two requirements conflict, or one conflicts with a data-isolation, security or billing rule.
- The feature needs something the product does not have at all (a new provider, a new role, a new data store).
- The technical design needs a new dependency or a pattern the repo's docs do not describe.

## Improve this skill

Each use of this skill is also a test of it. Full rules: `../../guides/skills.md`.

- **While working**, note privately any step here that was wrong, outdated, missing, unclear or unnecessary, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person in any repository. Facts about one codebase go to its `tasks/lessons.md` or docs, not here.
- **If anything is left**, tell the user what happened and propose the exact edit to this file with `AskUserQuestion`, recommended option first. If nothing is left, say nothing.
- **On approval**, apply the edit in the plugin's source repository as `../../guides/skills.md` describes, keep the file short and free of code samples, and commit it on its own as `chore: update /create-prd skill - <what changed>`.
- **Never** edit this file without approval, and never use an edit to weaken a gate or contradict a repo's `CLAUDE.md` or `AGENTS.md`.
