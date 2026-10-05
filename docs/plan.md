# Plan

A scheduled job that finds new internship postings and announces them in Discord channels.

## Requirements

- Poll sources every 20 minutes. The goal is to surface new postings as soon as possible.
- Announce only postings not announced before.
- One Discord channel per job type: SWE, data/ML, hardware/firmware, quant, other engineering, product.
- Within each message, group postings under region headers.

## Decisions

### Sources

- **Company sources (primary):** poll the company boards on a manually maintained approved list. Greenhouse, Ashby, Lever, and SmartRecruiters are built. More platforms come later, most reliable first:
  1. ~~Lever, SmartRecruiters~~ (done)
  2. Workday
  3. Amazon, Eightfold
  4. Apple
  5. Google (HTML), Meta (rotating GraphQL), custom sites
  6. Microsoft, which blocks datacenter IPs, so it needs the Raspberry Pi host
- **Simplify (slower fallback):** take postings from companies on the manually maintained FAANG+ list. Simplify lags company boards by hours, so it only catches what direct sources can't fetch yet. The duplicate check skips its copies of postings already seen directly.
- **Build order:** get the core pipeline working end to end with Greenhouse, Ashby, and Simplify before adding platforms.

- No filtering by internship term. The silent first poll keeps existing old-term postings from being announced.

### Runtime and Discord

- Runs as a scheduled job on GitHub Actions that starts, polls, posts, and exits. It is not an always-on process.
- cron-job.org supplies the schedule and dispatches the GitHub workflow every 20 minutes. GitHub's built-in cron created no scheduled runs even after disabling and re-enabling the workflow; the external scheduler replaces that trigger.
- "As soon as possible" means within about an hour. After deploying, check the real gaps between scheduled runs in the Actions history.
- Planned later move: a Raspberry Pi on a home connection, to reach Microsoft and get exact timing. The Python program only reads and writes a local `state.json`, so the move changes only what runs it, not the code.
- Posts to Discord via channel webhooks, not a gateway bot account.
- The channels are announcement channels, so other servers can **Follow** them. Webhook messages reach followers only after they're published, and publishing is currently done by hand. Discord allows 10 publishes per hour per announcement channel.

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
- **Boards section:** maps each board key (e.g. `greenhouse:stripe`, `ashby:<company>`, `simplify:<company>`) to its first successful poll time. A board is marked only after a successful fetch. A board with no entry gets a silent first poll.
- Each FAANG+ company counts as its own Simplify board (`simplify:<normalized company name>`). A company newly added to `faang_plus` gets a silent first poll, so its existing listings are never announced. A successful Simplify fetch marks every company on the list as polled, even companies with no postings.

### Classification

- **Channels:** SWE, data/ML, hardware/firmware, quant, other engineering, product. There is no catch-all channel. A posting matching no channel is ignored, and a posting matching several goes to every matching channel.
- **Simplify job type:** from Simplify's `category`:
  - `Software` / `Software Engineering` → SWE
  - `AI/ML/Data` / `Data Science, AI & Machine Learning` → data/ML
  - `Hardware` / `Hardware Engineering` → hardware/firmware
  - `Quant` / `Quantitative Finance` → quant
  - `Product` / `Product Management` → product
- **Greenhouse/Ashby job type:** case-insensitive keyword match on the title. Short keywords match on word boundaries. Starting keyword lists:
  - **SWE:** software, swe, sde, developer, backend, frontend, full stack, mobile, ios, android, infrastructure, devops, sre, security engineer
  - **data/ML:** machine learning, ml, ai, data science, data scientist, data engineer, data analyst, data analytics, research scientist
  - **hardware/firmware:** hardware, firmware, embedded, electrical, asic, fpga, rtl, chip, silicon, pcb, rf
  - **quant:** quant, quantitative, trading, trader
  - **other engineering:** mechanical, civil, chemical, aerospace, manufacturing, industrial, materials, test engineer, quality
  - **product:** product manager, product management, apm, product design
- **Intern detection:**
  - Ashby: `employmentType == "Intern"`.
  - Lever and SmartRecruiters: the platform's label (Lever `commitment`, SmartRecruiters `typeOfEmployment`) **or** the title matches the intern regex. Labels vary by company, and some internships are labelled "Full-time". Word boundaries keep out labels like "International Office Entity".
  - Greenhouse: title matches `\b(intern|internship|co-op|coop)s?\b`, case-insensitive.
  - All sources: titles containing "high school" are excluded.
