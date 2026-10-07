# HubSpot and NVIDIA source errors

Read-only investigation on 2026-10-07. No runtime/config changes, Discord sends, state writes, or commits were made during this research.

## HubSpot

### Confirmed failure

The configured [Greenhouse jobs endpoint](https://boards-api.greenhouse.io/v1/boards/hubspotjobs/jobs) still returned HTTP 404 in a fresh direct request. This is not evidence of an empty board.

The live [official careers directory](https://www.hubspot.com/careers/jobs) and canonical `/careers/jobs/all` returned HTML containing a React directory shell rather than job listings. Its [language/config script](https://www.hubspot.com/hubfs/hub_generated/template_assets/1/13123332719/1754337968754/template_careers-language.min.js) points to `https://wtcfns.hubspot.com/careers/graphql`. The [directory bundle](https://www.hubspot.com/hubfs/hub_generated/template_assets/1/212906311191/1778790754246/template_careers-directory.min.js) defines a `jobs` query with optional department, office, language, role-type, and search filters. It still links Greenhouse job alerts using `job_board=hubspotjobs`.

A fresh anonymous read-only query to that GraphQL endpoint returned HTTP 200 **with an error**, not usable jobs:

```json
{"errors":[{"message":"404: Not Found","path":["jobs"]}],"data":{"jobs":null}}
```

Its error extensions identify an upstream `JobsApi` HTTP 404 (`Job not found`). A headless browser check of the official directory independently reproduced the same failing GraphQL response; the visible page said “No jobs are currently listed.” That message appeared after the failed request, so it must not be interpreted as verified zero vacancies. Switching the adapter to this GraphQL endpoint currently would reproduce the upstream failure.

Search-index copies of official directory pages still contain older lists of approximately 132–136 jobs. Those cached/crawled lists are not fresh endpoint evidence and cannot establish current completeness, availability, or posting freshness. No working replacement Greenhouse slug or complete alternative general-careers feed was verified. The observed evidence does not establish whether the cause is temporary backend trouble, retirement of the old board, or a platform transition.

### Separate North America internship source

Fresh HTML from HubSpot's [official Emerging Talent page](https://www.hubspot.com/careers/emerging-talent) explicitly links North America applicants to [HubSpot on RippleMatch](https://app.ripplematch.com/v2/public/company/hubspot?tl=cd866a5f), also using the short link `https://app.ripplematch.com/t/cd866a5f`. EMEA and LATAM applicants are linked to the existing careers directory with `#roleType=intern`.

The public RippleMatch company page returned HTTP 200 and HubSpot metadata, but only an application shell. No complete anonymous job feed, job count, pagination contract, identifier mapping, or date semantics were verified. Therefore RippleMatch is a grounded next source to investigate for North America internships, not a ready replacement adapter. The official region split also means a North America feed alone would not prove coverage of EMEA/LATAM roles.

### Recommended direction

- Preserve the current failure behavior: do not convert HTTP 404 or GraphQL `jobs:null` into a successful empty poll or initialize a new board from them.
- Do not change the Greenhouse slug speculatively, or replace it with the currently broken GraphQL wrapper.
- Investigate the officially linked RippleMatch source next, validating complete anonymous access, identity, internship metadata and region coverage before implementation. Continue the existing Simplify fallback meanwhile.
- Recheck the official general directory for recovery. If changing sources later, preserve verified URL/identity alias deduplication; a newly introduced source board must initialize silently on its first successful fetch under the existing plan.

### Fields and completeness observations

The public directory query requests job ID/title, department name/ID, office ID/location, and location name. The frontend query has no pagination arguments; its configured page sizes (six mobile, twelve desktop) describe client-side presentation. Because the live query fails, no current result count or complete-list behavior was established. Do not build a completeness claim from bundle shape alone. The observed summary query does not request a posting date.

### RippleMatch public API follow-up (2026-10-07)

RippleMatch does expose anonymous endpoints used by its own public company frontend:

- [HubSpot company configuration](https://app.ripplematch.com/api/v2/company-branded-page/hubspot) returned HTTP 200 without login, identifying company ID `708`, UUID `41be18a8-cc4f-4aa3-a934-e97c7af6de0a`, and slug `hubspot`.
- [HubSpot public roles](https://app.ripplematch.com/api/v2/public/roles/708) returned HTTP 200 with `[]` in the isolated anonymous browser and in two independent direct requests without cookies or authorization headers.
- The [company API module](https://static.ripplematch.com/js/distribution/assets/CompanyBrandedPage.api.KhOnuaeP.v1.js) defines the first route; the [company page module](https://static.ripplematch.com/js/distribution/assets/CompanyBrandedPage.page.BdPY9AJh.v1.js) defines the second. These are public frontend APIs, not a documented supported developer API contract.

The fresh anonymous company page shows a profile/sign-up invitation for opportunities matched to the user. Its public role array is genuinely empty in the observed response, but **that does not prove HubSpot has no openings**, or that every opportunity offered through personalized matching is exposed publicly. We did not sign in, create a profile, or access private account APIs.

RippleMatch's official [public versus private roles documentation](https://resources.ripplematch.com/public-vs.-private-roles-in-the-role-settings) confirms that public roles appear on the company branded page and private roles do not; both can use AutoMatch and direct applications. Its [adding a role guide](https://resources.ripplematch.com/how-do-i-add-a-new-role-ripplematch-help-center) likewise describes private roles as restricted to sourced/matched candidates. Consequently this public API cannot establish coverage of all HubSpot roles. Whether HubSpot currently has any private roles remains unknown.

The frontend fetches the public role array once without pagination parameters. It then separates `event_mode` events from jobs, applies location filters locally, and implements “show more” against the already loaded data. It supplies no independent server count or pagination token. This establishes the current frontend behavior, not a guarantee that the server never caps or restricts its public list.

Potential field mapping is visible in the frontend source: `public_id` supplies role identity, `name` the displayed title, and `role_locations` the location array (with `location` as a city fallback). The frontend constructs job links as `/job/{company.url}/{public_id}` and event links separately. These are source-derived mappings; the currently empty HubSpot array prevents validating an active role's actual schema, application URL, posting date, employment type, required degree metadata, and closed/open behavior. None of those unobserved fields should be invented or inferred from an empty response.

**Recommendation:** this API is accessible and worth retaining as a candidate source, but it is not yet a verified useful HubSpot internship feed. Recheck it when an independently confirmed HubSpot North America role is published, compare that role's presence with the official page, and validate detail fields/completeness before enabling an adapter. Keep Simplify fallback and the existing Greenhouse failure handling meanwhile. A personalized signed-in session would add account dependence and still would not establish complete board coverage.

An official [Greenhouse integration guide](https://support.greenhouse.io/hc/en-us/articles/54675620080283-RippleMatch-integration), updated August 20, 2026, describes separate RippleMatch-specific Greenhouse boards for customers routing applications through RippleMatch. This makes such a configuration plausible in general, but does **not** confirm HubSpot changed its board or explain its current upstream 404.

### Validation against real HubSpot job links (2026-10-07)

HubSpot Emerging Talent's [official software-engineering application post](https://www.linkedin.com/posts/hubspot-students_emerging-talent-software-engineering-application-activity-7426647535097778176-9bfn) links [USA applications](https://app.ripplematch.com/t/16e8620e) and [Canada applications](https://app.ripplematch.com/t/87a54ac8). These resolve to public IDs `ada1428b` and `90098ffb`. They are historical links, not proof that applications remain open.

Anonymous browser checks and independent requests without cookies verified HTTP 200 JSON details from [USA detail API](https://app.ripplematch.com/api/v2/direct-apply/ada1428b) and [Canada detail API](https://app.ripplematch.com/api/v2/direct-apply/90098ffb). Both identify `companyId: 708`, the expected `publicId`, and a `roleUuid`. Both also return `isDisabledRole: true`; the browser displays that the job is not open for applications. Therefore neither can validate discovery of a currently active role.

| Observed field | USA | Canada |
| --- | --- | --- |
| `overview.name` | Software Engineering Intern + Co-op, USA (2026) | Software Engineering Intern + Co-Op, Canada (2026) |
| `overview.datePosted` | Mar 06, 2026 | Feb 17, 2026 |
| `overview.jobType` | Internship | Internship |
| `overview.employmentType` | Full Time | Full Time |
| `overview.locationType` | Remote | Remote |
| `roleLocationsList.locations[].city` | Cambridge, MA, USA | Toronto, ON, Canada |

This supersedes the earlier uncertainty about whether a detail posting-date field exists. The observed date is a date-only display string, with no timezone; its publication/freshness semantics remain unverified. `startDate` contains internship seasons and is not a posting date. `deadline` is null in these samples. Real descriptions are present in `roleDescription`; a reliable required-degree field was not established.

The [public apply command module](https://static.ripplematch.com/js/distribution/assets/PublicApplyFlow.commands.DutfXZry.v1.js) defines the read-only `/api/v2/direct-apply/{publicId}` route. The [public apply page module](https://static.ripplematch.com/js/distribution/assets/PublicApplyFlow.page.C_rkeLD4.v1.js) blocks applications for `isDisabledRole`. Its separate `trackingLinksDisabled` and `cbpLinksDisabled` flags govern their respective entry paths rather than proving global closure. A successful HTTP response alone cannot establish an open job. No applications were submitted and no account was created.

The public company-role feed still returned `[]`. These known closed roles demonstrate that details remain retrievable by ID after closure; they do not demonstrate that the feed discovers current internships or all roles. No current active HubSpot role was independently validated against that feed, so no adapter was enabled. The next evidence needed is an official active role link appearing in the public list with matching identity/details and an enabled application state; private-role coverage would remain excluded even then.

The [official Emerging Talent LinkedIn feed](https://www.linkedin.com/company/hubspot-students/) also has a 2027 Spring Co-op announcement with applications closing Monday, September 28 in the morning. That deadline precedes this October 7 investigation. Underlying role IDs were not retrieved; search-index wording that applications are open is not current active-role evidence.

## NVIDIA: the failed detail recovered; add bounded transient retries

### Verified live behavior

On 2026-10-07, three consecutive requests to the [exact previously failing official Workday detail endpoint](https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Research-Intern--Efficient-Deep-Learning---2027_JR2025478) returned HTTP 200 and JSON in 0.43s, 0.40s and 0.75s. The response identified requisition `JR2025478`, **Research Intern, Efficient Deep Learning - 2027**, with `posted=true` and `canApply=true`. The existing parser extracted a PhD requirement; existing classification correctly excluded it from undergraduate announcements.

A complete regular filtered fetch then succeeded using the configured `Intern (Fixed Term)` filter: 133 search rows, 110 title-eligible detail requests, 110 parsed postings and 10 announceable roles. Search took 5.72s, details 21.36s and the whole NVIDIA fetch 27.09s. This was one local read-only poll, not a GitHub-runner timing guarantee or a new filter coverage audit. The reproducible entry points are `fetch_workday`, `parse_workday` and `classify`; no Discord messages or persistent state writes were performed.

HTTP 502 means a gateway received an invalid upstream response ([HTTP semantics, section 15.6.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6.3)). Recovery is consistent with a temporary gateway/upstream error. It does **not** identify the exact cause or establish its frequency, and the original error was not reproduced during these checks. This job is currently accessible; treating the failed detail as a closed job would have been incorrect.

### Current behavior and recommendation

[`get_json`](../src/intern_alerts/sources/__init__.py) issues one GET and raises `SourceError` on HTTP or JSON failure. [`fetch_workday`](../src/intern_alerts/sources/workday.py) requires all selected detail requests to succeed. A single unresolved failure therefore rejects that board for the poll, preserving the [recorded completeness and silent-initialization rules](plan.md). Other boards can continue.

Recommended follow-up: allow **one bounded retry** for transient detail-read failures, such as HTTP 502/503/504 and transport/timeouts, retaining at most four concurrent requests. If the retry still fails, reject the board as today. Do not turn missing/malformed metadata into an empty result, retry deterministic parsing failures, or add persistent partial-scan state. Treat this as a Workday detail-fetch change with explicit tests for recovery, persistent failure and preserved silent initialization, rather than enabling broad automatic retries on every source.

No adapter/configuration changes were made during the research itself. The user subsequently authorized the retry follow-up. It is implemented in Workday detail fetching: one retry after 0.5s for HTTP 502/503/504 or transport failures, within the same four-worker pool. Search requests and JSON/metadata validation do not retry; persistent failures still reject the board. All 376 tests pass, including simulated recovery, retry exhaustion, concurrency and silent-initialization behavior. A read-only live NVIDIA fetch verified 133 search rows, 110 details and 10 eligible roles in 19.99s; no transient failure occurred, so retry execution is test evidence rather than live evidence. No messages or state writes during validation. The retry is subsequently pushed on `1c2f14d`; [GitHub Tests run 37671774102](https://github.com/alexypeng/swe-intern-alerts/actions/runs/37671774102) passed. A scheduled source fetch on that commit has not yet been inspected.
