---
name: release-note
description: Turn a merged release PR from any project into a business-friendly release note, either as a draft file for review or posted once to a Slack channel with @here first and a CC line last. Channel, CC people and the suffix default from setu's global release-note settings; the PR link and overrides are inputs.
argument-hint: "<pr-url> [channel:<name>] [cc:<name>,<name>,...] [--draft <file>]"
---

# Release note

Arguments are in `ARGUMENTS` below: `<pr-url>` (a URL, or `owner/repo#n`), optional
`channel:<name>`, optional `cc:<name>,<name>`, optional `--draft <file>`.

- **With `--draft <file>`:** write the note to that file and **post nothing**, anywhere. setu
  reviews the draft and posts it itself, exactly once. Your job ends at the file.
- **Without `--draft`:** write the note and post it, exactly once (Step 3).

## Inputs and defaults

Defaults are setu's global release-note settings, never hardcoded here. Read them once:

```bash
setu paths            # JSON; "home" is setu's data directory
```

then read `release_note` from `<home>/ui_settings.json` (a JSON file). It holds:

| Key | Meaning |
|---|---|
| `channel_name`, `channel_id` | the default Slack channel |
| `cc` | the default CC list, `[{name, slack_id}]` |
| `suffix` | the word written after each CC mention (empty = none) |

| Input | Required | Default |
|---|---|---|
| PR link | yes; ask if missing | none |
| Channel | no | `release_note.channel_name` / `channel_id` |
| CC people | no | `release_note.cc` |

A `channel:<name>` or `cc:<names>` argument (or the same said in plain words in the request)
**replaces** the default; it is not added to it. "no cc" means leave out the CC line. A name
matches an entry of `release_note.cc` case-insensitively and uses that entry's `slack_id`. The
default channel needs no lookup. For any other channel or person, look it up with the Slack
tools `slack_search_channels` (types `public_channel,private_channel`) or `slack_search_users`
when they exist in this session. If a name matches nobody or more than one, or no lookup tool is
available, ask the user (never guess): in a headless run that is `setu ask`. If the settings file
or its `release_note` key is missing and the arguments do not name a channel, ask the same way.

## 1. Read the PR

```bash
gh pr view <url> --json title,body,state,mergedAt,commits
```

- The PR body, especially its "What's in it" section, is the source. Leave out anything listed
  under "Held back".
- If the PR is not merged yet, say so and ask before going on (headless: `setu ask`).

## 2. Write the note

Audience: support and business people. Rules:
- **No technical details.** No class names, env vars, routes, queues, file names, commands or
  deploy steps.
- **No issue or PR references** (`#1234`).
- Group the changes into feature sections with an emoji header. Under each header, list short
  user-facing bullets about what changed and why it matters.
- Leave out internal-only changes such as dead-code removal and refactors.
- Name third-party gateways or providers when they help.

Template (Slack mrkdwn, not Markdown: `*bold*`, `•` bullets, no `##`):

```
<!here>
*🚀 Release Note - <D Month YYYY of merge>*

<one-line summary of the release>

*<emoji> <Feature area>*
• <user-facing change>
• ...

CC: <@ID1> <suffix>, <@ID2> <suffix>
```

`<!here>` always goes first. The CC line always goes last, with the suffix after each name
(omit the suffix and its space when the setting is empty). The date is the PR's merge date.

Write the text to the draft file (`--draft`), or to a temp file in the scratchpad or a temp
directory otherwise. Then, **with `--draft`, stop here**: print the path and a one-line
summary of the sections, and say what was held back. Do not run `slackcli`.

## 3. Post it (only without `--draft`)

Post it as a **new message**. Slack doesn't notify @here or @mentions that are added by
editing a message, so mentions must be in the first post.

```bash
slackcli messages send --recipient-id <channel-id> --message-file <file> --json
```

**Send exactly once. Never retry a send.** Run the send command bare: no `| jq`, `| tail` or
`|| true`, which can swallow its output. Even with empty or odd output, assume it posted. To
check, read the channel with `slackcli conversations read <channel-id> --limit 3`; it lists
messages **oldest first**, so the newest is at the bottom. If the note isn't there, ask the user
before sending again. A second send posts a duplicate that pings @here twice, and that cannot be
undone.

If a note needs fixing after it's posted, use
`slackcli messages edit --permalink <link> --message-file <file>`, and tell the user the edit
won't notify anyone again.

## 4. Report

Give the user the message link, the channel, who was CC'd, and a one-line summary of the
sections. If anything was held back, say so.
