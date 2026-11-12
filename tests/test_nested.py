"""The real nested export shape: nested addresses, lists, and what is dropped."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest
from conftest import SECRET_VALUES, Writer, nested_day

from opais.changes import ChangeFilter, compare
from opais.cli import main
from opais.export import parse_export, read_export
from opais.model import Address, StateNumber
from opais.snapshot import read_snapshot, write_snapshot

pytestmark = pytest.mark.filterwarnings("error")


def test_nested_addresses_are_read() -> None:
    first = parse_export(nested_day()).entities[0]
    assert first.street == Address(
        line1="1 Example Street", city="Exampleton", state="RI", zip="00001", zip4="0002"
    )
    assert first.billing.line1 == "2 Example Street"
    assert first.billing_organization == "Example Billing"
    (ship,) = first.shipping_addresses
    assert ship.is_street_address is False
    assert ship.organization == "Example Receiving"
    assert ship.address.line1 == "5 Example Street"


def test_other_nested_fields_are_read() -> None:
    first = parse_export(nested_day()).entities[0]
    assert first.ce_id == "9911"
    assert first.parent_ce_id == "1"
    assert first.parent_340b_id == "CH00001"
    assert first.subdivision_name == "Example Division"
    assert first.medicare_provider_number == "000000"
    assert first.grant_number == "H00XX00000"
    assert first.rural is False
    assert first.certified_date == "2020-01-01T00:00:00"


def test_lists_are_read_and_ordered() -> None:
    first = parse_export(nested_day()).entities[0]
    assert first.medicaid_numbers == (StateNumber("M1", "MA"), StateNumber("M2", "RI"))
    assert first.npi_numbers == (
        StateNumber("0000000001", "RI"),
        StateNumber("0000000002", "RI"),
    )
    pharmacy = first.contract_pharmacies[0]
    assert (pharmacy.pharmacy_id, pharmacy.contract_id) == ("20", "2")
    assert pharmacy.begin_date == "2024-01-15"
    assert pharmacy.address.city == "Exampleton"
    assert pharmacy.address.state == "RI"


def test_inspect_shows_no_unmapped_keys(
    write_json: Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_json(nested_day(), "nested.json")
    result = read_export(path)
    assert result.report.unmapped == {}
    assert result.report.dropped["entity: comments"] == 2
    assert main(["inspect", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "entity: comments: 2" in printed
    assert "entity: authorizingOfficial: 2" in printed
    for secret in SECRET_VALUES:
        assert secret not in printed


def test_dropped_values_never_reach_a_snapshot_or_report(
    write_json: Writer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one = write_json(nested_day(), "n1.json")
    changed = nested_day()
    changed["coveredEntities"][0]["name"] = "Example Nested One Renamed"
    changed["coveredEntities"][0]["comments"] = "Example nested comment"
    two = write_json(changed, "n2.json")
    s1, s2 = tmp_path / "s1.json", tmp_path / "s2.json"
    assert main(["snapshot", str(one), "--date", "2026-01-01", "--out", str(s1)]) == 0
    assert main(["snapshot", str(two), "--date", "2026-01-02", "--out", str(s2)]) == 0
    out = tmp_path / "report.json"
    main(["changes", str(s1), str(s2), "--format", "json", "--out", str(out)])
    main(["changes", str(s1), str(s2)])
    texts = [s1.read_text(), s2.read_text(), out.read_text(), capsys.readouterr().out]
    for text in texts[:3]:
        assert "comments" not in text
    for text in texts:
        for secret in SECRET_VALUES:
            assert secret not in text


def test_snapshot_bytes_are_stable_and_ignore_list_order(
    write_json: Writer, tmp_path: Path
) -> None:
    shuffled = copy.deepcopy(nested_day())
    for record in shuffled["coveredEntities"]:
        for key in ("medicaidNumbers", "npiNumbers", "contractPharmacies"):
            record[key].reverse()
    shuffled["coveredEntities"].reverse()
    entities = parse_export(nested_day()).entities
    again = parse_export(shuffled).entities
    texts = []
    for n, found in enumerate((entities, again, entities)):
        out = tmp_path / f"snap{n}.json"
        write_snapshot(
            found, out, taken_on=date(2026, 1, 1), source_sha256="a" * 64, source_bytes=1
        )
        texts.append(out.read_bytes())
    assert texts[0] == texts[1] == texts[2]


def test_state_filter_uses_the_nested_street_state(write_json: Writer, tmp_path: Path) -> None:
    one = write_json(nested_day(), "n1.json")
    changed = nested_day()
    for record in changed["coveredEntities"]:
        record["streetAddress"]["addressLine1"] = "3 Example Street"
    two = write_json(changed, "n2.json")
    s1, s2 = tmp_path / "s1.json", tmp_path / "s2.json"
    main(["snapshot", str(one), "--date", "2026-01-01", "--out", str(s1)])
    main(["snapshot", str(two), "--date", "2026-01-02", "--out", str(s2)])
    report = compare(read_snapshot(s1), read_snapshot(s2), ChangeFilter.make(state="RI"))
    assert {c.id_340b for c in report.field_changes} == {"CH99911"}
    assert report.summary.new_entities == 1
    kept = tmp_path / "ri.json"
    assert (
        main(["snapshot", str(one), "--date", "2026-01-01", "--out", str(kept), "--state", "ZZ"])
        == 0
    )
    assert read_snapshot(kept).header.entity_count == 1


def test_new_fields_are_compared(write_json: Writer, tmp_path: Path) -> None:
    one = write_json(nested_day(), "n1.json")
    changed = nested_day()
    first = changed["coveredEntities"][0]
    first["medicaidNumbers"].append({"medicaidNumber": "M3", "state": "RI"})
    first["npiNumbers"] = []
    first["billingAddress"]["organization"] = "Example Billing Two"
    first["contractPharmacies"][0]["terminationDate"] = "2026-02-01"
    first["contractPharmacies"].pop()
    two = write_json(changed, "n2.json")
    s1, s2 = tmp_path / "s1.json", tmp_path / "s2.json"
    main(["snapshot", str(one), "--date", "2026-01-01", "--out", str(s1)])
    main(["snapshot", str(two), "--date", "2026-01-02", "--out", str(s2)])
    report = compare(read_snapshot(s1), read_snapshot(s2))
    assert {c.field for c in report.field_changes} == {
        "medicaid_number",
        "npi",
        "billing_organization",
    }
    assert len(report.pharmacies_terminated) == 1
    assert len(report.pharmacies_removed) == 1
