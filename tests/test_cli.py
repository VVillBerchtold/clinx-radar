import json
from pathlib import Path
from typing import Any

import pytest
from conftest import Writer, base_day, later_day

from opais.cli import main

ROOT = Path(__file__).resolve().parent.parent


def make_snapshots(
    day1: Path, day2: Path, tmp_path: Path, extra: list[str] | None = None
) -> tuple[Path, Path]:
    one, two = tmp_path / "snaps" / "one.json", tmp_path / "snaps" / "two.json"
    assert (
        main(["snapshot", str(day1), "--date", "2026-01-01", "--out", str(one), *(extra or [])])
        == 0
    )
    assert (
        main(["snapshot", str(day2), "--date", "2026-01-02", "--out", str(two), *(extra or [])])
        == 0
    )
    return one, two


def test_snapshot_command(day1: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "deep" / "one.json"
    assert main(["snapshot", str(day1), "--date", "2026-01-01", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "read 6 entities" in printed
    assert "unmapped keys" in printed
    assert json.loads(out.read_text(encoding="utf-8"))["entity_count"] == 6


def test_snapshot_state_filter(
    day1: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "ri.json"
    assert (
        main(["snapshot", str(day1), "--date", "2026-01-01", "--out", str(out), "--state", "ri"])
        == 0
    )
    assert "kept 5 with street state RI" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["entity_count"] == 5


def test_snapshot_with_no_entity_exits_2(write_json: Writer, tmp_path: Path) -> None:
    empty = write_json([], "empty.json")
    out = tmp_path / "x.json"
    assert main(["snapshot", str(empty), "--date", "2026-01-01", "--out", str(out)]) == 2
    assert not out.exists()


def test_snapshot_errors_exit_2(
    write_json: Writer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = write_json([{"Entity Name": "Example"}], "bad.json")
    assert (
        main(["snapshot", str(bad), "--date", "2026-01-01", "--out", str(tmp_path / "x.json")]) == 2
    )
    assert "no 340B ID" in capsys.readouterr().err
    assert (
        main(["snapshot", str(tmp_path / "missing.json"), "--date", "2026-01-01", "--out", "x"])
        == 2
    )


def test_bad_date_is_a_usage_error(day1: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["snapshot", str(day1), "--date", "01/02/2026", "--out", str(tmp_path / "x.json")])
    assert stop.value.code == 2


def test_changes_markdown_to_stdout_trips_on_tiny_fixture(
    day1: Path, day2: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    capsys.readouterr()
    assert main(["changes", str(one), str(two)]) == 3  # 6 of 6 entities appear in a change
    captured = capsys.readouterr()
    assert captured.out.startswith("# Changes between 2026-01-01 and 2026-01-02")
    assert "tripwire:" in captured.err


def test_changes_json_to_file_exit_3_still_writes(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    out = tmp_path / "reports" / "r.json"
    assert main(["changes", str(one), str(two), "--format", "json", "--out", str(out)]) == 3
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["counts"]["terminations"] == 1


def test_changes_ordinary_exits_0(write_json: Writer, tmp_path: Path) -> None:
    records = [{"340B ID": f"CH{n:05d}", "Entity Name": f"Example {n}"} for n in range(100)]
    changed = [{**records[0], "Entity Name": "Example Renamed"}, *records[1:]]
    a, b = write_json(records, "a.json"), write_json(changed, "b.json")
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    assert main(["snapshot", str(a), "--date", "2026-01-01", "--out", str(one)]) == 0
    assert main(["snapshot", str(b), "--date", "2026-01-02", "--out", str(two)]) == 0
    assert main(["changes", str(one), str(two), "--out", str(tmp_path / "r.md")]) == 0
    assert "Field changes (1)" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_changes_state_filter(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    out = tmp_path / "zz.json"
    main(["changes", str(one), str(two), "--state", "ZZ", "--format", "json", "--out", str(out)])
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert (summary["old_entities"], summary["new_entities"]) == (1, 1)


def test_changes_error_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.json"
    assert main(["changes", str(missing), str(missing)]) == 2
    assert "error:" in capsys.readouterr().err


def test_inspect_command(day1: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inspect", str(day1)]) == 0
    printed = capsys.readouterr().out
    assert "records read: 6" in printed
    assert "entity.id_340b: 6" in printed
    assert "entity: Authorizing Official Name: 6" in printed


def test_inspect_lists_unmapped_keys(
    write_json: Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_json([{"340B ID": "CH99901", "Brand New Key": 1}], "x.json")
    assert main(["inspect", str(path)]) == 0
    assert "entity: Brand New Key: 1" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert "clinx-radar 0.1.0" in capsys.readouterr().out


def test_committed_examples_work(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one, two = tmp_path / "1.json", tmp_path / "2.json"
    args = ["--out"]
    day1, day2 = ROOT / "examples" / "export-day1.json", ROOT / "examples" / "export-day2.json"
    assert main(["snapshot", str(day1), "--date", "2026-01-01", *args, str(one)]) == 0
    assert main(["snapshot", str(day2), "--date", "2026-01-02", *args, str(two)]) == 0
    capsys.readouterr()
    main(["changes", str(one), str(two)])
    text = capsys.readouterr().out
    assert "## Terminations (1)" in text
    assert "## Contract pharmacies added (1)" in text


def test_fixtures_are_what_the_examples_were_made_from(day1: Path, day2: Path) -> None:
    assert json.loads(day1.read_text(encoding="utf-8")) == base_day()
    assert json.loads(day2.read_text(encoding="utf-8")) == later_day()
    assert (
        json.loads((ROOT / "examples" / "export-day1.json").read_text(encoding="utf-8"))
        == base_day()
    )
    assert (
        json.loads((ROOT / "examples" / "export-day2.json").read_text(encoding="utf-8"))
        == later_day()
    )


def run_changes(one: Path, two: Path, out: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    code = main(["changes", str(one), str(two), "--format", "json", "--out", str(out), *extra])
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_id_filter_keeps_only_those_ids(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    out = tmp_path / "r.json"
    _, doc = run_changes(one, two, out, "--id", " ch99901 ", "--id", "CH99902")
    assert doc["filter"] == {"ids": ["CH99901", "CH99902"], "state": None}
    assert doc["summary"]["old_entities"] == 2
    assert doc["summary"]["counts"]["terminations"] == 1
    assert doc["summary"]["counts"]["entities_added"] == 0
    assert doc["summary"]["counts"]["field_changes"] == 0
    assert doc["summary"]["counts"]["pharmacies_added"] == 1
    touched = {r["id_340b"] for rows in doc["changes"].values() for r in rows}
    assert touched == {"CH99901", "CH99902"}


def test_id_filter_markdown_header(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    out = tmp_path / "r.md"
    main(["changes", str(one), str(two), "--id", "CH99901", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "\nFilter: 340B ID CH99901\n" in text
    assert "| Entities | " not in text
    assert "- Entities: 1 before, 1 after" in text
    assert "computed on the whole file" in text


def test_state_filter_says_so_and_counts_the_filtered_set(
    day1: Path, day2: Path, tmp_path: Path
) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    out = tmp_path / "r.md"
    main(["changes", str(one), str(two), "--state", "zz", "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "\nFilter: state ZZ\n" in text
    assert "- Entities: 1 before, 1 after" in text
    _, doc = run_changes(one, two, tmp_path / "r.json", "--state", "ZZ")
    assert doc["filter"] == {"ids": [], "state": "ZZ"}


def test_id_and_state_must_both_match(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    _, doc = run_changes(one, two, tmp_path / "a.json", "--id", "CH99901", "--state", "ZZ")
    assert doc["summary"]["old_entities"] == 0
    assert doc["filter"] == {"ids": ["CH99901"], "state": "ZZ"}
    _, doc = run_changes(one, two, tmp_path / "b.json", "--id", "CH99902", "--state", "ZZ")
    assert doc["summary"]["old_entities"] == 1
    md = tmp_path / "c.md"
    main(["changes", str(one), str(two), "--id", "CH99902", "--state", "zz", "--out", str(md)])
    assert "Filter: 340B ID CH99902; state ZZ" in md.read_text(encoding="utf-8")


def test_unknown_id_is_an_error_naming_it(
    day1: Path, day2: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    capsys.readouterr()
    out = tmp_path / "r.md"
    code = main(
        ["changes", str(one), str(two), "--id", "CH99901", "--id", "CH00000", "--out", str(out)]
    )
    assert code == 2
    assert "CH00000 is in neither snapshot" in capsys.readouterr().err
    assert not out.exists()
    # An ID found in only one snapshot is fine: it was added or removed.
    assert main(["changes", str(one), str(two), "--id", "CH99907", "--out", str(out)]) in (0, 3)


def test_tripwire_ignores_the_filter(write_json: Writer, tmp_path: Path) -> None:
    records = [{"340B ID": f"CH{n:05d}", "Entity Name": f"Example {n}"} for n in range(100)]
    changed = [{**records[0], "Entity Name": "Example Renamed"}, *records[1:]]
    a, b = write_json(records, "a.json"), write_json(changed, "b.json")
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    main(["snapshot", str(a), "--date", "2026-01-01", "--out", str(one)])
    main(["snapshot", str(b), "--date", "2026-01-02", "--out", str(two)])
    out = tmp_path / "r.json"
    # Alone, the filtered set is 100% changed. The whole file is 1% changed: ordinary.
    code, doc = run_changes(one, two, out, "--id", "CH00000")
    assert code == 0
    assert doc["tripwire"]["reasons"] == []
    assert doc["summary"]["counts"]["field_changes"] == 1
    # And the reverse: the whole file trips even if the filtered set looks ordinary.
    bad = write_json([], "empty.json")
    three = tmp_path / "three.json"
    main(
        [
            "snapshot",
            str(write_json(records[:1], "c.json")),
            "--date",
            "2026-01-03",
            "--out",
            str(three),
        ]
    )
    code, doc = run_changes(one, three, out, "--id", "CH00000")
    assert code == 3
    assert bad.exists()
    assert any("fell from 100 to 1" in r for r in doc["tripwire"]["reasons"])


def test_no_filter_json_has_an_empty_filter_object(day1: Path, day2: Path, tmp_path: Path) -> None:
    one, two = make_snapshots(day1, day2, tmp_path)
    _, doc = run_changes(one, two, tmp_path / "r.json")
    assert doc["filter"] == {"ids": [], "state": None}


def test_inspect_shows_unrecognised_values_and_duplicates(
    write_json: Writer, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_json(
        [
            {
                "340B ID": "CH99901",
                "Participating": "Perhaps-secret-value",
                "Contract Pharmacies": [
                    {"Pharmacy ID": "P1", "Contract ID": "C1", "Pharmacy Name": "First"},
                    {"Pharmacy ID": "P1", "Contract ID": "C1", "Pharmacy Name": "Second"},
                ],
            }
        ],
        "x.json",
    )
    assert main(["inspect", str(path)]) == 0
    printed = capsys.readouterr().out
    assert "entity.participating: 1" in printed
    assert "Perhaps-secret-value" not in printed
    assert "later ones dropped): 1" in printed
    assert "contract pharmacies: 1" in printed
