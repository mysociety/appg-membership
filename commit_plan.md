# Senedd CPG lifecycle commit plan

The default dataset must contain only current CPG registrations and memberships.
Historical references must retain their Senedd term and explicit validity bounds.
Observation dates describe when evidence was collected, not when membership began.
The five commits below were created locally at the user's explicit request.
No publication or production import was performed.

## 1. Model registrations and validity

Commit: `Model Senedd registration terms and membership validity`.
Files: `models.py`, `senedd_models.py`, `senedd_lifecycle.py`.

- [x] Add typed Senedd term, registration, and membership validity models.
- [x] Record source body ID, term evidence, observation date, closure and reason.
- [x] Bound memberships by Senedd service spells and group closure, without joining
      memberships across a departure and later return or across an election.
- [x] Exclude unverified registrations from current output.

## 2. Reconcile official register snapshots

Commit: `Reconcile complete bilingual Senedd register snapshots`.
Files: `senedd.py`, Senedd CLI changes in `__main__.py`.

- [x] Parse current versus archived registrations using explicit source evidence.
- [x] Require fresh registration evidence after dissolution, including for returning MSs.
- [x] Validate list/detail pages before saving or reconciling; distinguish confirmed
      empty registers from failed fetches/parses.
- [x] Preserve historical snapshots, reconcile disappeared groups after a complete
      scrape, and keep English/Welsh lifecycle metadata aligned.

## 3. Export current and historical data

Commit: `Export current CPGs and bounded Senedd history`.
Files: `build_data.py`, current and historical resource schemas and Parquet files.

- [x] Apply term and parliamentary-service expiry at build time, even if scraping fails.
- [x] Export term/date bounds and reasons for historical references.
- [x] Use Senedd observation dates for officers and ordinary members.
- [x] Keep both language outputs when deduplicating memberships.
- [x] Update dataset schemas and verify generated resources.

## 4. Migrate and document

Commit: `Migrate Senedd term evidence and preserve historical references`.
Files: `senedd_migration.py`, migration CLI, `data/cpg_senedd_*`,
`data/history`, `data/raw/senedd`, `readme.md`.

- [x] Classify existing records using official term-specific evidence; recover Sixth
      Senedd versions overwritten by Seventh Senedd registrations from git history.
- [x] Rebuild data and review current/historical counts and removals.
- [x] Document source evidence, date semantics, refresh procedure and TWFY contract.
- [x] Check the TWFY importer if its source is accessible; document any external
      follow-up rather than claim frontend behaviour has been verified.

## 5. Verification and automation

Commit: `Test Senedd lifecycle rules and refresh data daily`.
Files: `tests/test_senedd_lifecycle.py`, official HTML fixtures, package tests,
`.github/workflows/build_and_publish.yml`, this plan.

- [x] Test mid-term departures for officers and members, re-election, later return,
      term expiry, fresh registration, disappeared/empty lists, failed/partial
      scrapes, language parity and migration idempotence.
- [x] Run project tests, Ruff, Pyright and dataset validation/build checks.

- [x] Add a daily CI refresh/build so expiry does not depend on a new commit.
      A failed scheduled scrape keeps saved evidence and does not skip the expiry build.

## Evidence and implementation notes

- Sixth Senedd dissolution starts **2026-04-08**. Date bounds will be half-open:
  `valid_from <= date < valid_until`; Sixth Senedd references therefore expire
  on 8 April, with 7 April their final possible active date.
- Official dissolution explanation:
  https://senedd.wales/senedd-now/senedd-blog/when-does-the-senedd-end-everything-you-need-to-know-about-dissolution/
- The January 2026 CPG monitoring report, paragraphs 14–15, confirms automatic
  deregistration at dissolution and fresh registration from **2026-07-01**:
  https://senedd.wales/media/uxuhemdd/cpg-monitoring-report-2024-25.pdf
- Official Sixth Senedd archive distinguishes groups active at dissolution from
  groups already ceased; the dissolution bound is a latest possible end, not a
  claim that every group remained active until then:
  https://senedd.wales/archive/sixth-senedd-2021-2026/cross-party-groups-sixth-senedd-2021-2026/
- Commit `3924cf435ed6f9a0aeec53cd07547ae47ec54bd5` (21 July 2026)
  updated 13 registrations in each language; existing folders mix terms.


## Results (11 November 2026)

- Migrated 156 legacy Sixth Senedd records and 26 legacy Seventh Senedd records
  across both languages, using official source IDs. No legacy records were left
  unverified. Initially recovered seven overwritten Sixth Senedd registrations per
  language from the pre-July git snapshot; the live refresh archives further
  replaced registrations before saving their successors.
