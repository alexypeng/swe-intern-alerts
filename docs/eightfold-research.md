# Eightfold source research

Research snapshot: 2026-10-09. This is research only; no adapter, board configuration, or classifier changes have been made.

## Recommendation

Start with **PayPal**, already approved in `config.toml`'s fallback company list, using its current public PCSx frontend search API. Anonymous search and field mapping work. Complete-board pagination, current internship coverage, dates on details, Simplify alias identity, and GitHub-runner access still need validation before implementation. Do not use the documented authenticated customer API for anonymous polling, and do not assume an old public endpoint or another tenant has the same access behavior.

## Sources and access evidence

The current [PayPal careers tenant](https://paypal.eightfold.ai/careers?domain=paypal.com) returned anonymous HTTP 200 using a plain GET without credentials or retained cookies. Its HTML bootstraps `domain=paypal.com` and loads the shared [PCSx frontend JavaScript](https://paypal.eightfold.ai/gen/js/pcsxPwa.fa5d073d8912644a.js). The same bundle was downloaded from [Qualcomm's first-party careers host](https://careers.qualcomm.com/gen/js/pcsxPwa.fa5d073d8912644a.js); PayPal HTML references precisely that bundle path/hash. Qualcomm is illustrative platform evidence, **not an approved company addition**.

The bundle constructs `GET /api/pcsx/search` with `domain`, `query`, `location`, `start`, optional `sort_by`, repeated `filter_<name>` parameters, and optional `hl`. It reads `data.count`, `data.positions`, `filterDef`, and `resultsMetaData`. It also calls `/api/pcsx/position_details?position_id=<numeric-id>&domain=<domain>&hl=en`. These are observed private frontend contracts, not a documented stability guarantee. [Frontend source](https://careers.qualcomm.com/gen/js/pcsxPwa.fa5d073d8912644a.js).

A live anonymous [PayPal search request](https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com&query=&location=&start=0&sort_by=timestamp) returned HTTP 200, an envelope with `status`, `error`, `data`, `metadata`, count **303**, and **10** positions. Returned `sortBy` was `timestamp`, and `resultsMetaData.usedFuzzSearch` was false. Only offset zero has been verified so far. The legacy `/api/apply/v2/jobs` route returned HTTP 403 in a separate parent-agent probe; this does not invalidate the working PCSx endpoint or establish that the legacy route always blocks.

Eightfold's documented [List Positions API](https://apidocs.eightfold.ai/reference/list_position) requires Authorization. The [authorization guide](https://apidocs.eightfold.ai/docs/eightfold-api-authorization-guide) describes customer administration and API keys/permissions. Treat this as a different API from public careers search.

Intel is approved but was **not verified as an Eightfold tenant**: a speculative `intel.eightfold.ai` hostname failed DNS both inside and outside the sandbox. First-party [Intel job pages](https://intel.wd1.myworkdayjobs.com/en-US/External/job/Process-Integration-and-Yield-Intern_JR0282666) show Workday. A guessed hostname failure is not evidence that Intel has no Eightfold services; it is sufficient reason to avoid designing an Intel Eightfold board from that guess.

## Observed search fields and proposed Posting mapping

The following example is a senior role used solely to inspect schema; it is not an internship candidate. [Live response](https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com&query=&location=&start=0&sort_by=timestamp).

| Posting responsibility | Observed field/example | Proposed handling / remaining validation |
| --- | --- | --- |
| Company | Tenant `paypal.com` | Configured display name `PayPal`; preserve fallback company normalization. |
| ID | `id=274922258196`; `atsJobId=R0137335`; `displayJobId=R0137335` | Use numeric public position identity provisionally; verify its persistence and Workday/application aliases before deciding requisition-based identity. |
| Title | `name=Sr. Director, EU Payment Operations & Strategy` | Preserve source title and shared title/degree policy. |
| Application URL | `positionUrl=/careers/job/274922258196` | Resolve against validated PayPal host; verify details and final application target. |
| Locations | `locations=[Luxembourg City, Luxembourg, Luxembourg]`; `standardizedLocations=[Luxembourg, Luxembourg, LU]` | Verify normalized country codes against shared region parser; retain display locations when possible. |
| Posted date | `postedTs=1791504000` | Unix seconds to UTC datetime, after comparing details/UI posted date. |
| Creation date | `creationTs=1789603200` | Distinct from `postedTs`; do not substitute creation time for posted time silently. |
| Department | `department=Product Management` | Research metadata only; existing channel policy is title-based. |
| Work model | `workLocationOption=onsite`, `locationFlexibility=null` | Do not treat every remote label as worldwide eligibility. Validate country restrictions. |

No details have yet been fetched in this audit. Therefore detail description/required-degree extraction, employment-type semantics, job closure behavior, and redirects remain unverified. Search filter metadata currently advertised `employment_type` with `Full Time`; it did not establish internship filtering coverage. [Search response](https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com&query=&location=&start=0&sort_by=timestamp).

## Completeness, eligibility, and identity

A count of 303 with ten rows proves pagination is required. The first response does **not** prove offset behavior, stable ordering, complete coverage, supported page-size overrides, or zero internships. The downloaded frontend sends `start`, but sends no page-size parameter in the observed search function. A future baseline scan should fetch all pages with at most four workers; require exact expected page lengths, unchanged counts, unique numeric IDs, and a matching final count response. Any failed required page or candidate detail rejects the whole board, preserving the plan's successful-first-poll boundary. Count checks cannot detect every same-count change.

Select internship candidates initially with the shared title regex (`intern`, `internship`, `co-op`, `coop`) and graduate-title exclusion. Validate that against a complete search scan and details before proposing native filters or employment-label classification. PayPal's [official university page](https://careers.pypl.com/university-hiring/north-america-latin-america/default.aspx) describes general advertisements differentiated by focus and both undergraduate and graduate opportunities. General pools may therefore be legitimate postings; inspect actual role titles and requirements rather than assuming every university listing is undergraduate eligible.

The frontend parses numeric job identity from `/careers/job/<id>-<slug>` and the `pid` query parameter. Thus the UI itself accepts multiple public URL forms. The repository's generic normalizer currently leaves nontracking query parameters intact, so a direct `/careers/job/<id>` URL and a fallback `/careers?pid=<id>&domain=paypal.com` can remain distinct. That is a **potential deduplication gap**, not yet a reproduced duplicate. Compare real Simplify PayPal listings and verified canonical/details/application links before defining a narrow, company-specific alias rule. Preserve the original application URL for Discord. [Frontend URL parsing source](https://careers.qualcomm.com/gen/js/pcsxPwa.fa5d073d8912644a.js).

## Validation status and next steps

Verified: current anonymous HTML access; first-party endpoint discovery; one successful search response; count303/default10 rows; numeric/requisition identities; separate posting/creation timestamps; raw/standardized locations; public URL shape.

Not yet verified: complete pagination, same-count churn/duplicate handling, current internship count, candidate descriptions and dates, native internship coverage, actual fallback duplicate aliases, end-to-end runtime, source publication latency, and datacenter/GitHub-runner access. No benchmark may be inferred from one subsecond search request.

A read-only audit script is prepared at `/private/tmp/eightfold-research-fetch.py`. It fetches all offsets with four workers, reports counts/IDs/page lengths, fetches title candidates, probes page-size parameters, and captures current Simplify PayPal rows for comparison. Its execution approval was cancelled; no audit result file was created. The implementation decision should wait for those concrete results. If full scan is stable and eligibility/identity mapping is verified, propose a PayPal-only `eightfold` adapter using the existing Posting boundary and whole-board failure behavior, then run a read-only GitHub validation before enabling the board. Broaden to other individually approved tenants only after separate evidence.
