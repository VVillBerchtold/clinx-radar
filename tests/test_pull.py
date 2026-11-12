"""The pull command, without a network or a browser. Every file here is made up."""

from __future__ import annotations

import builtins
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from opais import pull as pull_module
from opais.cli import main
from opais.pull import (
    EXIT_NO_EXTRA,
    EXIT_NOT_JSON,
    EXIT_NOT_ZIP,
    EXIT_TOO_SMALL,
    EXIT_WRONG_MEMBER,
    MEMBER_NAME,
    Fetch,
    PullError,
    check_zip,
    export_date_of,
    fetch_with_browser,
    pull,
    safe_name,
)

SITE_NAME = "340B_CoveredEntityJson_Daily_20261111_204200.zip"


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def good_content() -> bytes:
    return b'[{"made_up": true}]' + b" " * 2048


@pytest.fixture(autouse=True)
def small_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pull_module, "MIN_ZIP_BYTES", 1024)


def fake_fetch(content: dict[str, bytes] | bytes, suggested: str = SITE_NAME) -> Fetch:
    def fetch(out_dir: Path, timeout: float, browser: Path | None) -> tuple[Path, str]:
        saved = out_dir / ".opais-pull.part"
        if isinstance(content, bytes):
            saved.write_bytes(content)
        else:
            make_zip(saved, content)
        return saved, suggested

    return fetch


def test_a_good_zip_is_saved_under_the_sites_name_and_described(tmp_path: Path) -> None:
    result = pull(
        tmp_path / "raw",
        fetch=fake_fetch({MEMBER_NAME: good_content()}),
        now=lambda: datetime(2026, 11, 12, 3, 4, 5, tzinfo=UTC),
    )
    assert result.path == tmp_path / "raw" / SITE_NAME
    assert result.export_date == date(2026, 11, 11)
    line = json.loads(result.summary_line())
    assert set(line) == {"file", "bytes", "sha256", "pulled_at", "export_date"}
    assert line["pulled_at"] == "2026-11-12T03:04:05Z"
    assert line["bytes"] == result.path.stat().st_size
    assert len(line["sha256"]) == 64
    assert "made_up" not in result.summary_line()
    assert [p.name for p in (tmp_path / "raw").iterdir()] == [SITE_NAME]


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"<html>not a zip</html>", EXIT_NOT_ZIP),
        ({"SOMETHING_ELSE.JSON": good_content()}, EXIT_WRONG_MEMBER),
        ({MEMBER_NAME: good_content(), "second.txt": b"x"}, EXIT_WRONG_MEMBER),
        ({MEMBER_NAME: b"[]"}, EXIT_TOO_SMALL),
        ({MEMBER_NAME: b"<xml/>" + b" " * 2048}, EXIT_NOT_JSON),
    ],
)
def test_a_wrong_file_stops_the_pull_and_is_not_kept(
    tmp_path: Path, content: dict[str, bytes] | bytes, code: int
) -> None:
    with pytest.raises(PullError) as stopped:
        pull(tmp_path, fetch=fake_fetch(content))
    assert stopped.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_check_zip_accepts_a_byte_order_mark(tmp_path: Path) -> None:
    check_zip(make_zip(tmp_path / "a.zip", {MEMBER_NAME: b"\xef\xbb\xbf" + good_content()}))


@pytest.mark.parametrize(
    ("suggested", "expected"),
    [
        (SITE_NAME, SITE_NAME),
        ("../../etc/passwd", "passwd.zip"),
        ("..\\..\\evil name?.zip", "evil_name_.zip"),
        (".hidden.zip", "hidden.zip"),
        ("", "opais-export.zip"),
    ],
)
def test_safe_name(suggested: str, expected: str) -> None:
    assert safe_name(suggested) == expected


def test_export_date_of() -> None:
    assert export_date_of(SITE_NAME) == date(2026, 11, 11)
    assert export_date_of("export.zip") is None
    assert export_date_of("x_20261341_000000.zip") is None


def test_missing_extra_gives_one_plain_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def no_playwright(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("playwright"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    with pytest.raises(PullError) as stopped:
        fetch_with_browser(tmp_path, 1, None)
    assert stopped.value.code == EXIT_NO_EXTRA
    assert main(["pull", "--out", str(tmp_path)]) == EXIT_NO_EXTRA
    error = capsys.readouterr().err
    assert error.count("\n") == 1
    assert "uv sync --extra pull" in error


def test_command_line_prints_only_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        pull_module, "fetch_with_browser", fake_fetch({MEMBER_NAME: good_content()})
    )
    monkeypatch.setattr(
        "opais.cli.pull",
        lambda out, **kw: pull(out, fetch=pull_module.fetch_with_browser),
    )
    assert main(["pull", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out)["file"] == SITE_NAME
