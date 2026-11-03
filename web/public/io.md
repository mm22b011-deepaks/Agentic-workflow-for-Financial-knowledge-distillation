# Node inputs and outputs

## run-all

Input: settings (file). Settings used by this step.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## validate-config

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## build-constituents

Input: checked settings (check). Settings checked before running.
Output: members (member). Companies that were in the index.

- Member: Session-only member pseudonym
- Joined index: Membership start date
- Left index: Membership end date
- Mapped: A filing identifier is available

## estimate-scope

Input: members (member). Companies that were in the index.
Output: plan (release). Releases and requests planned across quarters.

- Members: Planned members (members)
- Quarters: Planned calendar quarters (quarters)
- Releases: Planned releases (releases)
- Requests: One request for each release (requests)
- Total requests: Includes retries and model comparisons (requests)
- Time needed: Estimated duration at the daily limit (days)

## ingest

Input: plan (release). Releases and requests planned across quarters.
Output: files (file). Saved earnings release files.

- Release: Session-only release pseudonym
- Filed: Filing date
- Saved: Download date
- File size: Downloaded file size (bytes)
- Status: Processing outcome
- Text length: Parsed text length (characters)

## extract

Input: texts (text). Release text ready for extraction.
Output: records (record). EPS, revenue, guidance and tone.

- Release: Session-only release pseudonym
- Filed: Filing date
- Quarter: Calendar quarter
- EPS: Reported earnings per share (per share)
- EPS confidence: Confidence in EPS (%)
- EPS status: Evidence validation status
- Revenue: Reported revenue
- Revenue confidence: Confidence in revenue (%)
- Revenue status: Evidence validation status
- Guidance: Forward outlook
- Guidance confidence: Confidence in guidance (%)
- Guidance status: Evidence validation status
- Tone: Management tone
- Tone confidence: Confidence in tone (%)
- Tone status: Evidence validation status
- Confidence: Mean confidence (%)
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## aggregate

Input: records (record). EPS, revenue, guidance and tone.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## gate

Input: index rows (index row). One KPI for each quarter.
Output: KPIs (KPI). KPIs meeting the publication threshold.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## publish

Input: KPIs (KPI). KPIs meeting the publication threshold.
Output: KPIs (KPI). KPIs meeting the publication threshold.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## suppressed

Input: index rows (index row). One KPI for each quarter.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## nowcast

Input: KPIs (KPI). KPIs meeting the publication threshold.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## cohort

Input: plan (release). Releases and requests planned across quarters.
Output: company-quarters (company-quarter). One member in one quarter.

- Member: Session-only member pseudonym
- Quarter: Calendar quarter
- Status: Processing outcome

## discover

Input: company-quarters (company-quarter). One member in one quarter.
Output: filings (release). Earnings filings found for each quarter.

- Release: Session-only release pseudonym
- Member: Session-only member pseudonym
- Quarter: Calendar quarter
- Filed: Filing date
- Filing item: SEC form item
- Status: Processing outcome

## download

Input: filings (release). Earnings filings found for each quarter.
Output: files (file). Saved earnings release files.

- Release: Session-only release pseudonym
- Filed: Filing date
- Saved: Download date
- File size: Downloaded file size (bytes)
- Status: Processing outcome
- Text length: Parsed text length (characters)

## parse

Input: files (file). Saved earnings release files.
Output: texts (text). Release text ready for extraction.

- Release: Session-only release pseudonym
- Filed: Filing date
- Text length: Parsed text length (characters)
- Text sent: Text sent for extraction (characters)
- Truncated: Text shortened
- Text preview: First three lines; Internal trace only

## extract-step

Input: texts (text). Release text ready for extraction.
Output: records (record). EPS, revenue, guidance and tone.

- Release: Session-only release pseudonym
- Filed: Filing date
- Quarter: Calendar quarter
- EPS: Reported earnings per share (per share)
- EPS confidence: Confidence in EPS (%)
- EPS status: Evidence validation status
- Revenue: Reported revenue
- Revenue confidence: Confidence in revenue (%)
- Revenue status: Evidence validation status
- Guidance: Forward outlook
- Guidance confidence: Confidence in guidance (%)
- Guidance status: Evidence validation status
- Tone: Management tone
- Tone confidence: Confidence in tone (%)
- Tone status: Evidence validation status
- Confidence: Mean confidence (%)
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## validate

Input: records (record). EPS, revenue, guidance and tone.
Output: checked records (record). Records with evidence and number checks.