- **Undergrad only:**
  - Simplify postings are kept if `degrees` is empty or includes `Bachelor's` or `Associate's`.
  - On all sources, a title naming a graduate degree or graduate students (PhD, MS, MSc, Master's, MBA, Doctoral, Graduate, Grad) is excluded unless it also names BS, BSc, Bachelor's, or Undergrad. "Undergraduate" does not count as "Graduate".
- **Regions:** Canada, US, UK, Europe, Remote, parsed with a lookup table: country names, US states and abbreviations, Canadian provinces, major cities and city abbreviations (`NYC`, `SF`), European countries.
  - Two-letter codes after a comma are US states or Canadian provinces. A `CA` that follows a province code (`Toronto, ON, CA`) is Canada's country code, not California.
  - Plain `Remote` goes under Remote. Remote-in-a-country (e.g. `Remote (US)`) goes under Remote only if that country is in one of the listed regions, so `Remote (India)` is dropped.
  - A posting spanning several regions appears under each.
  - Locations outside these regions, or not recognized, are dropped.
  - **Vague locations** (`Multiple Locations`, `Various Locations`, `In-Office`, `Flexible - Any … Site`, `BLANK`, `TBD`, empty): if none of the posting's other locations is recognized, the title is checked for a place (e.g. "… - Austin, TX"). If the title doesn't name one either, the posting goes under a last header, "📍 Location not specified".
- **Ignored and dropped postings** (no channel match or no region) are **not** recorded as seen, so they are announced once a rule later matches them.
- Unrecognized location strings are printed in the workflow log.

### Discord messages

- Plain-text Markdown (no embeds), one batch per job-type channel per run.
- Postings are grouped under region headers in the order US, Canada, Europe, UK, Remote. Empty regions are skipped.
- **Posting format:** `**Company** — [Title](<url>)`, then a line with the locations and the source's posted date (e.g. `Seattle, WA · NYC · Oct 4`). The `<…>` around the URL suppresses link previews.
- A posting in several regions shows its full location list under each region header.
- Within a region, newest posted date first.
- If a batch exceeds Discord's 2,000-character limit, split after the last posting that fits. Region headers are not repeated in continuation messages.
- On HTTP `429`, wait the time Discord specifies and retry the same message.
- A posting is recorded as seen only after the message where it first appears is posted successfully. State is saved after each message.
- Long location lists show the first 3 and then `+N more`.
- A blank line separates postings. Every message ends with a newline plus a zero-width space, because Discord trims trailing whitespace; that leaves a visible gap between consecutive messages.
- Markdown characters in company names and titles are escaped.
- Messages are sent with `allowed_mentions: {"parse": []}`, so nothing can ping.

### Config

- `config.toml` at the repo root holds:
  - `simplify_url`: the listings URL, which changes each hiring cycle.
  - `faang_plus`: lowercase company names, matched case-insensitively against Simplify's `company_name`. Seeded from Simplify's current list.
  - `[[boards]]` entries, each with `source` (`greenhouse` or `ashby`), `slug` (the board ID in the API URL), and `name` (display name, also used as the company name for dedup).
- Webhook URLs are GitHub repository secrets, one per channel: `WEBHOOK_SWE`, `WEBHOOK_DATA_ML`, `WEBHOOK_HARDWARE`, `WEBHOOK_QUANT`, `WEBHOOK_OTHER_ENG`, `WEBHOOK_PRODUCT`. The workflow passes them to the program as environment variables.
- If any webhook secret is missing, the run exits with an error naming it, before fetching anything.

### Workflow

- `.github/workflows/poll.yml` is triggered by `workflow_dispatch`, from cron-job.org every 20 minutes (`7,27,47 * * * *`) or manually. It has no built-in GitHub cron trigger.
- cron-job.org uses a fine-grained GitHub personal access token restricted to this repository with Actions write permission. The token is stored in cron-job.org's Authorization header; it is not a repository secret. Replace it there before its chosen expiration date.
- A successful scheduler request confirms dispatch was accepted, not that polling and posting completed. Check the GitHub run result as well as the scheduler history.
- If checking for the `state` branch fails for any reason other than "branch doesn't exist", the run fails instead of starting with empty state.
- The state commit sets its author per command (`git -c`) and never changes global git config.
- `.github/workflows/test.yml` runs the tests on pushes to `main` and on pull requests.
- `permissions: contents: write`, one `concurrency` group with `cancel-in-progress: false`, and `timeout-minutes: 10`.
- **Steps:**
  1. Check out `main`.
  2. Set up uv.
  3. Load state: fetch the `state` branch. If it exists, copy its `state.json` into place; if not (first run), start with empty state. Empty state means every board gets a silent first poll.
  4. Run the program with the `WEBHOOK_*` secrets as environment variables.
  5. Commit `state.json` to the `state` branch as `github-actions[bot]`, only if it changed. The first run creates `state` as a branch with no shared history. This step runs even if the program failed.
- The program writes `state.json` after each channel's messages are posted, so a crash partway through doesn't cause re-announcements.
- **Risk:** cron-job.org can delay requests and GitHub can queue dispatched jobs; neither guarantees exact timing. Scheduler notifications cover failed HTTP requests, not failures inside the GitHub job.

### Running

- `uv run python -m intern_alerts` runs one poll. `--dry-run` prints messages instead of sending them and doesn't save state; webhook secrets aren't needed for it.
- `STATE_PATH` sets the state file location. The default is `state.json`.
- `--backfill DAYS` is a one-off: it starts from empty state, sends every open posting published in the last `DAYS` days instead of recording them silently, and saves nothing.
- Company boards are fetched before Simplify, so a new job seen in both is announced from the direct source.
- A board that fails to fetch logs a warning and isn't marked polled. A failed Discord message logs an error, stops that channel, and makes the run exit with code 1. Its postings stay unrecorded and retry next run.

### Code structure

- `main.py`: runs the steps in order; holds no logic of its own.
- `config.py`: loads `config.toml` and webhook env vars, and fails fast on a missing secret.
- `models.py`: the shared `Posting` shape every source returns.
- `sources/`: one module per source (`simplify.py`, `greenhouse.py`, `ashby.py`), each returning `Posting`s.
- `classify.py`: intern detection, job type, region.
- `dedup.py`: checks postings against state (ID → URL → company + title + location).
- `normalize.py`: URL and company/title/location normalization, shared by dedup and state.
- `state.py`: load, save, and prune `state.json`, and track polled boards.
- `format.py`: builds channel messages with region headers and the 2,000-character split.
- `post.py`: sends messages to webhooks and handles `429`.

## Source facts (checked 2026-10-04)

- **Simplify:** `https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json`, one JSON array (~16.9k entries, ~4.4k with `active` and `is_visible` true). Fields include `id` (UUID), `company_name`, `title`, `url` (original application URL), `locations` (list of strings, often abbreviated like `NYC`, `SF`), `category` (mostly `Software`, `AI/ML/Data`, `Hardware`, `Product`, `Quant`), `terms`, `active`, `is_visible`, `date_posted`, `date_updated` (Unix seconds). The repo name changes each hiring cycle.
- **Simplify FAANG+:** not a field in the data. Simplify's README generator marks a listing 🔥 when `company_name.lower()` is in a hardcoded `FAANG_PLUS` set in `list_updater/constants.py`.
- **Greenhouse:** `https://boards-api.greenhouse.io/v1/boards/<board>/jobs` (`?content=true` adds descriptions). Fields include `id`, `title`, `location.name` (one free-text string), `absolute_url`, `departments`, `offices`, `first_published`, `updated_at`. No employment-type field, so interns must be found by title. `absolute_url` may be on the company's own domain with the job ID in a query parameter (e.g. `https://stripe.com/jobs/search?gh_jid=8194291`), and Simplify uses the same URL, so URL normalization must keep such parameters.
- **Simplify latency:** `listings.json` is committed about every 30 minutes (gaps up to 5 hours observed). For 8 Stripe internships on both Simplify and Greenhouse, Simplify's `date_posted` was 6.7–10.9 hours after Greenhouse's `first_published` (median ~7 hours).
- **Ashby:** `https://api.ashbyhq.com/posting-api/job-board/<board>`. Fields include `id` (UUID), `title`, `department`, `team`, `employmentType` (e.g. `Intern`), `location`, `secondaryLocations`, structured `address.postalAddress` (country/region/locality), `isRemote`, `workplaceType`, `jobUrl`, `publishedAt`.

- **Lever:** `https://api.lever.co/v0/postings/<slug>?mode=json` returns every posting in one list. It has `text` (title), `categories.commitment` (a free-text label per company), `categories.location` / `allLocations`, `workplaceType`, `hostedUrl`, and `createdAt` (milliseconds).
- **SmartRecruiters:** `https://api.smartrecruiters.com/v1/companies/<slug>/postings?limit=100&offset=N` is paged (max 100 per page, with `totalFound`). The slug is case-sensitive. It has `name`, `typeOfEmployment.label`, `location.fullLocation` / `remote`, and `releasedDate`. The list has no job URL, so it's built as `https://jobs.smartrecruiters.com/<slug>/<id>`, the same form Simplify uses. All pages are fetched, capped at 50.

## Open questions

- When Workday is added: check that Simplify's Workday URLs normalize to the same value as fetched ones.
