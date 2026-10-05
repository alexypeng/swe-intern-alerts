# Native internship filters

Checked 2026-10-05 against primary documentation for the public endpoints this project uses. A website control can filter a downloaded list in the browser; it does not establish a supported server query. “Not documented” below does not mean impossible on another endpoint or a company-specific career site.

## Documented capabilities

| Source | Current endpoint | Relevant server filtering | Rollout implication |
| --- | --- | --- | --- |
| Lever | `/v0/postings/{slug}` | `commitment`, `team`, `department`, `level`; repeated commitment values are ORed | Validate each board's labels and eligible coverage before selecting commitments. |
| Greenhouse | `/v1/boards/{slug}/jobs` | Job-list documentation specifies `content`; no internship, department, or employment-type query is documented there | Keep complete job-list fetching and local eligibility. |
| Ashby | `/posting-api/job-board/{slug}` | Documentation specifies `includeCompensation`; no employment-type query is documented | Keep complete feed fetching and local `employmentType` classification. |
| SmartRecruiters | `/v1/companies/{slug}/postings` | Department ID and custom-field value IDs; no employment-type or experience-level query is documented | Inspect board-specific departments/custom fields; enable only a filter with verified internship coverage. |
| Workday | `/wday/cxs/{tenant}/{site}/jobs` | Board-specific `appliedFacets`, observed in first-party responses | NVIDIA is validated; Salesforce and future tenants require individual checks. |

Lever documents `commitment` filtering and repeated OR values. Multiple values are case sensitive. Its returned `categories` include commitment, team and department. A label filter can exclude title-detected internships with a different commitment, so documented support alone does not establish completeness under this project's existing eligibility policy. [Official Lever Postings API](https://github.com/lever/postings-api#get-a-list-of-job-postings).

Greenhouse's list-jobs documentation describes all published job posts and the `content` option. Exposed job custom fields appear in response `metadata`; this does not document a metadata query filter. Separate office/department resources should not be treated as evidence for an internship query on the current jobs endpoint. [Official Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html#list-jobs).

Ashby's public feed documents currently published jobs and the compensation option. `employmentType` is a returned enum including `Intern`, alongside department and team response fields. The guide does not specify corresponding filtering parameters. This conclusion concerns the public posting feed, not Ashby's authenticated APIs or private frontend endpoints. [Official Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api).

SmartRecruiters documents `department` as a department ID and `custom_field.CUSTOM_FIELD_ID=VALUE1_ID,VALUE2_ID` for multiple custom-field values. Its public-list reference also has title/location query `q`, location, language, release-date and destination controls, but no `typeOfEmployment` or `experienceLevel` filter. Employment-type response labels are not themselves documented request parameters. Department/custom-field support remains useful if a particular employer exposes a complete internship category; `q=intern` is title searching rather than that native category. [Official public-posting reference](https://developers.smartrecruiters.com/reference/v1listpostings), [Posting API endpoint guide](https://developers.smartrecruiters.com/docs/endpoints), [Posting response objects](https://developers.smartrecruiters.com/docs/objects).

Workday's CXS behavior here is observed, not a published universal contract. NVIDIA's native Job Type is `workerSubType = Intern (Fixed Term)`; Time Type (`Full time`) is separate. Retain local eligibility, required page/detail validation and manual full scans. [NVIDIA first-party search endpoint](https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs), [recorded NVIDIA validation](nvidia-workday.md#native-internship-filter-2026-10-05).

## Live validation

Read-only first-party API probes compared native responses with complete boards on 2026-10-05. Counts are snapshots and changed slightly between requests.

| Board | Full rows | Validated native category | Filtered rows | Currently announceable roles covered |
| --- | ---: | --- | ---: | ---: |
| Palantir | 319 | commitment: Internship | 44 | 40 / 40 |
| Shield AI | 596 | commitment: Intern | 6 | 6 / 6 |
| Toyota Research Institute | 12 | commitment: Intern | 2 | 1 / 1 |
| Salesforce Futureforce | 23 | workerSubType: Intern (Fixed Term) | 22 | 1 / 1 |
| ServiceNow | 703 | Job Posting Type: Intern | 3 | 0 / 0; all 3 current internships included |
| Western Digital | 322 | Requisition Type: five observed university-recruiting categories, including Pipeline - UR | 79 | 3 / 3 |
| Intuitive | 744 | Career Site Category: Students & University | 12 | 3 / 3 |
| Renesas | 949 | Employment Type: Intern (INT) | 11 | 1 / 1 |
| LLNL | 166 | Position Type: Student Intern | 32 | 6 / 6 |

Lever filtered responses honored the requested commitment and matched its full-board label counts. SmartRecruiters custom-field responses honored selected value IDs and exactly matched full-board IDs carrying those values. Salesforce's selected facet covered its one announceable role. These probes sent no messages and wrote no production state. They establish current snapshot coverage, not future label coverage or a production speedup. Sources: first-party Lever `/v0/postings/{slug}?mode=json&commitment=<label>`, SmartRecruiters `/v1/companies/{slug}/postings?custom_field.<field ID>=<value IDs>`, and Salesforce's Workday CXS search endpoint, with complete responses from the same endpoints as baselines.

Intuitive's narrower Employee Type `Intern (Fixed Term)` and Req Type `UR - Intern` categories each omitted two eligible pipeline internships; the broader career-site category included them. Renesas's eligible intern was labeled Full-time in the public employment type but carried Intern (INT) in its custom field. Western Digital needed pipeline categories as well as UR - Intern. LLNL's Students category returned 29 rows, while Position Type Student Intern included 32. These are observed examples of why native filters need board-specific coverage checks.

Zoox and PlusAI exposed no internship commitments at the time of the probe. Sandisk was empty; Solidigm exposed no internship-specific department/custom-field category in the checked feed. No filters were enabled on these boards.

## Decision

The user chose to retain NVIDIA's filter and revert the unfinished expansion to all other boards. NVIDIA removed the dominant scan cost; most other boards already fetch in fractions of a second to a few seconds. Additional static labels and custom IDs would add maintenance for a smaller expected gain. Runtime/configuration are restored to their previous behavior; these findings are retained for a future board that becomes a significant bottleneck.
