import json
from datetime import date

from conftest import entity
from test_changes import day_pair, snapshot

from opais.changes import compare
from opais.export import parse_export
from opais.render import ROW_CAP, format_read_report, to_json, to_markdown


def test_json_parses_and_is_deterministic() -> None:
    report = day_pair()
    reasons = ("Example reason.",)
    text = to_json(report, reasons)
    assert text == to_json(day_pair(), reasons)
    doc = json.loads(text)
    assert doc["summary"]["counts"]["terminations"] == 1
    assert doc["summary"]["old_date"] == "2026-01-01"
    assert doc["tripwire"]["reasons"] == ["Example reason."]
    assert doc["changes"]["entities_added"] == [
        {"id_340b": "CH99907", "name": "Example Clinic Seven"}
    ]
    assert list(doc) == sorted(doc)


def test_markdown_has_header_counts_and_sections() -> None:
    text = to_markdown(day_pair(), ())
    assert text.startswith("# Changes between 2026-01-01 and 2026-01-02\n")
    assert "| Entities added | 1 |" in text
    assert "| Field changes | 2 |" in text
    assert "No tripwire reason was found." in text
    assert "## Entities added (1)" in text
    assert "| CH99907 | Example Clinic Seven |" in text
    assert "| CH99905 | Example Clinic Five Renamed | name | Example Clinic Five |" in text
    assert "6 before, 6 after" in text


def test_markdown_shows_tripwire_reasons_and_skips_empty_sections() -> None:
    same = compare(
        snapshot([entity("CH99901", "Example A")]), snapshot([entity("CH99901", "Example A")])
    )
    text = to_markdown(same, ("First reason.", "Second reason."))
    assert "- First reason." in text
    assert "- Second reason." in text
    assert "## Entities added" not in text


def test_markdown_caps_long_sections() -> None:
    many = [entity(f"CH9{n:05d}", f"Example {n}") for n in range(ROW_CAP + 30)]
    report = compare(snapshot([]), snapshot(many, date(2026, 1, 2), "b" * 64))
    text = to_markdown(report, ())
    assert f"## Entities added ({ROW_CAP + 30})" in text
    assert text.count("| CH9") == ROW_CAP
    assert "30 more rows are in the JSON report." in text
    assert len(json.loads(to_json(report, ()))["changes"]["entities_added"]) == ROW_CAP + 30


def test_markdown_escapes_pipes() -> None:
    old = snapshot([entity("CH99901", "Example A")])
    new = snapshot([entity("CH99901", "Example | B")], date(2026, 1, 2), "b" * 64)
    assert "Example \\| B" in to_markdown(compare(old, new), ())


def test_markdown_wording_is_neutral() -> None:
    text = to_markdown(day_pair(), ("Example reason.",)).lower()
    for word in ("because", "due to", "caused", "fraud"):
        assert word not in text


def test_read_report_text_names_keys_and_never_values() -> None:
    result = parse_export([entity("CH99901", "Example A", **{"Surprise": "value-xyz"})])
    text = format_read_report(result.report)
    assert "records read: 1" in text
    assert "entity: Surprise: 1" in text
    assert "entity: Authorizing Official Name: 1" in text
    assert "value-xyz" not in text
    assert "Example Official Person" not in text
