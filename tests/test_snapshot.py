import json
from datetime import date
from pathlib import Path

import pytest
from conftest import SECRET_VALUES, base_day, entity, later_day

from opais.changes import compare, tripwire
from opais.export import parse_export
from opais.render import to_json, to_markdown
from opais.snapshot import SnapshotError, read_snapshot, write_snapshot

D1 = date(2026, 1, 1)
D2 = date(2026, 1, 2)


def snap(records: list[dict[str, object]], path: Path, day: date, sha: str) -> Path:
    write_snapshot(
        parse_export(records).entities, path, taken_on=day, source_sha256=sha, source_bytes=10
    )
    return path


def test_same_input_same_bytes(tmp_path: Path) -> None:
    one = snap(base_day(), tmp_path / "a.json", D1, "a" * 64)
    reordered = base_day()[::-1]
    for record in reordered:
        record["Contract Pharmacies"].reverse()
    two = snap(reordered, tmp_path / "b.json", D1, "a" * 64)
    assert one.read_bytes() == two.read_bytes()
    assert b"\r" not in one.read_bytes()
    assert one.read_bytes().endswith(b"\n")


def test_header_and_ordering(tmp_path: Path) -> None:
    path = snap(base_day()[::-1], tmp_path / "a.json", D1, "a" * 64)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["format"] == "clinx-radar snapshot"
    assert doc["format_version"] == 1
    assert doc["taken_on"] == "2026-01-01"
    assert doc["entity_count"] == 6
    ids = [e["id_340b"] for e in doc["entities"]]
    assert ids == sorted(ids)
    pharmacies = doc["entities"][0]["contract_pharmacies"]
    assert [p["pharmacy_id"] for p in pharmacies] == ["P1", "P2", "P4"]


def test_dates_are_iso_when_parsed_and_original_otherwise(tmp_path: Path) -> None:
    record = entity(
        "CH99999", "Example", **{"Termination Date": "02/03/2026", "Edit Date": "sometime"}
    )
    path = snap([record], tmp_path / "a.json", D1, "a" * 64)
    (doc,) = json.loads(path.read_text(encoding="utf-8"))["entities"]
    assert doc["termination_date"] == "2026-02-03"
    assert doc["participating_start_date"] == "2020-01-01"
    assert doc["edit_date"] == "sometime"


def test_round_trip(tmp_path: Path) -> None:
    entities = parse_export(base_day()).entities
    path = tmp_path / "a.json"
    write_snapshot(entities, path, taken_on=D1, source_sha256="b" * 64, source_bytes=99)
    loaded = read_snapshot(path)
    assert loaded.header.taken_on == D1
    assert loaded.header.source_sha256 == "b" * 64
    assert loaded.header.source_bytes == 99
    assert loaded.header.entity_count == 6
    assert {e.id_340b for e in loaded.entities} == {e.id_340b for e in entities}
    again = tmp_path / "again.json"
    write_snapshot(loaded.entities, again, taken_on=D1, source_sha256="b" * 64, source_bytes=99)
    assert again.read_bytes() == path.read_bytes()


def test_unknown_format_version_is_refused(tmp_path: Path) -> None:
    path = snap(base_day(), tmp_path / "a.json", D1, "a" * 64)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["format_version"] = 2
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SnapshotError, match="format_version 2"):
        read_snapshot(path)


def test_damaged_snapshots_are_refused(tmp_path: Path) -> None:
    path = snap(base_day(), tmp_path / "a.json", D1, "a" * 64)
    doc = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        ({**doc, "format": "other"}, "not an"),
        ({**doc, "entity_count": 99}, "entity_count"),
        ({**doc, "taken_on": "nope"}, "not a date"),
        ({k: v for k, v in doc.items() if k != "taken_on"}, "header is incomplete"),
    ]
    for bad, message in cases:
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(SnapshotError, match=message):
            read_snapshot(path)
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(SnapshotError, match="expected an object"):
        read_snapshot(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(SnapshotError, match="not valid JSON"):
        read_snapshot(path)


def test_personal_values_never_reach_a_snapshot_or_a_report(tmp_path: Path) -> None:
    old_path = snap(base_day(), tmp_path / "old.json", D1, "a" * 64)
    new_path = snap(later_day(), tmp_path / "new.json", D2, "b" * 64)
    report = compare(read_snapshot(old_path), read_snapshot(new_path))
    reasons = tripwire(report)
    outputs = [
        old_path.read_text(encoding="utf-8"),
        new_path.read_text(encoding="utf-8"),
        to_markdown(report, reasons),
        to_json(report, reasons),
    ]
    for text in outputs:
        for secret in SECRET_VALUES:
            assert secret not in text
        assert "Authorizing" not in text
        assert "Primary Contact" not in text
