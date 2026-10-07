# Plan

A scheduled job that finds new internship postings and announces them in Discord channels.

## Requirements

- Poll sources every 20 minutes. The goal is to surface new postings as soon as possible.
- Announce only postings not announced before.
- One Discord channel per job type: SWE, data/ML, hardware/firmware, quant, other engineering, product.
- Within each message, group postings under region headers.

## Decisions

### Sources

- **Company sources (primary):** poll the company boards on a manually maintained approved list. Greenhouse, Ashby, Lever, SmartRecruiters, and Workday (Salesforce internship board and NVIDIA) are built. More platforms come later, most reliable first:
  1. ~~Lever, SmartRecruiters~~ (done)
  2. Expand Workday after validating each tenant's completeness and field mapping.
  3. Meta (deployed; GitHub-runner fetch/classification validated)
  4. Amazon (implemented and locally validated; runner check pending), Eightfold
  5. Apple
  6. Google (HTML), custom sites
  7. Microsoft, which blocks datacenter IPs, so it needs the Raspberry Pi host
- **Simplify (slower fallback):** take postings from companies on the manually maintained FAANG+ list. Simplify lags company boards by hours, so it only catches what direct sources can't fetch yet. The duplicate check skips its copies of postings already seen directly.
- **Meta fallback eligibility:** before classifying announceable Simplify Meta copies, validate their official Meta job pages and replace the fallback title with the official JSON-LD title. Verify even when the job is absent from current direct search or no Meta board is configured. Normalize verified jobs/profile URL aliases and fetch each eligible URL once per poll with four workers and one retry. Preserve Simplify IDs, URLs, degree metadata, locations, dates and category. If any required official page fails parsing/HTTP or redirects to another ID, defer that poll's entire Simplify Meta company, without initializing it; other fallback companies continue. No persistent rejection cache, state-schema change, or merged-qualification parsing. This closes the confirmed case where Simplify removed `(PhD)` from job 2180490782513668. Degree requirements absent from the official title remain a separate limitation.
- **Build order:** get the core pipeline working end to end with Greenhouse, Ashby, and Simplify before adding platforms.
- **Workday pagination:** return a board's results only after every required page succeeds. If any page fails, discard that board's partial results and retry the entire board on the next poll. A partial fetch never marks the board successfully polled; this preserves silent first-poll behavior without adding page-resume state.
- **Native Workday filters:** configured per validated board with `filter_facet` and a display-label `filter_value`; resolve the current ID/count from the unfiltered first page and apply the same facet to every filtered page. NVIDIA uses `workerSubType = Intern (Fixed Term)`, validated against a complete scan to include all 10 currently announceable roles. Require the filtered initial total to equal the discovered count, exact page lengths, unique paths, and unchanged ID/count in a final unfiltered facet response. A failed required request or invalid response fails the board. A missing label logs a warning and falls back to a complete unfiltered scan. Filtered results still pass the existing local title, degree, channel and region rules. No periodic full scans or additional state tracking; manual coverage checks use `--dry-run --unfiltered`. Other native filters require source/board validation before enabling them.
- **Meta:** use anonymous unfiltered job search with current query IDs discovered from the public search component's JavaScript on each poll. Require unique, valid results matching the independent count before and after candidate details; reject query errors, unfinished responses, changed counts, truncated lists, or unavailable query modules. Accept an empty list only with validated zero counts. The current API supplies all jobs and the frontend paginates them; count validation guards against that behavior changing. Internship title/team signals and the shared undergraduate-title rule select candidates, whose JSON-LD details use four request workers and one retry. Any unresolved candidate failure rejects the board and cannot initialize its silent first poll. Apply shared channel/region rules and verified numeric URL identity/alias normalization for direct, historical, and Simplify deduplication. No browser, native internship filter, persistent cache, or state-schema change. Merged qualifications remain unsuitable for required-degree extraction. Deployed on `5a804ac`; read-only Validate Meta source run `37400514018` verified GitHub-runner access, 1,089 search jobs and nine announceable candidate details in 3.16s. Publication latency and future title/team coverage remain unverified. The sitemap is research evidence only; the earlier sitemap-only adapter was superseded. See `meta-research.md` for alternatives and validation.
- **Filter expansion deferred:** retain NVIDIA's validated native filter and complete scans on other supported boards; Amazon's later candidate-query decision is recorded separately below. The user chose to revert the local Lever, SmartRecruiters and Salesforce filter expansion: their shorter fetch times offer less benefit, while company-specific labels/IDs add maintenance and can omit eligible pipeline postings. Revisit individually if a board becomes a significant bottleneck. Preserve the API and live coverage findings in `native-filters.md`; no additional filters are enabled.
- **Large unfiltered Workday boards:** NVIDIA retains opt-in `jobFamilyGroup` partitions for manual coverage checks and missing-filter fallback. Fetch every category; each must stay below 2,000 results. Require category totals to equal the independent time-type total, exact page counts, disjoint unique paths, and unchanged category/time-type counts after scanning. Any failed check rejects the entire board. Use four concurrent HTTP requests at most, scheduling pages across categories in one pool rather than completing categories serially. Retain category/page order when validating and returning results. For configured partition or filtered boards, shared title/degree rules select detail candidates after the complete requested search scan; channel and region rules still run on full details.

