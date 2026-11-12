from datetime import date
from pathlib import Path

import pytest
from conftest import SECRET_VALUES, Writer, base_day, entity, pharmacy

from opais.export import ExportError, fold, parse_export, read_export
from opais.model import Address, date_text, in_state, parse_date


def test_fold_matches_spellings() -> None:
    assert {fold(k) for k in ("340B ID", "340b_id", "340bId", "340b-ID")} == {"340bid"}


def test_top_level_list() -> None:
    result = parse_export(base_day())
    assert result.entities[0].id_340b == "CH99901"
    assert result.report.record_count == 6


def test_top_level_object_with_one_list() -> None:
    result = parse_export({"generated": "x", "entities": base_day()})
    assert len(result.entities) == 6


def test_top_level_object_with_several_lists_names_the_keys() -> None:
    with pytest.raises(ExportError, match=r"several lists.*alpha, beta"):
        parse_export({"beta": [], "alpha": []})


def test_top_level_object_with_no_list_and_wrong_types() -> None:
    with pytest.raises(ExportError, match="no list"):
        parse_export({"a": 1})
    with pytest.raises(ExportError, match="list of records"):
        parse_export("text")
    with pytest.raises(ExportError, match="record 1: the record is not an object"):
        parse_export([3])


@pytest.mark.parametrize(
    "keys",
    [
        {"id": "340B ID", "name": "Entity Name", "state": "Street State"},
        {"id": "340b_id", "name": "entityName", "state": "state"},
        {"id": "id340b", "name": "NAME", "state": "street-state"},
    ],
)
def test_folded_key_spellings(keys: dict[str, str]) -> None:
    result = parse_export([{keys["id"]: "CH99999", keys["name"]: "Example X", keys["state"]: "ZZ"}])
    (found,) = result.entities
    assert (found.id_340b, found.name, found.street.state) == ("CH99999", "Example X", "ZZ")
    assert result.report.unmapped == {}


def test_nested_list_key_variants() -> None:
    record = {
        "340B ID": "CH99999",
        "contract_pharmacies": [pharmacy("P1", "C1")],
        "shippingAddresses": [{"Shipping Organization": "Example Dock"}],
    }
    (found,) = parse_export([record]).entities
    assert found.contract_pharmacies[0].contract_id == "C1"
    assert found.shipping_addresses[0].organization == "Example Dock"


def test_blank_and_missing_fields_become_none() -> None:
    record = {"340B ID": " CH99999 ", "Entity Name": "   ", "NPI": None, "Rural": ""}
    (found,) = parse_export([record]).entities
    assert found.id_340b == "CH99999"
    assert found.name is None
    assert found.npi is None
    assert found.rural is None
    assert found.street == Address()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("TRUE", True), ("Yes", True), (True, True), ("false", False), ("No", False), ("maybe", None)],
)
def test_participating_parsing(raw: object, expected: bool | None) -> None:
    (found,) = parse_export([{"340B ID": "CH99999", "Participating": raw}]).entities
    assert found.participating is expected


def test_missing_340b_id_is_an_error_with_position() -> None:
    with pytest.raises(ExportError, match="record 2: the record has no 340B ID"):
        parse_export([entity("CH99901", "Example A"), {"Entity Name": "Example B"}])


def test_duplicate_340b_id_is_an_error() -> None:
    with pytest.raises(ExportError, match=r"record 2.*already appears in record 1"):
        parse_export([entity("CH99901", "A"), entity("CH99901", "B")])


def test_nested_item_must_be_an_object() -> None:
    with pytest.raises(ExportError, match="not an object"):
        parse_export([{"340B ID": "CH99999", "Contract Pharmacies": ["text"]}])


def test_unmapped_keys_are_counted_and_not_stored() -> None:
    records = [
        {"340B ID": "CH99901", "Surprise Key": "x", "Pharmacies": [{"Odd Pharmacy Key": "y"}]},
        {"340B ID": "CH99902", "Surprise Key": "z"},
    ]
    report = parse_export(records).report
    assert report.unmapped == {"entity: Surprise Key": 2, "pharmacy: Odd Pharmacy Key": 1}
    assert report.mapped["entity.id_340b"] == 2
    assert report.contract_pharmacy_count == 1


def test_known_ignored_keys_are_reported_separately() -> None:
    report = parse_export([{"340B ID": "CH99901", "NOFO Number": "x"}]).report
    assert report.ignored == {"entity: NOFO Number": 1}
    assert report.unmapped == {}


def test_personal_fields_are_dropped_and_listed_by_key_only() -> None:
    result = parse_export(base_day())
    report = result.report
    assert report.dropped["entity: Authorizing Official Name"] == 6
    assert report.dropped["entity: Primary Contact Phone"] == 6
    assert report.dropped["entity: Entry Comments"] == 6
    assert report.dropped["pharmacy: Pharmacy Phone"] == 3
    assert report.unmapped == {}
    assert not any(secret in repr(result) for secret in SECRET_VALUES)


def test_read_export_gives_hash_and_size(write_json: Writer) -> None:
    path = write_json(base_day(), "x.json")
    result = read_export(path)
    assert len(result.sha256) == 64
    assert result.size_bytes == path.stat().st_size


def test_read_export_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ExportError, match="not valid JSON"):
        read_export(path)


def test_in_state_ignores_case() -> None:
    entities = parse_export(base_day()).entities
    assert {e.id_340b for e in in_state(entities, " zz ")} == {"CH99902"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-01-31", date(2026, 1, 31)),
        ("2026-01-31T04:05:06", date(2026, 1, 31)),
        ("2026-01-31T04:05:06.123Z", date(2026, 1, 31)),
        ("01/31/2026", date(2026, 1, 31)),
        ("1/5/2026", date(2026, 1, 5)),
        ("31/01/2026", None),
        ("2026-02-30", None),
        ("January 5", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date(text: str | None, expected: date | None) -> None:
    assert parse_date(text) == expected


def test_date_text_keeps_original_when_unparsed() -> None:
    assert date_text("01/31/2026") == "2026-01-31"
    assert date_text("sometime") == "sometime"
    assert date_text(None) is None


def test_unrecognised_yes_no_values_are_counted_not_kept() -> None:
    records = [
        {"340B ID": "CH99901", "Participating": "Maybe", "Rural": "Unknown-x"},
        {"340B ID": "CH99902", "Participating": "TRUE", "Rural": "Unknown-x"},
        {
            "340B ID": "CH99903",
            "Shipping Addresses": [{"340B ID Street Address (Yes/No)": "Sometimes"}],
        },
    ]
    result = parse_export(records)
    assert result.report.unrecognised == {
        "entity.participating": 1,
        "entity.rural": 2,
        "shipping.is_street_address": 1,
    }
    assert "Maybe" not in repr(result.report)


def test_duplicate_pharmacy_keeps_the_first_and_counts_the_rest() -> None:
    record = {
        "340B ID": "CH99901",
        "Contract Pharmacies": [
            pharmacy("P1", "C1", **{"Pharmacy Name": "First"}),
            pharmacy("P1", "C1", **{"Pharmacy Name": "Second"}),
            pharmacy("P2", None, **{"Pharmacy Name": "Same"}),
            pharmacy("P2", None, **{"Pharmacy Name": "Same"}),
            pharmacy("P2", None, **{"Pharmacy Name": "Other"}),
        ],
    }
    result = parse_export([record])
    kept = result.entities[0].contract_pharmacies
    assert [p.name for p in kept] == ["First", "Same", "Other"]
    assert result.report.duplicate_pharmacies == 2
    assert result.report.contract_pharmacy_count == 3
