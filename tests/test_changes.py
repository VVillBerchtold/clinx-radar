from dataclasses import replace
from datetime import date
from decimal import Decimal

from conftest import Record, base_day, entity, later_day

from opais.changes import ChangeReport, compare, tripwire
from opais.export import parse_export
from opais.model import in_state
from opais.snapshot import Snapshot, SnapshotHeader


def snapshot(records: list[Record], day: date = date(2026, 1, 1), sha: str = "a" * 64) -> Snapshot:
    entities = parse_export(records).entities
    return Snapshot(SnapshotHeader(day, sha, 1, len(entities)), entities)


def day_pair() -> ChangeReport:
    return compare(snapshot(base_day()), snapshot(later_day(), date(2026, 1, 2), "b" * 64))


def test_added_and_removed() -> None:
    report = day_pair()
    assert [(e.id_340b, e.name) for e in report.entities_added] == [
        ("CH99907", "Example Clinic Seven")
    ]
    assert [e.id_340b for e in report.entities_removed] == ["CH99903"]


def test_terminations_and_reinstatements() -> None:
    report = day_pair()
    (ended,) = report.terminations
    assert ended.id_340b == "CH99902"
    assert ended.old_termination_date is None
    assert ended.new_termination_date == "2026-02-01"
    assert (ended.old_participating, ended.new_participating) == (True, False)
    (restored,) = report.reinstatements
    assert restored.id_340b == "CH99904"
    assert restored.old_termination_date == "2025-06-30"
    assert restored.new_termination_date is None


def test_participating_flag_alone_counts_as_termination() -> None:
    new = base_day()
    new[4]["Participating"] = "FALSE"
    report = compare(snapshot(base_day()), snapshot(new, date(2026, 1, 2), "b" * 64))
    assert [t.id_340b for t in report.terminations] == ["CH99905"]


def test_field_changes() -> None:
    report = day_pair()
    changes = {(c.id_340b, c.field): (c.old, c.new) for c in report.field_changes}
    assert changes == {
        ("CH99905", "name"): ("Example Clinic Five", "Example Clinic Five Renamed"),
        ("CH99905", "street.line1"): ("1 Example Street", "2 Example Street"),
    }
    assert report.field_changes[0].name == "Example Clinic Five Renamed"


def test_every_watched_field_is_compared() -> None:
    new = base_day()
    new[0].update(
        {
            "Entity Sub-Division Name": "Example Division",
            "Entity Type": "HOSP",
            "Street Address 2": "Suite 2",
            "Street Address 3": "Floor 3",
            "Street City": "Newtown",
            "Street State": "ZZ",
            "Street Zip": "00002",
            "Street Zip4": "0003",
            "Billing Organization": "Example Billing",
            "Medicaid Number": "M0",
            "NPI": "0000000001",
            "Medicare Provide Number": "MP0",
            "Grant Number": "G0",
        }
    )
    report = compare(snapshot(base_day()), snapshot(new, date(2026, 1, 2), "b" * 64))
    assert {c.field for c in report.field_changes} == {
        "subdivision_name",
        "entity_type",
        "street.line2",
        "street.line3",
        "street.city",
        "street.state",
        "street.zip",
        "street.zip4",
        "billing_organization",
        "medicaid_number",
        "npi",
        "medicare_provider_number",
        "grant_number",
    }


def test_edit_date_alone_is_not_a_change() -> None:
    report = day_pair()
    assert "CH99906" not in {row.id_340b for row in report.field_changes}
    touched = {
        row.id_340b for attribute in report.summary.counts for row in getattr(report, attribute)
    }
    assert touched == {"CH99901", "CH99902", "CH99903", "CH99904", "CH99905", "CH99907"}
    assert report.touched_entities == 6


def test_pharmacy_changes() -> None:
    report = day_pair()
    assert [(p.id_340b, p.pharmacy_id, p.contract_id) for p in report.pharmacies_added] == [
        ("CH99901", "P3", "C3")
    ]
    assert [(p.pharmacy_id, p.contract_id) for p in report.pharmacies_removed] == [("P2", "C2")]
    (ended,) = report.pharmacies_terminated
    assert (ended.pharmacy_id, ended.contract_id, ended.termination_date) == (
        "P1",
        "C1",
        "2026-02-01",
    )


def test_pharmacy_without_contract_id_is_keyed_by_name() -> None:
    new = base_day()
    new[0]["Contract Pharmacies"][2]["Pharmacy Name"] = "Example Pharmacy P4 Renamed"
    report = compare(snapshot(base_day()), snapshot(new, date(2026, 1, 2), "b" * 64))
    assert [p.pharmacy_name for p in report.pharmacies_added] == ["Example Pharmacy P4 Renamed"]
    assert [p.pharmacy_name for p in report.pharmacies_removed] == ["Example Pharmacy P4"]


