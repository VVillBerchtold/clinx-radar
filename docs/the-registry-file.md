# The registry's file and the field list

**In short:** the reader keeps only the fields on one list. `opais inspect` shows, by field name, what a file holds and what the reader did with it. When the registry adds a field, a person decides whether it joins the list.

## The shape of the file

The file is one JSON object with one key, `coveredEntities`, holding a list. Each entity has nested parts:

- `streetAddress` and `billingAddress`;
- lists of `shippingAddresses`, `medicaidNumbers`, `npiNumbers` and `contractPharmacies`;
- each contract pharmacy has its own `address`.

The reader also accepts the older flat spellings (`Street Address 1`, `Medicaid Number`, `NPI`), which the made-up files in `examples/` use. Field names are matched without regard to capitals, spaces or punctuation.

Medicaid numbers and NPIs are kept as lists, each with its state, in a fixed order. A flat `Medicaid Number` or `NPI` is kept as a single value beside them. The change report compares both together.

## The one list

Every field the reader keeps is named in one table near the top of `src/opais/export.py`. Nothing else is read.

- The `authorizingOfficial` and `primaryContact` parts are not read at all.
- Any field whose name starts with `Authorizing Official` or `Primary Contact`, pharmacy phone numbers, the free-text `Entry Comments` field and the entity `comments` field are dropped.
- A field the table does not know is counted by name and its value is thrown away.

## `opais inspect`

```bash
uv run opais inspect examples/export-day1.json
```

It prints field names and counts, and never a value from the file:

- how many entities, shipping addresses and contract pharmacies were read;
- each kept field and how often it was seen;
- field names the list does not know;
- the personal and free-text fields that were dropped;
- yes/no fields (`Participating`, `Rural`, the shipping flag) whose value was not one of true/false/yes/no/y/n/1/0. They are read as blank, and only the count is shown;
- contract pharmacies that repeat an earlier one under the same entity (same pharmacy ID and contract ID, or pharmacy ID and name when there is no contract ID). The first is kept and the count of the rest is shown.

## Adding a field

Run `opais inspect` on a new file. If it lists a field name the reader did not recognise, and the field is about the organization and not a person, add its spelling to the table in `src/opais/export.py`, with a test that uses a made-up record. The table is in one place and is meant to grow.

## A snapshot

A snapshot is one JSON document for one day. Keys are sorted, entities are sorted by 340B ID, and dates are written one way where they could be read. Nothing in it comes from a clock, so the same file always gives the same snapshot, byte for byte. It also records the day and a fingerprint of the file it was made from.