- No filtering by internship term. The silent first poll keeps existing old-term postings from being announced.

- **Amazon:** the user selected faster regular polling through the union of the native internship filter and `intern`, `internship`, `co-op`, and `coop` keyword searches. Fully paginate every query with 100-row pages and at most four request workers; require exact lengths, unique IDs within each query and unchanged query counts before/after. Deduplicate overlaps by ID, reject inconsistent candidate data, and retry count churn up to three complete query-union passes. Reject unresolved query failures; any query reaching the 10,000 cap falls back to the complete business-partition scan. Preserve basic-only degree extraction, shared title/channel/region policy and URL identity. Manual `--dry-run --unfiltered` uses the complete partition scan (and disables Workday native filters); no scheduled full audit or persistent cache/state change. Live comparison on 2026-10-07: complete 22,371 jobs / 349 candidates / 32 eligible in 47.09s, union 349 candidates / the same 32 eligible IDs in 9.21s, including ASIC 10517535. Keyword/native coverage can change and is not guaranteed beyond this snapshot; count equality does not detect all same-count changes. Amazon remains local/uncommitted, with runner validation pending.

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
- **Workday copies:** postings from the same Workday tenant with the same requisition ID count as one job, even across career-site URLs. Normalize those URL variants for duplicate checks while keeping the original application link for Discord. Apply the same normalization to historical stored URLs so existing state continues to prevent duplicate announcements.

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
  - **Meta-specific descriptions:** Production Engineer and Network Production Engineer map to SWE; DFX Engineering maps to other engineering, as selected by the user. These titles can describe different duties at other companies, so the additions apply only to Meta.
  - **Amazon-specific exclusion:** Business Developer duties are business/customer development. That phrase alone does not supply the SWE `developer` signal; other explicit channel keywords still apply.
- **Intern detection:**
  - Ashby: `employmentType == "Intern"`.
  - Lever and SmartRecruiters: the platform's label (Lever `commitment`, SmartRecruiters `typeOfEmployment`) **or** the title matches the intern regex. Labels vary by company, and some internships are labelled "Full-time". Word boundaries keep out labels like "International Office Entity".
  - Greenhouse, Workday and Amazon: title matches `\b(intern|internship|co-op|coop)s?\b`, case-insensitive. Workday's `timeType` can be `Full time` for internships and is not used as an eligibility signal.
  - Meta: a title signal or an explicit internship team selects search candidates; candidate JSON-LD employment type also feeds shared internship classification.
  - All sources: titles containing "high school" are excluded.
