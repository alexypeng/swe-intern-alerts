# GitHub Actions scheduled polls not starting

Researched October 4, 2026 (America/Toronto). This records evidence and proposed diagnostics, not a change to the agreed runtime.

## Finding

The evidence points toward missing schedule delivery or scheduler registration on GitHub's side, but does not prove either. Manual success validates execution of the polling job; it cannot validate the independent schedule trigger. No scheduled run exists to inspect for a job failure.

## Repository evidence

The investigation session checked GitHub's deployed configuration and API responses:

- Repository `alexypeng/swe-intern-alerts` is public, not a fork, not archived, and uses `main` as its default branch. [Repository API](https://api.github.com/repos/alexypeng/swe-intern-alerts).
- Workflow `374949134`, `.github/workflows/poll.yml`, is `active`. [Workflow API](https://api.github.com/repos/alexypeng/swe-intern-alerts/actions/workflows/374949134).
- Repository Actions permissions report `enabled: true`, `allowed_actions: all`. This was checked through the authenticated `repos/alexypeng/swe-intern-alerts/actions/permissions` API.
- The deployed schedule is `7,27,47 * * * *`, plus `workflow_dispatch`. Its latest cron change was commit `d61a19b656c1de100414ececddf2b80fff2c1422`, October 4 at 19:53 EDT, attributed by GitHub to `alexypeng`. [Deployed workflow](https://github.com/alexypeng/swe-intern-alerts/blob/main/.github/workflows/poll.yml), [cron commit](https://github.com/alexypeng/swe-intern-alerts/commit/d61a19b656c1de100414ececddf2b80fff2c1422).
- The schedule-filtered runs API returned `total_count: 0`; manual polling runs have succeeded. Disabling and re-enabling the workflow did not produce a scheduled run by the user's subsequent check. [Schedule runs API](https://api.github.com/repos/alexypeng/swe-intern-alerts/actions/workflows/poll.yml/runs?event=schedule&per_page=5), [run history](https://github.com/alexypeng/swe-intern-alerts/actions/workflows/poll.yml). These endpoints are live views, not permanent snapshots.

## What GitHub documents

Schedules use the latest default-branch commit and require the workflow file on that branch. The minimum interval is five minutes. UTC is the default timezone; this hourly minute list also fires at :07, :27, and :47 in Toronto. Heavy load can delay schedules or drop queued jobs, especially at the top of an hour. Public repositories lose scheduled workflows after 60 days without activity. A writer's commit changing the cron reactivates a deactivated workflow and sets its scheduled actor; the docs do not promise this repairs an already active schedule. The inactive-actor warning specifically concerns Enterprise Managed Users. [Official schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

These documented default-branch, minimum-interval, and disabled-workflow conditions do not match the configuration checked above. The cron already avoids the top of the hour.

GitHub's status API reported Actions `operational`, no active incidents, and overall `All Systems Operational`; its page timestamp was `2026-10-05T02:39:22.354Z`. This is aggregate status, not proof that this repository's schedules are healthy. [Official status API](https://www.githubstatus.com/api/v2/summary.json).

## Recent firsthand reports

These are reports of symptoms, not authoritative explanations of scheduler internals:

- On September 30, another owner reported default-branch cron schedules never starting while push and manual dispatch worked. The owner said disabling/re-enabling failed, then reported the first scheduled build on October 1, days late. [Community discussion 209156](https://github.com/orgs/community/discussions/209156).
- On September 29, another owner reported an active default-branch workflow, successful manual runs, no schedule runs for over four hours, and operational aggregate status. [Community discussion 209036](https://github.com/orgs/community/discussions/209036).

This makes a GitHub scheduling problem plausible. Neither report proves a shared cause, a current outage, or that waiting a particular number of hours will fix this repository. Claims in replies that a cron edit reliably forces registration are unverified.

## Proposed next steps

1. Optional controlled experiment: change only the cron to `8,28,48 * * * *`, have the owner commit and push it to `main`, and record the push time in UTC. This preserves the 20-minute interval but conflicts with the literal cron recorded in `docs/plan.md`, so the plan should be updated if this experiment is accepted. Do not describe it as a guaranteed repair. No workflow or plan edit was made during this research.
2. Check the schedule API after several expected slots; distinguish an absent run from a queued, failed, or successful run. A successful manual dispatch is still not success for this experiment. The official run-list API supports filtering by `event`. [Workflow runs API documentation](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow).

   ```powershell
   gh api 'repos/alexypeng/swe-intern-alerts/actions/workflows/poll.yml/runs?event=schedule&per_page=10' --jq '{total_count, runs: [.workflow_runs[] | {id, event, created_at, status, conclusion, head_sha}]}'
   ```

3. If still empty, report the evidence to GitHub through [Support](https://support.github.com/) or [Community Actions discussions](https://github.com/orgs/community/discussions/categories/actions): repository URL, workflow ID, default-branch commit, cron and exact missed UTC times, active/enabled API results, zero scheduled runs, successful manual run IDs, and the enable/disable attempt. Research did not send a report.
4. For polling continuity, make a runtime decision: an external timer could call the existing `workflow_dispatch` endpoint; it requires authenticated Actions write access. Alternatively, bring forward the Raspberry Pi move already recorded in `docs/plan.md`. Neither fallback was configured. External dispatch still uses GitHub runners; it bypasses the cron trigger, not all Actions availability. [Official dispatch endpoint](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [project plan](../plan.md).