def test_summary_and_sorting() -> None:
    report = day_pair()
    s = report.summary
    assert (s.old_entities, s.new_entities) == (6, 6)
    assert (s.old_date, s.new_date) == (date(2026, 1, 1), date(2026, 1, 2))
    assert (s.old_sha256, s.new_sha256) == ("a" * 64, "b" * 64)
    assert s.counts == {
        "entities_added": 1,
        "entities_removed": 1,
        "terminations": 1,
        "reinstatements": 1,
        "field_changes": 2,
        "pharmacies_added": 1,
        "pharmacies_removed": 1,
        "pharmacies_terminated": 1,
    }
    many = [entity(f"CH9{n:04d}", f"Example {n}") for n in (5, 2, 9)]
    ids = [e.id_340b for e in compare(snapshot([]), snapshot(many)).entities_added]
    assert ids == sorted(ids)


def test_no_change_report_is_empty() -> None:
    report = compare(snapshot(base_day()), snapshot(base_day(), date(2026, 1, 2), "b" * 64))
    assert report.touched_entities == 0
    assert tripwire(report) == ()


def test_state_filter_applies_before_comparing() -> None:
    old, new = snapshot(base_day()), snapshot(later_day(), date(2026, 1, 2), "b" * 64)
    old = replace(old, entities=in_state(old.entities, "ZZ"))
    new = replace(new, entities=in_state(new.entities, "ZZ"))
    report = compare(old, new)
    assert (report.summary.old_entities, report.summary.new_entities) == (1, 1)
    assert [t.id_340b for t in report.terminations] == ["CH99902"]
    assert report.touched_entities == 1


def fake(n: int) -> list[Record]:
    return [entity(f"CH{n:05d}{i}", f"Example {i}") for i in range(n)]


def test_tripwire_ordinary_change_has_no_reason() -> None:
    old = fake(100)
    new = [{**old[0], "Entity Name": "Renamed"}, *old[1:]]
    report = compare(snapshot(old), snapshot(new, date(2026, 1, 2), "b" * 64))
    assert report.touched_entities == 1
    assert tripwire(report) == ()


def test_tripwire_zero_entities() -> None:
    report = compare(snapshot(fake(5)), snapshot([], date(2026, 1, 2), "b" * 64))
    reasons = tripwire(report)
    assert "The new snapshot has no entities." in reasons


def test_tripwire_entity_count_fell() -> None:
    old = fake(100)
    report = compare(snapshot(old), snapshot(old[:97], date(2026, 1, 2), "b" * 64))
    assert any("fell from 100 to 97" in r for r in tripwire(report))
    assert tripwire(report, max_removed_share=Decimal("0.05")) != tripwire(report)
    # Exactly the threshold is not "more than".
    report = compare(snapshot(old), snapshot(old[:98], date(2026, 1, 2), "b" * 64))
    assert not any("fell" in r for r in tripwire(report))
    report = compare(snapshot(old), snapshot(old[:99], date(2026, 1, 2), "b" * 64))
    assert any("fell" in r for r in tripwire(report, max_removed_share=Decimal("0.001")))


def test_tripwire_too_many_entities_touched() -> None:
    old = fake(100)
    new = [replace_name(r, i) for i, r in enumerate(old)]
    report = compare(snapshot(old), snapshot(new, date(2026, 1, 2), "b" * 64))
    reasons = tripwire(report)
    assert any("20 entities appear in a change" in r and "10%" in r for r in reasons)
    assert tripwire(report, max_changed_share=Decimal("0.5")) == ()


def replace_name(record: Record, i: int) -> Record:
    """Rename every fifth record."""
    if i % 5:
        return record
    return {**record, "Entity Name": "Renamed " + str(record["Entity Name"])}


def test_tripwire_dates_not_later() -> None:
    same = compare(snapshot(fake(5)), snapshot(fake(5), date(2026, 1, 1), "b" * 64))
    assert any("not later than" in r for r in tripwire(same))
    earlier = compare(snapshot(fake(5)), snapshot(fake(5), date(2025, 12, 31), "b" * 64))
    assert any("2025-12-31" in r and "not later than" in r for r in tripwire(earlier))


def test_tripwire_same_source_hash() -> None:
    report = compare(snapshot(fake(5)), snapshot(fake(5), date(2026, 1, 2), "a" * 64))
    assert tripwire(report) == ("Both snapshots were made from a file with the same SHA-256.",)
