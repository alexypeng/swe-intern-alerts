# Workday adapter investigation

Checked 2026-10-05. Salesforce's adapter and NVIDIA's verified category partitions are implemented locally. Earlier observations below record the investigation that informed these changes. The agreed pagination failure policy is in `plan.md`; NVIDIA expansion evidence is in `nvidia-workday.md`.

## Verified source behavior

Probed the companies' public Workday endpoints directly. These are observed responses, not a documented Workday API contract.

- Search: POST `https://<host>/wday/cxs/<tenant>/<site>/jobs` with JSON `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}`.
- Detail: GET the same base followed by a search row's `externalPath`.
- Search rows contain `title`, `externalPath`, `locationsText`, relative `postedOn`, and `bulletFields` containing a requisition ID in these samples.
- Detail responses contain `jobPostingInfo`, including `jobReqId`, `title`, `externalUrl`, `startDate`, `location`, and optional `additionalLocations`. Observed `timeType` is `Full time` even for internships; it is not an internship signal.
- The detail `startDate` is consistent with the displayed posting age in the inspected samples (e.g. 2026-08-31 for a summer 2027 internship displayed as posted 30+ days ago). Proposed use: date-only publication date interpreted as UTC midnight. This mapping still needs validation on additional tenants before expanding coverage.

Primary endpoints: [Salesforce search](https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/Futureforce_Internships/jobs), [NVIDIA search](https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs), [NVIDIA software internship detail](https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/NVIDIA-2027-Internships--Software-Engineering_JR2023495).

### Complete small-board validation

Salesforce's `Futureforce_Internships` board reported 23 postings. Requests at offsets 0 and 20 returned 20 and 3 unique paths. The second page reported `total: 0`, despite containing three jobs. Retain the initial total rather than interpreting each page's total as the board size.

Fetched details for all 23 jobs: all had nonempty `jobReqId`, `title`, `externalUrl`, `startDate`, and `location`. Mapping those fields into the existing `Posting` shape and running the existing classifier produced one announceable SWE posting, `JR340771`, with eight US locations. Other postings did not meet the current internship/degree/channel/region rules. This is a live mapping probe, not a test of a production adapter.

### Initial large-board completeness blocker

NVIDIA's unfiltered search reported `total: 2000`; job-type facet counts added to 2678. Offset 1980 returned 20 jobs. Offsets 2000 and 2020 returned the first page again, with total 2000. These observations suggest a result-window cap; completeness of the unfiltered response is not established.

A server-side `intern` search also returned an `International` title. Search text is not a reliable internship classifier. Restricting to one search word could also omit co-ops or other eligible titles; it is not a verified completeness solution.

Proposal: start with the smaller Salesforce internship board. Before adding NVIDIA, investigate complete facet partitions or another verified source path. Repeated pages, early empty pages, and a capped result window must fail the board fetch rather than silently mark it initialized.

## Cross-source duplicates

The NVIDIA systems internship `JR2023492` has identical direct and active Simplify URLs; the current normalizer matches them. The software internship `JR2023495` also had identical URLs, but its Simplify row was inactive, so it is evidence of URL format rather than current fallback coverage.

Salesforce's `JR340771` has two active Simplify URLs:

- [Futureforce internship site](https://salesforce.wd12.myworkdayjobs.com/Futureforce_Internships/job/California---San-Francisco/Summer-2027-Intern---Software-Engineer_JR340771)
- [External career site](https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/California---San-Francisco/Summer-2027-Intern---Software-Engineer_JR340771-1)

Direct detail requests for both return the same requisition ID, title, date, and location list. Existing URL normalization matches the first URL but not the second. Simplify uses its own UUID and a shortened title, so identity and field comparisons are not dependable substitutes.

Agreed decision: treat these career-site copies of the same tenant and requisition as one job. Implemented narrowly scoped Workday URL normalization based on tenant and the observed `JR` plus numeric requisition suffix (with an optional numeric copy suffix), leaving unknown formats distinct. Keep the original application URL for display. Existing stored URLs are normalized while building the seen index so historical Simplify records also match; resetting state would undermine silent first polls. Verify additional requisition formats before extending the normalization.

Source: [Salesforce external-site detail](https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/job/California---San-Francisco/Summer-2027-Intern---Software-Engineer_JR340771-1) and [Simplify's listings](https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json).

## First implementation

1. Support Workday board addresses: host, tenant, and career-site ID. Fit this into `Board` configuration with a validated Workday host and a `tenant/site` slug; other source configuration keeps its current shape.
2. Add `sources/workday.py`: POST paged search, use the initial total, validate unique results and completeness, fetch required detail responses, and produce shared `Posting` objects. Any required page/detail failure raises `SourceError` and returns no partial board result.
3. Fetch unfiltered lists and every detail for the small board, preserving full locations. This deliberately avoids adding a second filtering path to the adapter; the existing classifier handles internship, degree, channel, and region checks. Final duplicate decisions remain in the existing dedup module.
4. Add verified Workday URL normalization and compatibility with stored URL records, following the agreed requisition-copy decision above.
5. Wire the fetcher into `main.py` and add only Salesforce `Futureforce_Internships` for the first rollout. A newly added board keeps its silent first poll.

Verification should cover: 20+3 pagination with a zero later total; unique-count mismatch/repeated/early-empty pages; a later-page failure leaving the board unpolled; required detail failures; exact date and multiple locations; full-time-labelled internship titles; graduate-only exclusions; both cross-site URLs matching historical state; different tenants/requisitions staying distinct; and silent first-poll behavior. Run the existing suite and a dry run before rollout.

No Discord messages were sent and no application state was saved during this investigation. The live Salesforce detail probe took about eight seconds; this is one-board evidence, not a runtime guarantee for expanded coverage.

## Implementation verification (2026-10-05)

- Salesforce is configured as the first direct Workday board. NVIDIA remains on the existing fallback.
- Search retains the initial total and validates every page, unique paths, and the final count. A count of 2,000 or more is rejected conservatively because completeness cannot be established at the observed cap. HTTP/JSON errors, invalid required detail fields, and postings that become unavailable fail the entire board fetch.
- Details supply the requisition ID, title, original URL, full location list, and date-only publication date in UTC. Internship and undergrad filtering stays in the shared classifier.
- Live dry run of the implemented pipeline: 23 Salesforce jobs fetched; one eligible SWE internship recorded silently; two active Salesforce Simplify copies skipped by URL. Exit status 0, with no Discord sends or state-file writes.
- Regression tests cover pagination, malformed results, detail failure, eligibility and regions, historical cross-site URLs, distinct tenants/requisitions, and failed-first-poll recovery followed by new-job announcements.
- Final full suite: 201 tests passed.

## NVIDIA expansion

The initial capped-list blocker is resolved for the observed NVIDIA board with opt-in category partitions. Every category and its required pages must succeed, category coverage must agree with independent time-type counts, and the complete union must have the expected number of unique paths. A capped category or changed coverage fails the board. Configured partition boards prefilter detail requests with shared title eligibility rules after scanning every category; the small Salesforce board retains full detail validation.

The user additionally approved description-based education checks after a confirmed NVIDIA graduate-only role passed title checks. Explicit graduate-only requirements are now excluded through the existing degree classifier, while bachelor's alternatives remain eligible. See [NVIDIA validation](nvidia-workday.md) for primary evidence, implementation controls, live dry-run results, and the final 231-test suite.
