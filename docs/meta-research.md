# Meta careers research

Checked 2026-10-05. **Current state:** the sitemap approach below was superseded by a locally implemented and verified public search GraphQL adapter with dynamically discovered operation IDs. Meta is deployed on `5a804ac`; GitHub-runner fetch/classification succeeded in run `37400514018`. See the final section for current evidence. Earlier sections preserve the investigation history and are not the current implementation contract.

## Initial conclusion (historical; superseded)

The strongest inspected implementation discovers Meta jobs through its public XML sitemap and extracts structured `JobPosting` data from individual pages. Investigate that route before implementing the rotating GraphQL approach recorded in the plan. This is a proposed change of approach, not an accepted implementation decision.

Open-source support claims need source inspection: one scraper assumes a Next.js response without pagination, another uses bounded browser scrolling without proving completeness, and a third has explicitly removed direct Meta tracking.

## Inspected repositories

| Repository | Actual source behavior | Implication for this project |
| --- | --- | --- |
| [colophon-group/jobseek](https://github.com/colophon-group/jobseek/blob/87ceae8dadae7177b5b282bc960b358c706144a7/apps/crawler/data/boards.csv) | Its `meta-careers` board uses the sitemap monitor, filters URLs containing `/profile/job_details/`, and uses the JSON-LD scraper with browser rendering, `networkidle`, and a 45-second timeout. | Strongest starting point. Discovery avoids search-page pagination and GraphQL document IDs. Its rendering setting does not prove every detail page requires a browser. |
| [ever-jobs/ever-jobs](https://github.com/ever-jobs/ever-jobs/blob/57399c8500211e1ce57b5fbfc5e4d2b2de58b33d/packages/plugins/source-company-meta/src/meta.service.ts) | GETs `/jobs?q=…&location=…`, searches HTML for `__NEXT_DATA__`, and reads `props.pageProps.jobs` or `initialJobs`. Returns at most `resultsWanted`, default 50. Its declared GraphQL endpoint is unused. | No pagination or total verification; absent embedded data returns an empty result without a failure. This code is not evidence of complete or currently working Meta coverage. |
| [internship-scanner/internship-scanner](https://github.com/internship-scanner/internship-scanner/blob/main/scraper/adapters/custom_modules/meta.py) | Playwright navigation, cookie dismissal, up to 15 scrolls, 10 “Show more” clicks, and 10 more scrolls; then reads currently present `/jobs/` anchors and deduplicates URLs. Docstring gives `roles[0]=Internship`; navigation uses the configured careers URL. | Concrete browser approach and native-filter lead, but no result-total check. It does not collect cards after each scroll. Dynamic lists that discard old DOM nodes could defeat this approach; that risk was not tested here. |
| [zaccesss/isaac-adjei-automations](https://github.com/zaccesss/isaac-adjei-automations/blob/main/scraper/sources/faang.py) | Current source deliberately excludes Meta. Its explanation identifies Relay GraphQL with rotating persisted IDs and uses Trackr as the internship fallback. | Useful maintenance evidence. The old portfolio documentation advertising a Meta Playwright scraper no longer describes current implementation. |

Jobseek's [sitemap monitor](https://github.com/colophon-group/jobseek/blob/87ceae8dadae7177b5b282bc960b358c706144a7/apps/crawler/src/core/monitors/sitemap.py) explicitly documents Meta's `/jobsearch/sitemap.xml`: its observed Chrome user agent received HTTP 400, while a crawler user agent obtained XML. The monitor supports sitemap discovery and traversal; the pinned board configuration supplies Meta's exact URL. This is repository evidence, not a guarantee that user-agent behavior will remain unchanged.

The internship scanner's [browser helpers](https://github.com/internship-scanner/internship-scanner/blob/main/scraper/adapters/custom_modules/__init__.py) stop scrolling when document height stops changing, stop clicking on errors or a missing button, and turn navigation failures into `False`. The Meta module then returns `[]` on failed navigation. Our pipeline must distinguish a fetch failure from a genuinely empty successful board so silent first-poll state cannot initialize from a failed scrape.

Other candidates were weaker: [isscottw/MetaCrawler](https://github.com/isscottw/MetaCrawler) describes Puppeteer, but its inspected public tree contains only a README, so its claimed implementation was not verifiable. Aggregated internship lists can include Meta without implementing a direct Meta fetcher.

## Read-only live checks

Local HTTP checks used a self-identifying research user agent, without login credentials, browser automation, Discord sends, or state writes.

- [Meta's sitemap](https://www.metacareers.com/jobsearch/sitemap.xml) returned HTTP 200, XML, and 1,075 unique job URLs in one `urlset`. All matched `/profile/job_details/<numeric ID>/`.
- Three sitemap detail URLs returned HTTP 200 through plain HTTP. Each contained one `JobPosting` JSON-LD block with title, ISO timestamp with offset, structured location arrays, description, qualifications, and employment type.
- Samples were [Security Engineer, Nation State](https://www.metacareers.com/profile/job_details/1126735619851519/), [Software Engineer - Product (Technical Leadership)](https://www.metacareers.com/profile/job_details/4043567932553615/), and [Network Engineer, Deployment & Support](https://www.metacareers.com/profile/job_details/769709699353828/). These were not internship samples.
- JSON-LD `identifier.value` was an alphanumeric requisition-like ID, distinct from the numeric URL ID. Identity and URL canonicalization need validation against existing Simplify records before choosing an adapter ID.

These checks establish accessibility and inspectable fields for three pages on the local connection. They do not establish that the sitemap includes every currently searchable internship, how quickly newly posted jobs enter it, whether closed listings disappear promptly, or accessibility from GitHub Actions runners. No GraphQL request or complete detail sweep was performed. A sitemap count is not an independently verified board total.

## Suggested next validation (historical)

1. Compare known current internships from Meta search and Simplify with sitemap IDs. Repeat after new postings appear to measure sitemap delay. Treat Simplify as corroborating evidence rather than an exhaustive reference.
2. Fetch representative internship details, including undergraduate, graduate-only, multiple-location, and remote roles. Check title, description/qualification requirements, date, IDs, and local eligibility mapping. Do not infer internship status from the three full-time examples.
3. Probe the same public requests from the intended GitHub runner. Add browser dependencies only if evidence makes them necessary.
4. Define complete-poll validation and bounded fetch concurrency before implementation. The sitemap currently has URLs only; fetching every detail each poll could recreate an expensive N+1 bottleneck. Any caching proposal needs an explicit design for changing descriptions and previously ineligible roles.

If sitemap coverage or freshness is insufficient, investigate browser-observed search requests and discover current tokens/document IDs rather than copying a fixed GraphQL ID. The inspected repositories do not establish a robust direct GraphQL solution or verified native internship-filter completeness.


## Sitemap freshness investigation (2026-10-05)

**Finding:** the live sitemap changes and its HTTP response discourages caching, but first-poll detection after publication remains unverified. No primary-source statement of Meta's generation cadence or a measured search-to-sitemap delay was found in the inspected repositories or searches. Jobseek's own monitoring cadence is not Meta's update cadence; its [monitor documentation](https://github.com/colophon-group/jobseek/blob/87ceae8dadae7177b5b282bc960b358c706144a7/docs/04-monitors-and-scrapers.md) also warns that sitemap discovery can omit job URLs.

### Live observations

- Earlier snapshot: 2026-10-05 14:26:42 UTC, 1,075 URLs. Two new snapshots at 19:11:03 and 19:11:04 UTC each had 1,084 URLs: 17 added and eight removed compared with the earlier snapshot. These observations demonstrate that the list changed during the roughly 4h44m interval; they do not locate any change within that interval.
- Both responses from [Meta's sitemap](https://www.metacareers.com/jobsearch/sitemap.xml) included `Cache-Control: private, no-cache, no-store, must-revalidate` and an expired `Expires` date. No Age, ETag or Last-Modified response header was observed. This is evidence against ordinary HTTP-cache reuse, not proof that Meta's upstream job dataset is updated immediately.
- Every entry had the same `lastmod`: 12:11:03-07:00 in the first new response and 12:11:04-07:00 in the second. The URL sets were identical while the body hashes differed. The earlier snapshot also assigned its request-time value to all URLs. **Inference:** these values behave like response-generation timestamps, not individual job modification or first-sitemap-appearance times. Do not use them for notification ordering or freshness measurements. The [Sitemap protocol](https://www.sitemaps.org/protocol.html#xmlTagDefinitions) defines page-level lastmod as the linked page's modification date, not sitemap generation time.
- Six newly observed URLs had inspectable job details. One was [Electrical Engineering Intern](https://www.metacareers.com/profile/job_details/1105729655266553/), with JSON-LD `employmentType: INTERN` and `datePosted: 2026-10-05T10:25:59-07:00` (17:25:59 UTC). It was present in the 19:11 sitemap check, about 1h45m after its stated posting time. **That is an observation interval, not a measured 1h45m delay:** there was no sitemap observation between its stated posting time and this check, and `datePosted` itself has not been verified as the exact opening time.
- Other sampled added URLs had older stated posting dates, ranging from September 2 to October 3. Relisting, previously incomplete sitemap coverage, and differences between stated posting dates and current publication are possible explanations. We did not establish which explanation applies; these records do not prove days-long sitemap lag.

### Decision implication for the sitemap approach

Do not promise detection on the first 20-minute poll from this evidence. Sitemap discovery remains promising, but neither HTTP caching headers nor a fresh-looking lastmod proves immediate backend inclusion. To measure the extra discovery delay, independently snapshot official search results and the sitemap every few minutes during actual new postings, record first-seen intervals for matching numeric job IDs, and repeat across multiple postings (including internships). Until then, the expected delay is the unknown publication-to-sitemap delay plus our normal polling/scheduling delay. No monitor or production adapter was enabled by this investigation.


## Sitemap implementation validation (historical; superseded)

The earlier sitemap adapter was implemented with four concurrent detail requests, one retry on failure, shared title/structured-employment classification, and numeric URL IDs. Verified jobs/profile aliases normalize to one identity. Merged qualification text does not establish required degree restrictions. No cache/state-schema changes.

Complete live scans repeatedly failed on `1771434380856457`: HTTP 200, no JobPosting JSON-LD, generic Meta Careers title, and an embedded SSR error. The `/jobs/` alias redirects to the same failing page; `classic_view=true` and `classic_view=1` also yielded no details. This is a second rollout limitation beyond unknown sitemap publication delay. At that stage the adapter rejected the whole board rather than silently omitting that URL and stayed disabled pending complete-scan and runner validation. The search-based adapter below supersedes it. No Discord messages or production-state changes occurred during probes.

At that stage, 285 tests passed, including real internship field structure, sitemap validation, bounded concurrent fetching, failed/redirected details, retry recovery, silent first poll, and Meta/Simplify URL deduplication.


## Browser-rendering test (2026-10-05; historical snapshot)

User authorized testing the reference configuration's browser-rendered JSON-LD extraction. Used Playwright 1.63.0 with installed Chrome, headless and a fresh browser context, `networkidle`, and 45-second navigation timeout. Dependencies and HTML/screenshots/results were stored under `/private/tmp`, with no project dependency or runtime changes. Chromium download failed; installed Chrome supplied the browser instead. This is a local Chrome test, not the exact browser/version or deployed environment used by Jobseek.

| Public job ID | HTTP status | Network idle | Navigation/extraction time | Rendered JSON-LD | Visible result |
| --- | --- | --- | --- | --- | --- |
| 1771434380856457 | 200 | reached | 6.16s | none | Electrical Engineering Intern, full description, minimum/preferred qualifications, Apply now button; no location shown in captured header |
| 1105729655266553 | 200 | reached | 2.47s | one JobPosting | Electrical Engineering Intern, Sunnyvale plus one location, full details |

At that time, the failing page rendered a job listing; absent JSON-LD was not evidence of closure. Browser rendering did not make that page compatible with the JSON-LD parser, while the control page parsed successfully. No full-board browser scan was attempted. These two samples do not establish complete coverage, runtime, runner access, or freshness.

This snapshot motivated investigation of browser-received data and search requests. It did not justify treating missing JSON-LD as closure or assuming browser rendering would generate it. The resulting HTTP search approach is described below.

## Current solution: public search requests with dynamic operation discovery

The user reopened the design because the uncommitted sitemap adapter was not established as correct, requested alternatives, and authorized finding and implementing a working solution. Browser observation of [Meta's public job search](https://www.metacareers.com/jobsearch/) identified the site's own `POST /graphql` requests. Fresh ordinary HTTP requests successfully replayed them locally, without login or a runtime browser.

### Verified public response behavior

- `CareersJobSearchResultsV2DataQuery` returns the complete observed unfiltered set in `data.job_search_with_featured_jobs_v2.all_jobs`, despite the UI displaying ten rows at a time. One captured response contained 1,084 unique jobs; a later complete adapter run contained 1,086. The response does not itself supply an independent total.
- `CareersJobSearchHideFiltersBarV2Query` supplies `job_count`. An unfiltered count request independently returned 1,084 for the captured 1,084-row search. The implemented poll reads the count before and after fetching candidate details and requires the same count, exact list length, and unique IDs. This rejects observed changes in count or malformed/partial results; equal counts cannot prove an unchanged set when additions and removals cancel.
- Fresh page bootstrap supplies the `LSD` token. HTTP replay worked with form fields including the fresh token, current `doc_id`, variables and operation metadata, plus `X-FB-LSD`. The adapter discovers IDs each poll rather than storing the observed numeric IDs as its contract.
- Bootstrap discovery is bounded to the resources associated with `Bootloader`'s `compMap['CPJobSearch.react']`. Resource URLs come from the aggregate `rsrcMap` and initially preloaded script/link attributes. Six referenced resources resolve to five JavaScript assets and one stylesheet. Both required operation IDs are exported by exactly named `*_candidate_portalRelayOperation` modules in the search asset, and the corresponding `.graphql` modules reference those exports. Looking only for an inline `params.id` misses this current representation.
- The five assets totaled roughly 7.5 MB, including a roughly 5.6 MB search bundle. A local asset probe fetched them in less than one second. This is a one-machine observation, not a runner bandwidth or timing guarantee.
- A comparison showed 1,085 sitemap URLs against 1,084 search jobs, with sitemap-only ID `1690022942358388`. The previously problematic `1771434380856457` had disappeared from search and subsequently from the sitemap; a later browser visit explicitly showed unavailable. Its earlier rendered listing remains valid historical evidence. Missing JSON-LD alone still cannot establish closure.
- Native `roles = Internship` returned eleven records, matching the observed internship title/team signals in the unfiltered set. The implementation uses the complete unfiltered list, avoiding reliance on the filter's future completeness. It selects candidate details using current title/team internship signals and shared undergraduate rules, then requires successful JSON-LD details and shared channel/region classification.

The live adapter verified 1,086 search rows and nine candidate details in 4.84 seconds. All nine details parsed through plain HTTP. A full CLI dry poll succeeded on all 54 sources in 24.27 seconds; Meta took 5.37 seconds. These runs sent no messages and saved no state. The regression suite passed all 300 tests. Meta is enabled only in local configuration; no commit, push or deployment occurred. A read-only manually dispatched runner-validation workflow is prepared for verification after the user commits and pushes.

### Manual full-detail coverage audit

A later one-time audit fetched every job in a 1,089-row search, with independent counts of 1,089 before and after. It took 159.92 seconds. Of those details, 1,084 parsed successfully and produced the same four announceable postings as the candidate-only adapter; no additional eligible posting was found among parseable pages. Five details lacked JobPosting JSON-LD: `691715269835265` (Product Manager, Machine Learning), `1286818323298472` (Research Scientist, FAIR SGT - Paris), `1064155186370895` (Data Center Campus Facility Manager), `3492253594282417` and `2358713911326793` (Warehouse Operations Manager). None had an internship title/team signal in the search snapshot. Their missing JSON-LD leaves their complete metadata unverified; this is corroborating coverage evidence, not proof that no unlabelled internship can exist. Requiring all details would reject the board on these five pages. Candidate-only fetching still requires every selected detail and rejects rather than silently drops any selected failure. A fresh candidate-only run verified 1,089 rows/nine details in 5.12 seconds before this audit.

### Alternative assessment

| Route | Evidence and practical tradeoff |
| --- | --- |
| **Public search GraphQL with current IDs discovered from assets** | Working locally and implemented. One bootstrap, five asset requests, one full search, two count checks, and candidate-only details: eighteen requests for nine candidates before retries. Discovery survives numeric ID rotation, but private operation/module names, bootstrap maps and response fields can still change. GitHub-runner access subsequently verified in run `37400514018`. |
| **Sitemap plus every detail** | Public discovery works and [Jobseek's board configuration](https://github.com/colophon-group/jobseek/blob/87ceae8dadae7177b5b282bc960b358c706144a7/apps/crawler/data/boards.csv) uses this route. Current evidence includes sitemap-only/stale entries and unavailable structured details. Around 1,085 details per poll makes it far more expensive; sitemap inclusion delay remains unknown. Superseded as the primary route. |
| **Plain HTML/SSR or embedded data** | Inspectable JSON-LD works for current candidate details. Failed raw detail HTML lacked the full job object; rendered HTML had Relay `xcp_requisition_job_description`, including an empty location array. The inspected pages are not supported by the assumed `__NEXT_DATA__` parser. A generic SSR/DOM fallback needs its own identity/location/date validation before use. |
| **Browser-observed responses** | Useful for discovery and diagnostics: revealed the exact search request and complete list. Could rediscover operation IDs if static bootstrap discovery breaks. Runtime adoption would add browser setup, memory/startup cost and runner verification; current HTTP path does not require it. |
| **Browser DOM scrolling** | [Internship scanner's implementation](https://github.com/internship-scanner/internship-scanner/blob/main/scraper/adapters/custom_modules/meta.py) uses bounded scrolling/clicking. The complete observed network array is stronger than the ten-row UI; bounded interaction alone does not prove coverage and DOM virtualization can lose earlier rows. No validated production DOM solution was found. |
| **Aggregators** | Existing Simplify fallback continues to provide independent coverage. [Isaac Adjei's current scraper](https://github.com/zaccesss/isaac-adjei-automations/blob/main/scraper/sources/faang.py) explicitly abandons direct Meta scraping for an aggregator. Aggregators add their own delay and coverage rules and do not establish Meta's official board total. |

An additional primary implementation report, [Fetchaller's SPA discovery notes](https://github.com/Averyy/fetchaller-mcp/blob/main/wafer-feedback.md), describes observing Meta's requests and replaying plain HTTP with dynamically sourced LSD and operation IDs on August 1, 2026. That report corroborates the mechanism; our October live probes establish the current local behavior. Its reported job count is a historical sample, not our board total.

### Remaining limits

Search uses the site's own currently exposed job dataset, removing the extra sitemap-discovery step, but no publication-to-search latency guarantee was found. A twenty-minute polling schedule still includes scheduler/runner delay. Required query discovery, counts, uniqueness and candidate detail failures reject the whole board, preserving silent first-success behavior. A future internship with neither a recognized title nor team signal could be missed by candidate selection; native-filter matching in one snapshot does not prove future coverage. Monitor label/schema changes and perform manual coverage checks when Meta's UI or internship conventions change. The private GraphQL interface is not a documented stable public API, and the successful runner check establishes one observed fetch/classification run rather than ongoing reliability.


## Changeset cleanup

Removed the unused sitemap parser and its seven obsolete parameterized validation cases from production code/tests. Sitemap observations remain research evidence. The retained search adapter and regression suite pass 293 tests; the earlier 300-test result included those seven sitemap cases. Consolidated current Meta decisions and status in `plan.md` without retaining contradictory rollout instructions.

## Role classification correction

The user's 11-internship snapshot contains two PhD-titled exclusions and nine candidates. Five were fetched but initially dropped for having no channel match. The captured official descriptions establish [Production Engineer](https://www.metacareers.com/profile/job_details/1609178343953401/) as software infrastructure/reliability work and [Network Production Engineer](https://www.metacareers.com/profile/job_details/1412139847020398/) as network automation/production software: both now map to SWE. [DFX Engineering](https://www.metacareers.com/profile/job_details/1095054769939445/) means Design for Excellence, covering manufacturing processes, fixtures, mechanical tolerances and yield/failure analysis; the user selected Other Engineering. All five postings include bachelor's students. These mappings apply only to Meta. The earlier four-announceable audit results above predate this correction.

Verification: three regression cases reproduce the missing channels before the fix and pass afterward, including guards against applying these mappings to other sources. All 296 tests pass. Replaying the captured search and official candidate details now yields nine announceable postings and two graduate-title exclusions. No messages or persistent-state changes occurred.

## GitHub-runner verification

[Validate Meta source run 37400514018](https://github.com/alexypeng/swe-intern-alerts/actions/runs/37400514018) succeeded on deployed commit `5a804ac`. The source verified 1,089 search jobs and fetched nine candidate details in 3.16 seconds; all nine were announceable, including DFX and both regional Production/Network Production Engineer postings. This check sent no Discord messages and saved no state. Scheduled polling/state initialization were not inspected.


## Simplify degree-label bypass and fix (2026-10-07)

User reported [job 2180490782513668](https://www.metacareers.com/profile/job_details/2180490782513668/). Official JSON-LD title is `Software Engineer Intern, Machine Learning (PhD)` and the qualifications explicitly require PhD enrollment. Direct classification correctly excludes this title. Public state instead contained Simplify ID `e458bd10-4f0d-449d-9f51-dcb595087eb9`, first seen 2026-10-06T23:20:35Z. The corresponding Simplify row used `Software Engineer Intern - Machine Learning`, degrees `[]`, and the same Meta job URL. Its replay reproduced an eligible SWE result. Excluded direct jobs are not recorded, so deduplication did not reject that fallback copy.

The fix verifies eligible Simplify Meta URLs against official JSON-LD and replaces titles before shared classification. It preserves fallback identity, URL, date, degree metadata, locations and category. This works for links absent from current search and when Meta direct polling is unavailable/unconfigured. Four requests maximum, one retry, aliases fetched once per poll. Missing/invalid data or a wrong-ID redirect defers the entire Meta fallback company without initializing it; other fallback companies proceed. No blacklist/cache/state change or interpretation of merged qualification text. Official titles lacking degree restrictions remain a limitation.

Regression initially sent the PhD-only job; after correction, no message or state record. Live read-only replay confirmed original fallback announce=True, official-title fallback announce=False. The suite passes 361 tests, including aliases/identity preservation, retry, invalid/redirected details, failure isolation and silent recovery. No Discord sends, production-state updates, commits or deletion of historical records.

Complete configured dry poll: Meta direct search verified 1,108 jobs / 13 candidates in 7.03s; Simplify including official-title verification completed in 2.62s without a Meta deferral. Total fetch 29.08s. HubSpot returned 404 and one NVIDIA detail returned 502, so those unrelated boards were omitted; no claim of all-source success. Dry run wrote no state and sent no messages.
