# swe-intern-alerts

Posts new internship openings to Discord, polling company boards every 20 minutes.

Every 20 minutes cron-job.org triggers a GitHub Actions workflow that polls company job boards, keeps only undergrad internships, and posts the ones it hasn't announced before. Each job type has its own channel, and postings are grouped by region inside each message.

<img width="809" height="437" alt="image" src="https://github.com/user-attachments/assets/2650a7fa-5367-4185-92d0-184515b5fad5" />

Discord can be accessed here: https://discord.gg/hjb77xqxHP

## How it works

```
cron-job.org (every 20 min) → GitHub Actions
  → load state.json from the `state` branch
  → fetch Greenhouse, Ashby, Lever, SmartRecruiters, and Workday boards, then Simplify (FAANG+ fallback)
  → keep undergrad internships; pick channel(s) and region(s)
  → skip anything already announced (job ID → URL → company + title + location)
  → post to each channel's Discord webhook
  → commit state.json back to the `state` branch
```

- **Sources:**
  - Greenhouse, Ashby, Lever, SmartRecruiters, and Workday company boards, polled directly. This is the fast path. Workday coverage includes Salesforce's internship board and NVIDIA.
  - Simplify's internship list for the companies in `faang_plus`. It's a slower fallback (Simplify lags company boards by hours) for companies with no supported board.
- **Channels:** SWE, data/ML, hardware/firmware, quant, other engineering, product.
- **Regions:** US, Canada, Europe, UK, Remote, and "Location not specified" for vague locations.
- **No floods:** the first time any board or FAANG+ company is polled, its existing postings are recorded silently. Only postings that appear after that are announced.

The full design and the reasoning behind each decision are in [`docs/plan.md`](docs/plan.md).

## Setup

1. **Discord:** create the six channels. For each one, go to *Edit Channel → Integrations → Webhooks → New Webhook* and copy the webhook URL.
2. **GitHub secrets:** go to *Settings → Secrets and variables → Actions* and add one repository secret per channel:

   | Secret | Channel |
   |---|---|
   | `WEBHOOK_SWE` | Software engineering |
   | `WEBHOOK_DATA_ML` | Data / ML / AI |
   | `WEBHOOK_HARDWARE` | Hardware, firmware, electrical |
   | `WEBHOOK_QUANT` | Quant |
   | `WEBHOOK_OTHER_ENG` | Mechanical, civil, aerospace, etc. |
   | `WEBHOOK_PRODUCT` | Product |

3. **First run:** go to *Actions → Poll internships → Run workflow*. On an empty state, it posts nothing and creates the `state` branch.
4. **Scheduler:** follow [the cron-job.org setup guide](docs/external-scheduler.md) to dispatch the workflow every 20 minutes.

## Adding companies

Edit [`config.toml`](config.toml), then commit and push. Each new entry gets a silent first poll, so adding companies never floods your channels.

- **Greenhouse, Ashby, Lever, or SmartRecruiters board.** Add a `[[boards]]` entry. `slug` is the board's ID in the API URL:

  ```toml
  [[boards]]
  source = "greenhouse"   # or "ashby", "lever", "smartrecruiters"
  slug = "stripe"         # boards-api.greenhouse.io/v1/boards/<slug>/jobs
  name = "Stripe"         # shown in messages
  ```

  To check a slug, open its API URL in a browser. A valid slug returns JSON with jobs in it:
  - Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs`
  - Ashby: `https://api.ashbyhq.com/posting-api/job-board/<slug>`
  - Lever: `https://api.lever.co/v0/postings/<slug>?mode=json`
  - SmartRecruiters: `https://api.smartrecruiters.com/v1/companies/<slug>/postings` (the slug is case-sensitive)
