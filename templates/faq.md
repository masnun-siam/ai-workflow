<!-- Template for a product's docs/faq.md, filled by /faq-updater. A repo's own docs/templates/faq.md overrides it.
     Writer notes like this one are HTML comments, so readers of the site never see them. Keep the file's parts in this order. -->
<!-- Whoever edits `skill` text by hand switches its `Source:` to `team`. A run never edits the source-language text of anything marked `team`. -->

# <Product> help guide

Synced to: <commit sha> (<YYYY-MM-DD>)
Languages: <codes>
Videos from: <url>

<!-- Languages: ISO 639-1 codes, optionally with a region such as pt-BR, separated by commas. The first code is the source language.
     Videos from: a YouTube playlist or channel URL; may be empty. -->

## Index

| ID | Question | Section | Source |
|---|---|---|---|
| <section-slug>-<n> | <question in the source language> | [<section title>](#<section-id>) | skill |

<!-- One row per question. Source is `skill` or `team`. -->

## Retired IDs

<!-- A single line of every retired section and question ID. An ID on it counts as used. -->
<id>, <id>

## Rejected videos

<!-- A single line of YouTube video IDs that must never be proposed again. -->
<video id>, <video id>

## Questions to answer

<!-- The team appends one question per bullet. A run answers each, files it in a section and removes the bullet. -->
- <question>

## Needs an answer from the team

<!-- One bullet per question the code can't answer, wording unchanged. The team writes the answer as indented text under it; the next run files it in a section as `team`. -->
- <question>
  <the team's answer, once written>

---

<!-- IDs: a section's ID is <section-slug>; a question's ID is <section-slug>-<n>, <n> the next unused number for that slug (retired IDs count as used).
     A sub-section's ID is <section-slug>-<name> with a non-numeric name. An ID never changes once given. -->
<!-- Section shape: `#` panel, `##` top-level menu area, `###` feature, `####` sub-section when a feature is split. Each heading carries its anchor.
     Parts in order; leave out any with nothing to say, except the title and the summary: videos, summary, "In this section", menu path, numbered steps, field tables, limits, screenshots, FAQ.
     Put a `Source: skill|team` line after each guide passage. -->

# <Panel title> <a id="<panel-id>"></a>

## <Menu area title> <a id="<area-id>"></a>

### <Feature title> <a id="<section-id>"></a>
<!-- covers: <paths> -->

Videos:
- [<video title>](<video url>)

<One-paragraph summary in everyday words.>
Source: skill

In this section:
- [<Sub-section title>](#<section-id>-<name>)

Menu path: **<Menu>** > **<Item>**

1. <Step, with the UI's labels in bold.>
2. <Step.>

| Field | What it does |
|---|---|
| **<Field>** | <Description.> |

Limits: <limits, if any.>

![<what the screenshot shows>](faq-images/<section-id>-1.png)

#### <Sub-section title> <a id="<section-id>-<name>"></a>
<!-- covers: <paths> -->

<Summary and guide passage.>
Source: skill

<!-- FAQ entry: a heading one level below its parent (`####` under a feature, `#####` under a sub-section).
     `Source:` takes an optional per-language form, e.g. `Source: skill; bn: team`.
     One block per language, in the order of `Languages`. The heading holds the source-language text; every block starts with its language name in bold;
     non-source blocks then give the title or question in their language. Keep a blank line inside each edge of a `div` so Markdown renders. -->

#### <Question in the source language> <a id="<section-slug>-<n>"></a>
Source: skill

<div lang="<source code>">

**<Source language name>**

<Answer that stands alone for a new user.>

</div>

<div lang="<other code>">

**<Language name>**

<Question in this language>

<Answer in this language.>

</div>

##### <Question in the source language> <a id="<section-id>-<name>-<n>"></a>
Source: skill

<div lang="<source code>">

**<Source language name>**

<Answer.>

</div>
