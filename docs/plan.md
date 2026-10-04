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

- Runs as a scheduled job on GitHub Actions that starts, polls, posts, and exits. It is not an always-on process.
- Posts to Discord via channel webhooks, not a gateway bot account.

### Stack

- Python, managed with uv.

### New-posting detection

- Keep a persistent set of postings already seen, in a state file committed by the workflow to a dedicated `state` branch (kept separate from code).
- The workflow uses GitHub Actions `concurrency` so only one run executes at a time.
- Entries are removed 12 months after they were first seen, whether or not the listing is still open.
- **Identity key:** company + the source's job posting ID.
- **First poll of a board:** silently record its existing postings as seen; announce nothing. This applies to the bot's first run and to every board added to the approved list later, so stored state must track which boards have been polled.
- **Check order** for an incoming posting, most exact first:
  1. Identity key (company + source job posting ID).
  2. Normalized original job URL, which catches the same job from Simplify and from Greenhouse/Ashby.
  3. Normalized company + title + location, as a last resort.

### State file

- One JSON file, `state.json`, on the `state` branch. Timestamps are UTC ISO 8601 strings.
- **Posting records**, one per posting seen, each holding:
  - identity key (company + source job posting ID)
  - normalized URL
  - normalized `company`, `title`, `location` as separate fields
  - first-seen time
- **Boards section:** maps each board key (e.g. `greenhouse:stripe`, `ashby:<company>`, `simplify:faang`) to its first successful poll time. A board is marked only after a successful fetch. A board with no entry gets a silent first poll.

## Open questions

- How Simplify's data marks FAANG+ postings, and whether it includes the original job URL (unverified).
- How each posting is classified into a job type and a region.
- Message format and handling of Discord's webhook message-length and rate limits.
