# Changelog

## 2.0.0 · 261112 — Unified follow-up delivery

- Accept recordings starting at or after discharge in both calculation entries; window and sparse-target eligibility remain independent.
- Generate slim Mode/CGM daily, NewMetric, Full7, Sparse5 and patient outcomes from the same calculation.
- Add exact 24-hour discharge-anchored daily results, retaining at least seven days and full denominators on the final day.
- Add readable qualified hypoglycemia event details, censor evidence and pre-rounding conditional threshold membership.
- Exclude analysis_id and timezone suffixes from delivery tables; retain four-place half-up rounding and Times New Roman workbooks.
- Keep synthetic outputs outside _Outputs and record authorized cleanup of obsolete artifacts.

## 2.0.0 · 261110 — DRQ research delivery

- Add 13 grouped-window CSVs, a 14-day FBS CSV and a 14-sheet daily workbook, including the actual pump treatment window.
- Use the approved v2.0.0 range, risk, coverage, night-event, FBS and conditional-event definitions.
- Add separately named previous-CGM-day MODD and patient-level batch audit records with resumable execution.
- Add reversible single-CSV export and restoration of a complete result ZIP with per-asset hash checks.
- Document the approved definitions, legacy column mapping, output formatting and deployment commands.

## 2.0.0 · 261109 — Research table revision

- Export decimal results to four places using decimal half-up rounding. Compute thresholds, coverage, events and missingness before formatting.
- Add a Times New Roman workbook to the batch CLI and retain text identifiers, empty cells and numeric Excel values.
- Record export precision in the manifest and validate range-duration and coverage identities within the corresponding rounding bounds.
- Classify a first valid CGM observation at or after discharge as a patient-level time error and continue the batch.
- Document the DRQ, v2.0 and v2.0.0 lineage and the locked deployment workflow in Chinese and English.

## 2.0.0 — 2026-11-04 — Initial clean workspace

- Created a standalone uv project with source, tests, current specifications and operating manuals.
- Applied approved event episode/run separation, strict conditional thresholds, complete-day ADRR sensitivity and pump-time exception scope.
- Restricted input to original source folders; cleaned folders are backups.
- Added a batch CLI, synthetic validation and CI configuration.
- Added a whole-window SD MAGE candidate; formal reference acceptance remains pending.
