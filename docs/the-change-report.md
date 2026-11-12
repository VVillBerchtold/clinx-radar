# The change report

**In short:** give `opais changes` two snapshots and it lists what differs between them, kind by kind. If the amount of change looks wrong for one day, it says so and exits with a different code.

## What it lists

| Section | What counts |
|---|---|
| Entities added, entities removed | In one snapshot and not in the other |
| Terminations | A termination date appears, or `participating` goes from yes to no |
| Reinstatements | The reverse |
| Field changes | The old and new value of: name, sub-division name, entity type, the street address, billing organization, Medicaid number, NPI, Medicare provider number, grant number |
| Contract pharmacies added, removed, newly terminated | See below |

Two things to know when reading one:

- Terminations, field changes and pharmacy changes are looked for only in entities that are in **both** snapshots. An entity that was added or removed is listed once, under that heading.
- A change in the registry's "edit date" alone is not reported. Something a reader can see must have changed.

A contract pharmacy arrangement is identified by the entity's 340B ID, the pharmacy ID and the contract ID. When the contract ID is missing, the pharmacy name is used in its place.

The report says what changed between two dates. It does not say why.

## Markdown or JSON

The report prints as Markdown. Add `--format json` for JSON and `--out FILE` to write it to a file.

## Looking at part of the registry

- `--state RI` keeps the entities whose **street address** is in that state. It is not the state of the billing address or of a contract pharmacy.
- `--id CH99901` keeps one entity. It can be repeated (`--id A --id B`). It ignores capitals and surrounding spaces.
- With both, an entity must match both.

A filtered report says which filter was applied ("Filter: state RI"), in Markdown and in a `filter` object in JSON. Its counts describe the filtered set only.

A 340B ID that is in neither snapshot is an error that names the ID, so a typo is never read as "no changes".

## The tripwire

Some days the registry's file may be cut short, or published twice, or hold a change so large that a person should look before anyone trusts it. The tripwire is a short list of plain-word reasons. It is empty when the change looks ordinary.

The reasons:

- the new snapshot has no entities;
- the entity count fell by more than 2% of the old count;
- more than 10% of the old count of entities appear in a change;
- the new snapshot is dated the same as, or earlier than, the old one;
- both snapshots were made from the very same file.

The 2% and 10% are starting values, not findings. In the library they are the parameters `max_removed_share` and `max_changed_share` of `tripwire(report)`. Change them once you have seen how much a real file moves from day to day.

The tripwire is about the whole registry, not one entity. When a filter is applied, it is still worked out on the unfiltered comparison.

In the made-up example every one of the six entities appears in a change, so the tripwire has a reason. The report is still printed.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The change is ordinary |
| 3 | The tripwire has a reason. The report is still written |
| 2 | An error, such as an unknown 340B ID. `opais snapshot` also exits with 2 when it read no entity |

A scheduled job can use code 3 to stop and ask a person. That is how [clinx.org](https://clinx.org)'s monthly refresh uses it.