- Release: Session-only release pseudonym
- Filed: Filing date
- Quarter: Calendar quarter
- EPS: Reported earnings per share (per share)
- EPS confidence: Confidence in EPS (%)
- EPS status: Evidence validation status
- Revenue: Reported revenue
- Revenue confidence: Confidence in revenue (%)
- Revenue status: Evidence validation status
- Guidance: Forward outlook
- Guidance confidence: Confidence in guidance (%)
- Guidance status: Evidence validation status
- Tone: Management tone
- Tone confidence: Confidence in tone (%)
- Tone status: Evidence validation status
- Confidence: Mean confidence (%)
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## consolidate

Input: checked records (record). Records with evidence and number checks.
Output: records (record). EPS, revenue, guidance and tone.

- Release: Session-only release pseudonym
- Filed: Filing date
- Quarter: Calendar quarter
- EPS: Reported earnings per share (per share)
- EPS confidence: Confidence in EPS (%)
- EPS status: Evidence validation status
- Revenue: Reported revenue
- Revenue confidence: Confidence in revenue (%)
- Revenue status: Evidence validation status
- Guidance: Forward outlook
- Guidance confidence: Confidence in guidance (%)
- Guidance status: Evidence validation status
- Tone: Management tone
- Tone confidence: Confidence in tone (%)
- Tone status: Evidence validation status
- Confidence: Mean confidence (%)
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## review

Input: flags (flag). Issues needing a person to review.
Output: flags (flag). Issues needing a person to review.

- Release: Session-only release pseudonym
- Quarter: Calendar quarter
- Review reason: Why review is needed
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Field needing review: Affected extracted field

## xbrl

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## model

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## cache

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## limiter

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## validators

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## sec

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## rate

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## kpi

Input: records (record). EPS, revenue, guidance and tone.
Output: KPIs (KPI). KPIs meeting the publication threshold.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## rebuild-index

Input: files (file). Saved earnings release files.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## model-bakeoff

Input: texts (text). Release text ready for extraction.
Output: records (record). EPS, revenue, guidance and tone.

- Release: Session-only release pseudonym
- Filed: Filing date
- Quarter: Calendar quarter
- EPS: Reported earnings per share (per share)
- EPS confidence: Confidence in EPS (%)
- EPS status: Evidence validation status
- Revenue: Reported revenue
- Revenue confidence: Confidence in revenue (%)
- Revenue status: Evidence validation status
- Guidance: Forward outlook
- Guidance confidence: Confidence in guidance (%)
- Guidance status: Evidence validation status
- Tone: Management tone
- Tone confidence: Confidence in tone (%)
- Tone status: Evidence validation status
- Confidence: Mean confidence (%)
- Checks failed: Validation failures (checks)
- Flagged: Requires review
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## doctor

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## freeze-panel

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## validate-index

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## supersede-stale

Input: settings (file). Settings used by this step.
Output: completed checks (check). Action completed without creating data rows.

- Status: Step outcome
- Completed: Action completion time
- Completed checks: Successful action completions (checks)

## demo

Input: settings (file). Settings used by this step.
Output: index rows (index row). One KPI for each quarter.

- KPI: Index measure
- Quarter: Calendar quarter
- Value: KPI value
- Unit: KPI unit
- Reported: Observed records (records)
- Expected: Expected records (records)
- Coverage: Fraction of expected records (%)
- Minimum coverage: Minimum observations as share of expected records (%)
- Gate: Meets publication checks
- Suppressed: Below publication threshold

## serve

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## export

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## prepare-labels

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## quality-summary

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## report

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## schedule-plan

Input: settings (file). Settings used by this step.
Output: completed checks (check). Action completed without creating data rows.

- Status: Step outcome
- Completed: Action completion time
- Completed checks: Successful action completions (checks)

## schedule-status

Input: settings (file). Settings used by this step.
Output: completed checks (check). Action completed without creating data rows.

- Status: Step outcome
- Completed: Action completion time
- Completed checks: Successful action completions (checks)

## schedule-run

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## schedule-pause

Input: settings (file). Settings used by this step.
Output: completed checks (check). Action completed without creating data rows.

- Status: Step outcome
- Completed: Action completion time
- Completed checks: Successful action completions (checks)

## schedule-resume

Input: settings (file). Settings used by this step.
Output: completed checks (check). Action completed without creating data rows.

- Status: Step outcome
- Completed: Action completion time
- Completed checks: Successful action completions (checks)

## schedule-install

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## schedule-uninstall

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## raptor

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## demo-ingest

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## demo-parse

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## demo-extract

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## demo-validate

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## demo-aggregate

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## cli

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed

## schedule

Input: settings (file). Settings used by this step.
Output: checked settings (check). Settings checked before running.

- Setting: Configuration setting
- Value: Configured non-identifying value
- Type: Setting value type
- Quote: Evidence check passed
- Number: Number check passed
- Scale: Scale check passed
- Row: Row check passed
- Period: Period check passed
