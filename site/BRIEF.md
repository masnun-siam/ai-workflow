# Showcase site brief

Replaces the old "Field Guide" at masnun-siam.github.io/ai-workflow.

- Audience: hiring managers/recruiters and social/launch traffic. Needs a 10-second hook.
- Look: dark, cinematic (Linear/Vercel style), big product video hero.
- Stack: Vite + React + TS in `site/`, reusing `ui/` where it helps. Deployed by a GitHub Actions Pages workflow.
- Sections: hero video + tagline, animated pipeline (each stage with a real artifact), aiw UI tour, proof/stats + todoman case study.
- UI tour must show: board/epics overview, live session view, peer-review panel, dispatch + CI/merge gate.
- Media: real screenshots, MP4/WebM loops (compressed, in repo, <~3MB each), code-driven animations. Sped-up recordings with captions (ffmpeg). Plus a 30-60s promo clip to post.
- Story: a fresh todoman run of the full pipeline for one feature, "dump result card" (after a dump is processed, post one comment with a table of created tasks/meetings/tracking issues, links and labels). Run stops at a reviewed, green, ready PR; no merge.
- Recording: automated (headless browser), full real sessions OK.
- Redact: personal todo data (masnun-siam/todo), emails/invitees, work repos/company names.
- CTA: star / view on GitHub. Branding: subtle footer credit only.
- Copy: drafted by Claude, reviewed by the owner.
- Checkpoint: owner reviews the built site on a preview before it is published.
