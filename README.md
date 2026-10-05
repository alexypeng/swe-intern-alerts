# swe-intern-alerts

Posts new internship openings to Discord, within about 20 minutes of a company publishing them.

Every 20 minutes a GitHub Actions workflow polls company job boards, keeps only undergrad internships, and posts the ones it hasn't announced before. Each job type has its own channel, and postings are grouped by region inside each message.

```
## 🇺🇸 US
**Stripe** — [Software Engineer, Intern](<https://stripe.com/jobs/search?gh_jid=8128745>)
San Francisco, Seattle, New York City · Aug 31

## 🇨🇦 Canada
**Stripe** — [Software Engineer, Intern (Summer or Winter)](<https://stripe.com/jobs/search?gh_jid=8130805>)
Toronto · Aug 31
```

## How it works

```
GitHub Actions (every 20 min)
  → load state.json from the `state` branch
  → fetch Greenhouse, Ashby, Lever, and SmartRecruiters boards, then Simplify (FAANG+ fallback)
  → keep undergrad internships; pick channel(s) and region(s)
  → skip anything already announced (job ID → URL → company + title + location)
  → post to each channel's Discord webhook
  → commit state.json back to the `state` branch
```

- **Sources:**
  - Greenhouse, Ashby, Lever, and SmartRecruiters company boards, polled directly. This is the fast path.
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

3. **First run:** go to *Actions → Poll internships → Run workflow*. It posts nothing and creates the `state` branch. After that, the schedule takes over.

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
- **Company with no supported board** (e.g. Google, Microsoft): add its name to `faang_plus` exactly as Simplify spells it (case doesn't matter).
- **Every hiring cycle:** update `simplify_url` to the new Simplify repo (e.g. `Summer2028-Internships`).

To change which titles go to which channel, or which places map to which region, edit the keyword and place tables in [`src/intern_alerts/classify.py`](src/intern_alerts/classify.py). The workflow log lists any locations it couldn't recognize.

## Running locally

Requires [uv](https://docs.astral.sh/uv/).

```
uv run pytest                                   # tests
uv run python -m intern_alerts --dry-run        # fetch and print messages; sends nothing, saves nothing
```

A dry run with no `state.json` treats everything as a first poll, so it only prints summary lines.

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
- **Schedule delays:** GitHub may delay or skip scheduled runs when it's busy. Compare scheduled run times with:
  ```
  gh run list --workflow poll.yml --event schedule --limit 100 --json createdAt --jq '.[].createdAt'
  ```
- **60-day rule:** GitHub disables scheduled workflows in public repos after 60 days with no repository activity. If that happens, re-enable the workflow from the Actions tab.
- **State:** `state.json` on the `state` branch holds everything announced in the last 12 months, plus when each board was first polled. Older records are pruned automatically.

## Roadmap

More platforms, most reliable first: Workday, Amazon and Eightfold, Apple, then Google, Meta and custom sites. Microsoft blocks cloud IPs, so it needs a planned move to a Raspberry Pi on a home connection.
