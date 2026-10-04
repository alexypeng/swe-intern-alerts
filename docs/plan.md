# Plan

A scheduled job that finds new internship postings and announces them in Discord channels.

## Requirements

- Poll sources roughly every 15 minutes. The goal is to surface new postings as soon as possible.
- Announce only postings not announced before.
- One Discord channel per job type (e.g. SWE, data/ML, firmware/electrical).
- Within each message, group postings under region headers.

## Decisions

### Sources

- **Ashby and Greenhouse:** poll only the company boards on a manually maintained approved list.
- **Simplify:** take only postings labelled FAANG+. These are not filtered by the approved list.

### Runtime and Discord

- Runs as a scheduled job that starts, polls, posts, and exits. It is not an always-on process.
- Posts to Discord via channel webhooks, not a gateway bot account.

### New-posting detection

- Keep a persistent set of postings already seen.
- **Identity key:** company + the source's job posting ID.
- **First poll of a board:** silently record its existing postings as seen; announce nothing. This applies to the bot's first run and to every board added to the approved list later, so stored state must track which boards have been polled.
- **Cross-source duplicates** (the same job from Simplify and from Greenhouse/Ashby):
  - Main check: compare the original job URL, normalized (or the job ID extracted from it).
  - Fallback when no URL is available: compare normalized company + title + location.

## Open questions

- Language/stack.
- Scheduler platform, and where the seen set and polled-boards state are stored (must persist between runs).
- How Simplify's data marks FAANG+ postings, and whether it includes the original job URL (unverified).
- How each posting is classified into a job type and a region.
- Message format and handling of Discord's webhook message-length and rate limits.
