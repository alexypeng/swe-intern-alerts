# External scheduler setup

cron-job.org dispatches the existing GitHub workflow every 20 minutes. GitHub Actions still runs the Python job and saves state. Complete the setup below before relying on automatic polling.

## 1. Create the GitHub token

Open [GitHub's fine-grained token form](https://github.com/settings/personal-access-tokens/new).

- Token name: `intern-alerts scheduler`.
- Resource owner: `alexypeng`.
- Choose an expiration date and set a reminder to replace the token before then.
- Repository access: **Only select repositories**, then `swe-intern-alerts`.
- Repository permissions: **Actions → Read and write**. Metadata read access is automatic; no additional permissions are needed.
- Generate the token and copy it for the next step. Paste it directly into cron-job.org, not chat or a tracked file.

GitHub's [dispatch endpoint documentation](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) specifies Actions write permission for fine-grained tokens.

## 2. Create the scheduler job

Sign in to the [cron-job.org console](https://console.cron-job.org/) and create a cron job. Keep it disabled while configuring and testing.

| Setting | Value |
| --- | --- |
| Title | `Internship alerts` |
| URL | `https://api.github.com/repos/alexypeng/swe-intern-alerts/actions/workflows/poll.yml/dispatches` |
| Schedule | Custom: minutes `7`, `27`, `47`; every hour, day, month, and weekday |
| Request method | `POST` |
| Request body | `{"ref":"main"}` |

In the request settings (the console's Advanced section), add these headers:

| Header | Value |
| --- | --- |
| `Authorization` | `Bearer YOUR_GITHUB_TOKEN` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |
| `X-GitHub-Api-Version` | `2026-03-10` |

Replace `YOUR_GITHUB_TOKEN` with the token from step 1. Leave HTTP basic authentication off. Enable failure notifications. The service supports [custom headers, POST requests, and request bodies](https://cron-job.org/en/faq/).

## 3. Test the job

Use the console's test-run feature. This triggers a real poll and can post new listings to Discord. Expect HTTP `200` with the run ID and URL for the pinned API version.

Open [Poll internships in GitHub Actions](https://github.com/alexypeng/swe-intern-alerts/actions/workflows/poll.yml). Confirm a new run appears and finishes successfully, including the state-saving step. A successful HTTP response means GitHub accepted the dispatch; it does not mean the poll itself succeeded.

If the test fails:

- `401`: check the token and the `Bearer ` prefix.
- `403`: check Actions write permission, token expiration, and repository Actions settings.
- `404`: check the URL, repository selection on the token, and that `poll.yml` exists on `main`.
- `422`: check the JSON body and the `main` branch.

Do not disable the GitHub workflow: both external and manual dispatch require it to stay active.

## 4. Enable and verify

Enable the cron-job.org job. Check its next predicted execution times and, after the next scheduled request, confirm a corresponding GitHub run appears:

```powershell
gh run list --workflow poll.yml --event workflow_dispatch --limit 10
```

External and manual requests both use `workflow_dispatch`; compare timestamps with cron-job.org's history to identify automatic runs. Check several cycles to confirm the schedule is working.

The workflow removes GitHub's built-in schedule, so push that change to `main` to complete the switch. Keep the workflow enabled. Replace the token in the Authorization header before it expires. Scheduler failure notifications cover HTTP dispatch failures; inspect GitHub Actions for polling or posting failures. The service [does not guarantee exact timing](https://cron-job.org/en/faq/), and dispatched jobs may still wait for a GitHub runner.