- **Workday board.** Use the host from its public career URL and a `tenant/site` slug:

  ```toml
  [[boards]]
  source = "workday"
  slug = "salesforce/Futureforce_Internships"
  host = "salesforce.wd12.myworkdayjobs.com"
  name = "Salesforce"
  ```

  Every search page and required detail must succeed before the board is processed. Workday URLs for the same tenant and verified `JR` requisition are compared as one job across career sites; messages retain the original application URL. Existing state needs no reset.

  NVIDIA uses its native Job Type filter on every search page:

  ```toml
  filter_facet = "workerSubType"
  filter_value = "Intern (Fixed Term)"
  partition_facet = "jobFamilyGroup"
  ```

  The filter ID is discovered from the board each poll. Filtered totals, page sizes, unique paths, and the final filter count are checked before fetching eligible details. Existing title, degree, channel, and region rules still apply. If the label is unavailable, a warning precedes a complete unfiltered scan. Filters are configured per validated Workday board; no hourly scan schedule or extra state is needed.

  `partition_facet = "jobFamilyGroup"` remains for manual unfiltered scans and fallback beyond the 2,000-result window. Category pages share four workers, with cross-checks for coverage and changing counts. Other capped boards are rejected unless partition coverage has been verified and explicitly enabled. A category that itself reaches 2,000 results is also rejected. [NVIDIA validation](docs/nvidia-workday.md) records the evidence and limits.

  Workday eligibility also checks explicit education requirements in descriptions: graduate-only requirements are excluded, mixed requirements accepting bachelor's students remain eligible, and preferred degrees do not exclude roles. Unrecognized education wording retains the existing title-based policy.
- **Company with no supported board** (e.g. Google, Microsoft): add its name to `faang_plus` exactly as Simplify spells it (case doesn't matter).
- **Every hiring cycle:** update `simplify_url` to the new Simplify repo (e.g. `Summer2028-Internships`).

To change which titles go to which channel, or which places map to which region, edit the keyword and place tables in [`src/intern_alerts/classify.py`](src/intern_alerts/classify.py). The workflow log lists any locations it couldn't recognize.

## Running locally

Requires [uv](https://docs.astral.sh/uv/).

```
uv run pytest                                   # tests
uv run python -m intern_alerts --dry-run        # fetch and print messages; sends nothing, saves nothing
uv run python -m intern_alerts --dry-run --unfiltered  # manual comparison without native filters
```

A dry run with no `state.json` treats everything as a first poll, so it only prints summary lines.

`--unfiltered` requires `--dry-run`. It preserves Workday partition coverage and local eligibility rules while bypassing native source filters. Workday logs separate search-scan and detail durations.

To send real messages from your machine (PowerShell), set the webhook URLs for the session first:

```powershell
. .\scripts\set-webhooks.ps1
uv run python -m intern_alerts
```

This writes a local `state.json` (ignored by git). `STATE_PATH` changes where it's stored.

To fill the channels with what's already open (for example, when they're first set up):

```powershell
uv run python -m intern_alerts --backfill 14   # every open posting from the last 14 days
```

A backfill ignores state and saves none. The scheduled bot has already recorded these postings, so it won't send them again. Running the backfill twice sends everything twice.

## Operating notes

- **Failures:**
  - A board that fails to fetch is logged as a warning and retried on the next run.
  - A Discord message that fails to send turns the run red. Its postings aren't marked as seen, so they're sent on the next run.
- **Schedule checks:** compare cron-job.org's execution history with GitHub's dispatched runs. GitHub groups external dispatches and manual runs under the same event:
  ```
  gh run list --workflow poll.yml --event workflow_dispatch --limit 100 --json createdAt,conclusion
  ```
- **Scheduler credentials:** replace the GitHub token in cron-job.org before it expires. Enable scheduler failure notifications; they report dispatch failures, while poll failures appear in GitHub Actions.
- **State:** `state.json` on the `state` branch holds everything announced in the last 12 months, plus when each board was first polled. Older records are pruned automatically.

## Roadmap

Next: deploy and check NVIDIA native filtering, validate native filters on other supported boards where the API supports them, then investigate Meta before Amazon and Eightfold, followed by Apple, Google and custom sites. Additional Workday boards require individual completeness checks. Microsoft blocks cloud IPs, so it needs a planned move to a Raspberry Pi on a home connection.