- Validated all 108 bilingual detail pages for 54 current registrations.
- Current output: **54 groups and 318 membership rows per language**. Only Seventh
  Senedd registrations appear. All current memberships have source observation dates.
- History: **85 Sixth Senedd and 54 Seventh Senedd registrations per language**;
  1,830 membership evidence rows per language. Unknown starts remain null. Every
  Sixth Senedd reference has an end bound no later than 8 April 2026.
- Re-running migration leaves existing files unchanged and adds no snapshots.
- `pytest -q`: **174 passed**, with one existing Pydantic configuration deprecation.
- Ruff lint and formatting checks: pass. Pyright: zero errors or warnings.
- All five dataset resources validate, including the two historical resources.
- Standard `dataset build --all`: passes in an isolated copy, including the UK
  person-ID assignment step. Original UK source files were not regenerated.
- No publication, production imports or database writes performed.
- Automatic approval review rejected deleting intermediate historical snapshots
  because they are immutable evidence. They remain preserved; the exporter
  recalculates derived term/service bounds against the current configuration and
  Popolo data without modifying those snapshots.

## External TWFY follow-up

Source review completed against:
https://github.com/mysociety/theyworkforyou/blob/master/src/twfy_tools/utils/personinfo.py
and `src/twfy_tools/db/utils.py` in the same repository.

The importer currently restricts its group lookup to UK APPGs, matches member rows
by slug without parliament, and has no date/term fields in its APPG models. Its
upload supports replacing assignments and removing absent people, but fully empty
uploads require a separate clearing path. No live behaviour is claimed verified.

Before enabling Senedd CPGs there:

- [ ] Join groups and memberships by parliament plus slug; handle both languages.
- [ ] Import only current resources and clear expired assignments, including when
      all Senedd memberships disappear.
- [ ] If displaying historical references, add term/date fields to its models and
      templates, and visibly label historical evidence.
- [ ] Verify end-to-end removal for an MS losing their last membership and for
      term-wide closure. Committee memberships require their own pipeline review.

These are separate changes in the TWFY repository. The completed work above is
local to this repository; publication remains a later release step.


## Snapshot filename adjustment

- [x] Use date-first `YYYY-MM-DD-<hash>.json` names within the existing
      language/term/body-ID folders. Capture dates are separate from observation
      and membership dates.
- [x] Preserve deduplication across days: unchanged content retains its first name.
- [x] Rename all 196 existing snapshots using their known 11 November 2026 capture
      timestamps. Verify that every file is preserved byte-for-byte.
- [x] Keep legacy hash-only files compatible with archival reruns and readers.
- [x] Add checks for same-day changes, reruns on later days and legacy filenames.
- [x] Verification after the filename change: **174 tests passed**; Ruff and
      Pyright checks pass. Snapshot contents and counts are unchanged.


## Commit execution

Created the planned commits locally, including the approved date-first snapshot
filenames:

1. `a665890c` — Model Senedd registration terms and membership validity.
2. `b3630454` — Reconcile complete bilingual Senedd register snapshots.
3. `d5e3909b` — Export current CPGs and bounded Senedd history.
4. `1024fa1b` — Migrate Senedd term evidence and preserve historical references.
5. Test Senedd lifecycle rules and refresh data daily — includes this plan, the
   regression tests, official HTML fixtures and the scheduled workflow.

The five planned commits are on main. The separate TWFY integration tasks above remain open.


## GitHub Actions composite JSON publishing fix

- Reproduced `TypeError: Invalid value '' for dtype 'Int64'` in the shared
  `data_common` JSON publisher. Its missing-value replacement attempted to insert
  strings into the nullable `senedd_term` integer array.
- Shared-library fix `c280dae7f6405ff6c8d07a70243422e9ec525381` normalizes
  storage before replacing missing cells, retains integer/boolean/float values,
  and serializes dates and timestamps as ISO strings rather than silently
  returning JSON null. It preserves the newer upstream main commit.
- Added shared-library regression tests and a consuming-repository test that
  builds JSON, SQLite and Excel from the real current/historical CPG resources.
- Verification after incorporating upstream main: **213 tests passed**; Ruff
  and parent-repository Pyright pass. Scoped Pyright passes for the two changed
  shared-library modules. Its full optional-module type check requires
  Google/charting/scientific extras absent from this environment.
- Both `dataset version auto --auto-ban major --all --publish` and
  `dataset publish --all` passed in an isolated copy with outputs confined to
  `/tmp`. These commands generate local artifacts; no hosted data was published
  during verification.
- After user approval, the dependency fix was pushed directly to
  `mysociety/data_common` main before committing this repository's updated
  submodule pin. This follow-up commit includes the pin, integration regression
  test and updated plan, for direct delivery to main without a PR.