- **Undergrad only:**
  - Simplify postings are kept if `degrees` is empty or includes `Bachelor's` or `Associate's`.
  - On all sources, a title naming a graduate degree or graduate students (PhD, MS, MSc, Master's, MBA, Doctoral, Graduate, Grad) is excluded unless it also names BS, BSc, Bachelor's, or Undergrad. "Undergraduate" does not count as "Graduate".
  - Workday additionally extracts explicit enrollment/education requirements from description paragraphs. A graduate-only requirement excludes the role; a requirement allowing bachelor's or associate's students remains eligible. Preferred qualifications do not establish a required degree, and a generic mixed-degree introduction cannot override a specific graduate-only requirement. Unrecognized or unstated education retains the existing title-based policy. The user approved this extension after a confirmed NVIDIA graduate-only false positive. Partition-mode detail candidates must have an inspectable description. Amazon reuses this extraction on its separate basic qualifications, excluding preferred qualifications entirely.
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
- `[[boards]]` entries, each with `source` (`greenhouse`, `ashby`, `lever`, `smartrecruiters`, `workday`, or `meta`), `slug` (the board ID in the API URL), and `name` (display name, also used as the company name for dedup). Workday additionally requires a validated `host` and uses a `tenant/site` slug. Native filters optionally require both `filter_facet` (`workerSubType` or `jobFamilyGroup`) and a nonempty `filter_value`; these fields currently apply only to Workday. NVIDIA uses `workerSubType` with `Intern (Fixed Term)` and retains `partition_facet = "jobFamilyGroup"`; omitted partition configuration means capped unfiltered boards still fail.
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
- `--unfiltered` requires `--dry-run` and clears native filter configuration for that invocation only, retaining partition coverage and local classification. It is a manual coverage check, never a periodic stateful audit.
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

## Historical rollout checkpoints (2026-10-05)

- Salesforce and NVIDIA Workday support is committed and pushed to `main`. The push rejection was resolved by merging the remote README Discord-link change; both changes are preserved.
- Local regression suite: 231 tests passed. GitHub's Tests workflow succeeded on deployed merge commit `61c4ff4`.
- The user confirmed that the deployed Workday poll verification worked. Both new boards use silent first successful polls; later eligible postings are announced only if unseen through both direct sources and Simplify. The live dry-run counts in the validation notes are test evidence, not production announcement counts.
- Subsequently inspected production run `37269532808` on commit `61c4ff4`: success; NVIDIA verified 2,679 search rows and fetched 100 candidate details. Salesforce was first-polled with no new silent records because eligible existing roles were already seen; NVIDIA was first-polled with four additional silent records. The workflow saved updated state in commit `2e67c6c`. Poll and post took 71 seconds with sequential board fetching; Workday used up to four requests internally. This was the baseline before the later concurrency deployment.
- GitHub history showed successful external dispatches at 05:00, 05:20, and 05:40 UTC, confirming the observed 20-minute cadence for those runs.
- Polling optimization is authorized, implemented locally, and verified with 235 passing tests. Same-machine live dry runs took 88.73 seconds with one board worker and 58.67 seconds with four (33.9% reduction); both succeeded on all 52 company boards plus Simplify with identical per-source posting counts. NVIDIA verified 2,684 search rows and fetched 107 candidate details in both runs. Both dry runs sent nothing and saved no state. This is one measured pair, not a production timing guarantee.
- Polling optimization is deployed on merge commit `cc0ffcc`. Production runs `37313512480` and `37313790508` succeeded: Poll and post took 76s and 66s, versus 77s in each of the two preceding sequential runs. Total fetch times were 75.24s and 65.45s; NVIDIA alone took 69.67s and 59.64s, verifying 2,684 search rows and 107 candidate details in both. NVIDIA's unchanged internal scan dominates the remaining time; board parallelism cannot remove that work. These are observational production comparisons, not controlled benchmarks.
- NVIDIA follow-up is implemented locally and passes 238 tests. Same-machine old/new dry polls took 68.28s/49.09s (28.1% reduction); all 53 source fetches succeeded. NVIDIA returned identical postings, with 2,684 search rows and 107 candidate details in both. Renesas changed from 949 to 950 postings during the comparison; other returned postings matched. The new NVIDIA scan took 34.90s and details 13.81s. No messages or state writes. This is one measured pair, not a production guarantee.
- The user subsequently chose native filtering on regular polls with manual full-scan checks, removing partition-board priority scheduling and its test. The retained follow-up includes four-request Workday pools, cross-category scheduling for full scans, stage timing logs, and coverage validation. NVIDIA native filtering and `--dry-run --unfiltered` are implemented locally; 256 tests pass and live CLI validation succeeded. No hourly audit or state schema changes.
- The completed same-machine CLI comparison succeeded on all 53 sources in both modes: filtered 25.63s versus unfiltered 54.35s (52.8% shorter). NVIDIA took 16.94s versus 47.10s; search stages took 5.43s for 128 rows versus 35.03s for 2,685 rows, with 106 versus 108 detail candidates. Both returned exactly the same 10 announceable NVIDIA Posting objects. Other boards changed during the consecutive live polls, so this is observational timing evidence, not a production guarantee. Neither run sent messages or saved state.
- Those native-filter deployment checkpoints are historical. Meta is now deployed; Amazon's current implementation and runner-validation status are recorded above. Further native filters remain deferred, and additional Workday tenants require individual validation.

## Current task: shorten polling

- **Baseline:** deployed run `37269532808` spent 71 seconds in Poll and post with sequential company-board fetching. Workday already uses up to four concurrent HTTP requests internally. First-poll recording does not reduce future fetch counts.
- **Change:** fetch company boards with four board workers in configuration order and process Simplify after direct sources so duplicate checks continue to prefer direct postings. No special partition-board priority. Workday's internal four-request pool remains separate. NVIDIA uses its validated native internship filter on regular polls; manual unfiltered scans and missing-label fallback interleave category pages. Complete requested coverage and all required details must succeed before returning any postings.
- **Safety:** only fetching runs concurrently. Classification, deduplication, board initialization, state writes, and Discord sends remain sequential. A failed board stays omitted and uninitialized; Workday's complete-page/detail requirement remains intact.
- **Measurement:** per-source and total fetch timing logs, plus separate Workday search-scan and detail timings. Compare old and new live dry runs on the same machine/configuration, checking duration, successful board coverage, and returned postings. The deployed 71-second step is a reference, not an identical-environment benchmark.
- **Verification:** test overlapping fetches and the four-worker bound, deterministic result order, direct/Simplify duplicate precedence when requests finish out of order, and failure isolation with silent first-poll behavior. Run the regression suite and a live dry run that sends no messages and saves no state. After deployment, compare scheduled run timings.
- **Status:** initial board concurrency is deployed on `cc0ffcc`. The latest native-filter follow-up is local and uncommitted, with 256 passing tests and a successful live CLI comparison. Tests cover same-filter pagination, ignored filters, changed counts, repeated/short pages, unavailable-label fallback, empty filtered boards, silent recovery after a detail failure, and non-persisting manual unfiltered CLI checks. Cross-category concurrency tests remain; the priority test was removed with its rule. NVIDIA rejected 50- and 100-row page limits with HTTP 400, so page size stays 20.

## Remaining source questions

- HubSpot/NVIDIA error research (2026-10-07): HubSpot's configured Greenhouse board returns 404, and the live official careers directory also fails through its GraphQL backend; its empty display is not validated zero-job coverage. North American emerging-talent links point to RippleMatch. Its anonymous company API identifies HubSpot as company 708; the public roles endpoint returns HTTP200 with an empty list, reproduced in the browser and direct HTTP. RippleMatch explicitly supports private roles excluded from company pages, so this endpoint cannot establish complete internship coverage. The user authorized validation against known roles before adding a supplemental source: officially shared US/Canada SWE roles `ada1428b`/`90098ffb` return anonymous detail JSON with verified identity, title, location, internship type and `overview.datePosted`, but both are disabled and their pages confirm applications are closed. Active-role discovery remains unverified; no RippleMatch adapter is enabled. NVIDIA's previously failed detail recovered on three requests, and a complete filtered poll succeeded; a bounded transient detail retry is recommended but not implemented. See [source-error research](source-errors-research.md).
- Amazon: regular candidate queries and manual complete partitions, field/degree mapping and Simplify aliases are locally validated. After commit/push, verify GitHub-runner access with `validate-amazon.yml`, then inspect normal silent initialization. Publication latency remains unmeasured. See [Amazon research](amazon-research.md).
- Workday expansion: verify other tenants' partition coverage, posting dates, requisition formats, and education wording before adding boards. NVIDIA's category partitions returned all 2,678 observed postings; a category growing to 2,000 or more is deliberately rejected until further partitioning is verified. See `workday-adapter.md` and `nvidia-workday.md` for evidence and verification.

The user reported that the deployed NVIDIA filter appears to work. This is user-reported deployment evidence; no additional production timing audit was performed during the filter-expansion investigation.


## Meta implementation status (2026-10-05)

The anonymous search adapter is deployed and enabled on `main` (`5a804ac`). It replaces the unsuccessful sitemap-only adapter. Research history, source links, alternatives, and limitations are retained in [Meta research](meta-research.md).

Local verification: a complete search returned 1,089 records and nine candidate details in 5.12s; four matched classification before the subsequent Meta-specific role mappings. A one-time audit inspected all 1,089 search-listed pages in 159.92s, finding the same four eligible postings among 1,084 parseable details. Five non-candidate pages lacked JSON-LD, so hidden internship metadata remains unverified. The full CLI dry poll succeeded on all 54 sources in 24.27s (Meta: 5.37s). These runs sent no messages and saved no state.

Deployment and runner access verified: [Validate Meta source run 37400514018](https://github.com/alexypeng/swe-intern-alerts/actions/runs/37400514018) succeeded on `5a804ac`, verifying 1,089 search jobs and fetching nine candidate details in 3.16s; all nine were announceable after the role mappings. This validates runner fetch/classification; scheduled polling and state initialization were not inspected in this check. The read-only Validate Meta source workflow fails on source errors and uses no webhooks or persistent state. Existing Simplify fallback and silent first-success behavior remain. Private query schemas, title/team conventions, and publication delay remain limitations; a successful normal poll workflow can still have skipped Meta, so verify the source's own log.

Subsequent [regular poll 37400912707](https://github.com/alexypeng/swe-intern-alerts/actions/runs/37400912707) succeeded on `5a804ac`: Meta verified 1,089 search jobs and fetched nine details in 2.95s; eight entries were recorded silently, zero were new announcements, and the board was first-polled. Total fetch time was 18.52s; state was saved in commit `6a39f29`. The ninth posting's deduplication reason was not inspected.
