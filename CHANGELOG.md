# Changelog

This project follows [semantic versioning](https://semver.org/).

## Unreleased

### Changed

- The README opens in plain words (what the tool is for, a sample report, a one-minute example, what is kept and what is dropped). The detail moved to `docs/`: the change report, getting the registry's file, and the file and its field list.

### Added

- `opais pull --out DIR [--browser PATH] [--timeout SECONDS]` (optional extra `pull`, Playwright 1.52.0): fetches the daily export once through HRSA's public reports page, refuses with distinct exit codes (4 to 12) if the page or file is not as expected, and prints one JSON summary line (name, bytes, sha256, UTC time, export date).
- `opais.export`: reads one HRSA daily export (JSON) into typed records. A single table maps each field to the key spellings it accepts.
- A report of the keys the reader did not recognise, and of the personal fields it dropped.
- People named in the export (authorizing official, primary contact), pharmacy phone numbers and entry comments are dropped at read time.
- `opais.snapshot`: a deterministic snapshot file, format version 1.
- `opais.changes`: a comparison of two snapshots, and a tripwire with starting thresholds.
- `opais.render`: Markdown and JSON change reports.
- The `opais` command with `snapshot`, `changes` and `inspect`.
- `opais changes --id` (repeatable) beside `--state`. The report states the filter in Markdown and in a JSON `filter` object, and its counts describe the filtered set. An unknown 340B ID is an error. The tripwire is always computed on the unfiltered comparison.
- The reader reports yes/no values it did not recognise (by field name) and contract pharmacies dropped as repeats of an earlier key. `opais inspect` shows both.

- The reader maps the nested structure of the HRSA export: `streetAddress`, `billingAddress`, shipping addresses, pharmacy `address` objects, `medicaidNumbers` and `npiNumbers` lists, `subName`, `cmsCertificationNumber`, `parentCeId` and `parentId340B`. New model fields: `parent_340b_id`, `parent_ce_id`, `medicaid_numbers`, `npi_numbers`. The snapshot keeps them, with the lists in a fixed order. The flat spellings still work.

### Changed

- The entity `comments` field is dropped at read time and counted by name in `opais inspect`.
- The Medicaid number and NPI changes in a report compare the flat value and the lists together.

- A contract pharmacy that repeats an earlier key under the same entity is dropped by the reader (the first is kept) and counted, instead of collapsing silently when two snapshots are compared.
