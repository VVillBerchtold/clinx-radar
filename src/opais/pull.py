"""Get HRSA's Covered Entity Daily Export by pressing the button on its public page.

HRSA publishes no direct address for the file. Its reports page is an interactive app that hands
the file to the browser when the button is pressed, so this module opens that one page in a plain
headless browser, presses that one button once and saves what the site sends.

It makes one attempt. It changes nothing about the browser to look like something else, and it
stops with a plain message if the page is not as expected. Everything after the browser step
(checking, naming, hashing, the summary line) is ordinary code that needs no browser.

The raw export names people. This module never prints or logs anything from inside the file.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REPORTS_URL = "https://340bopais.hrsa.gov/reports"
BUTTON_NAME = "Covered Entity Daily Export (JSON)"
MEMBER_NAME = "OPA_CE_DAILY_PUBLIC.JSON"
MIN_ZIP_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 600

EXIT_NO_EXTRA = 4
EXIT_PAGE_STATUS = 5
EXIT_BUTTON_COUNT = 6
EXIT_NO_DOWNLOAD = 7
EXIT_NOT_ZIP = 8
EXIT_WRONG_MEMBER = 9
EXIT_TOO_SMALL = 10
EXIT_NOT_JSON = 11
EXIT_BROWSER = 12

INSTALL_HINT = (
    "the 'pull' extra is not installed: run `uv sync --extra pull`, "
    "then `uv run playwright install chromium` (or pass --browser)"
)


class PullError(Exception):
    """The pull stopped. `code` is the exit code for the command line."""

    def __init__(self, code: int, message: str) -> None:
        """Keep the exit code beside the message."""
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PullResult:
    """What was saved: where, how big, its hash, when, and the day in its name."""

    path: Path
    size_bytes: int
    sha256: str
    pulled_at: datetime
    export_date: date | None

    def summary_line(self) -> str:
        """One JSON line about the file. Nothing from inside the file."""
        return json.dumps(
            {
                "file": self.path.name,
                "bytes": self.size_bytes,
                "sha256": self.sha256,
                "pulled_at": self.pulled_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "export_date": self.export_date.isoformat() if self.export_date else None,
            }
        )


#: The browser step: save the site's file into the folder, return (path, name the site suggested).
Fetch = Callable[[Path, float, Path | None], tuple[Path, str]]


def safe_name(suggested: str) -> str:
    """Return a plain base name for the saved file, whatever the site suggested."""
    base = suggested.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    if not base:
        base = "opais-export"
    if not base.lower().endswith(".zip"):
        base += ".zip"
    return base[:120]


def export_date_of(name: str) -> date | None:
    """Return the day in a name like 340B_CoveredEntityJson_Daily_20261111_204200.zip, if any."""
    found = re.search(r"_(\d{4})(\d{2})(\d{2})_\d{6}", name)
    if not found:
        return None
    try:
        return date(int(found[1]), int(found[2]), int(found[3]))
    except ValueError:
        return None


def check_zip(path: Path) -> None:
    """Refuse a file that is not the expected export. Reads only the first bytes of the member."""
    if not zipfile.is_zipfile(path):
        raise PullError(EXIT_NOT_ZIP, "the file HRSA's page sent is not a zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names != [MEMBER_NAME]:
            raise PullError(
                EXIT_WRONG_MEMBER,
                f"the zip should hold exactly one file named {MEMBER_NAME}; it holds {len(names)}",
            )
        if path.stat().st_size < MIN_ZIP_BYTES:
            raise PullError(
                EXIT_TOO_SMALL,
                f"the zip is {path.stat().st_size} bytes, under the floor of {MIN_ZIP_BYTES}",
            )
        with archive.open(MEMBER_NAME) as member:
            opening = member.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
        if not opening.startswith((b"{", b"[")):
            raise PullError(EXIT_NOT_JSON, f"{MEMBER_NAME} does not start like JSON")


def sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file, read a block at a time."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_with_browser(
    out_dir: Path, timeout_seconds: float, browser: Path | None
) -> tuple[Path, str]:
    """Open the page, press the button once, save the download. One attempt, default browser."""
    try:
        from playwright.sync_api import Error as BrowserError  # noqa: PLC0415 (optional extra)
        from playwright.sync_api import TimeoutError as BrowserTimeout  # noqa: PLC0415
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError as error:
        raise PullError(EXIT_NO_EXTRA, INSTALL_HINT) from error

    temporary = out_dir / ".opais-pull.part"
    try:
        with sync_playwright() as driver:
            launched = driver.chromium.launch(
                headless=True, executable_path=str(browser) if browser else None
            )
            try:
                page = launched.new_context(accept_downloads=True).new_page()
                response = page.goto(REPORTS_URL, wait_until="networkidle", timeout=90_000)
                status = response.status if response else None
                if status != 200:
                    raise PullError(
                        EXIT_PAGE_STATUS, f"HRSA's reports page answered {status}, not 200"
                    )
                button = page.get_by_role("button", name=BUTTON_NAME, exact=True)
                count = button.count()
                if count != 1:
                    raise PullError(
                        EXIT_BUTTON_COUNT,
                        f"expected one button named '{BUTTON_NAME}' on the page, found {count}",
                    )
                try:
                    with page.expect_download(timeout=timeout_seconds * 1000) as waiting:
                        button.click()
                except BrowserTimeout as error:
                    raise PullError(
                        EXIT_NO_DOWNLOAD, f"no download started within {timeout_seconds:g} seconds"
                    ) from error
                download = waiting.value
                download.save_as(temporary)
                return temporary, download.suggested_filename
            finally:
                launched.close()
    except BrowserError as error:
        first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
        raise PullError(EXIT_BROWSER, f"the browser could not do it: {first_line}") from error


def pull(
    out_dir: Path,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    browser: Path | None = None,
    fetch: Fetch = fetch_with_browser,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PullResult:
    """Fetch the export into `out_dir`, check it, and describe it. Raises PullError."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved, suggested = fetch(out_dir, timeout_seconds, browser)
    try:
        check_zip(saved)
    except PullError:
        saved.unlink(missing_ok=True)
        raise
    target = out_dir / safe_name(suggested)
    saved.replace(target)
    return PullResult(
        path=target,
        size_bytes=target.stat().st_size,
        sha256=sha256_of(target),
        pulled_at=now(),
        export_date=export_date_of(target.name),
    )
