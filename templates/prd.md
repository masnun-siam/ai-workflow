# PRD — <Feature name>

**Status:** Draft · **Date:** YYYY-MM-DD · **Slug:** `<feature-slug>` · **Owner:** <name> · **Priority:** <critical, high, medium or low> · **Repo:** <owner/repo>

Status is `Draft`, `In review` or `Approved`. This document is the source of truth for the feature: every issue is derived from it, and a decision that is not written here has not been made.

Diagrams (writer note, delete before saving): use a diagram wherever it makes a part easier to read or discuss than text alone, and always for a big feature. Draw them in Mermaid code blocks so they render on GitHub and are reviewed as text. Useful kinds: a flowchart for a user flow or a decision, a sequence diagram for an exchange between user, frontend, API and other services or for a race between two requests, a state diagram for a lifecycle, an entity diagram for the data model. Put each one next to the text it supports, with a one-line caption saying what it shows. A diagram adds to the text and never replaces a requirement or its acceptance line. A small change needs none.

## Overview

Two or three sentences a non-engineer can follow: what the feature is and who uses it. Link the design if there is one.

Today:
- What the product already does in this area, named the way a user or engineer would say it, not as file paths.
- The closest existing feature, which sets the pattern to follow.
- What does not exist yet.

## Problem

What users cannot do today and what that costs them.

## Users

Which roles and in which part of the product.

## Goals

- Outcomes, stated from the user's side.

## Non-goals

- What this version deliberately leaves out, so nobody builds it by accident.

## Requirements

- **FR-1 <Short name>.** The behaviour, including limits and validation rules.
  - Acceptance: an observable result someone could test.
- **FR-2 <Short name>.** ...
  - Acceptance: ...

## Edge cases

- Concurrency, empty states, limits reached, deleted or missing data.
- Data isolation, if the project is multi-tenant or has per-user data: what must never be visible to or counted for another tenant or user.
- Existing data: whether anything needs migrating.

## Technical design

The decisions about how the requirements are built: the ones that are costly to change later, or that two engineers must agree on before they can work apart. Name the `FR-n` each part serves. Write "Not affected" under a heading the feature does not touch.

Keep it at the level of contracts and behaviour. Names that are part of a contract belong here: endpoints, request and response fields, tables or collections and their fields, events, commands operations must run. File paths, class and method names, function signatures, step-by-step logic, query keys, styling classes, test file names and line numbers do not; they are worked out against the current code when the issues are written, and would be stale here by then.

### Data

Which store, the tables or collections, their fields and types, indexes, ownership scoping, and the migration or backfill for existing data.

### API

Each endpoint: method and path, who may call it, request fields with validation rules, the response shape, and the error cases. This is the contract the frontend builds against.

### Backend

The moving parts that are added or changed and what each is responsible for (for example "an hourly cleanup that deletes tags unused for 72 hours"), and how each behaves under concurrency and failure.

### Frontend

The screens and components that are added or changed, what each shows and does, and its loading, empty and error states.

### Realtime and other services

Events that are broadcast and who receives them, and whether any other service in the system reads or writes the same data.

### Non-functional

Performance, security and compatibility limits that apply.

### Testing

Which kind of test (API, unit, component, end to end, manual) proves which requirement, and anything that cannot be tested automatically.

## Rollout and cost

Everyone at once or gated, billing or third-party cost impact, and anything operations must do before or after release.

## Success metrics

How we will know it worked. Write "None formally defined" if that is the truth.

## Epics

One epic unless the team asked for more. The issue number is filled in when the PRD is approved.

- **E1 <Epic title>** — covers FR-1 to FR-n. Issue: —

## Decisions

- <Decision> — <the reason>. Product and technical decisions both go here.

## Open questions

- <Question> — <who can answer it>.

This list must be empty before the status becomes `Approved`. Every answer moves to "Decisions".

## Change log

- YYYY-MM-DD — <what changed after approval, why, and which issues were updated>.

## Related

- Design, BRD, earlier PRDs and issues.
