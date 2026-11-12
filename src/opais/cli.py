"""Command line: make a snapshot, compare two snapshots, inspect an export, or pull one."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from opais import __version__
from opais.changes import ChangeFilter, FilterError, compare, tripwire
from opais.export import ExportError, read_export
from opais.model import in_state
from opais.pull import DEFAULT_TIMEOUT_SECONDS, PullError, pull
from opais.render import format_read_report, to_json, to_markdown
from opais.snapshot import SnapshotError, read_snapshot, write_snapshot

#: Exit codes: 0 ordinary, 2 an error (or nothing read), 3 the tripwire has a reason.
EXIT_OK = 0
EXIT_ERROR = 2
EXIT_TRIPWIRE = 3


def _snapshot(args: argparse.Namespace) -> int:
    result = read_export(args.export)
    entities = result.entities
    if args.state:
        entities = in_state(entities, args.state)
    print(f"read {len(result.entities)} entities from {args.export.name}")
    if args.state:
        print(f"kept {len(entities)} with street state {args.state.upper()}")
    print(format_read_report(result.report), end="")
    if not result.entities:
        print("error: no entity was read", file=sys.stderr)
        return EXIT_ERROR
    write_snapshot(
        entities,
        args.out,
        taken_on=args.date,
        source_sha256=result.sha256,
        source_bytes=result.size_bytes,
    )
    print(f"wrote {len(entities)} entities to {args.out}")
    return EXIT_OK


def _changes(args: argparse.Namespace) -> int:
    old, new = read_snapshot(args.old), read_snapshot(args.new)
    report = compare(old, new, ChangeFilter.make(args.id or (), args.state))
    # The tripwire is about the whole file, so it always uses the unfiltered comparison.
    reasons = tripwire(compare(old, new))
    text = to_json(report, reasons) if args.format == "json" else to_markdown(report, reasons)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(text.encode("utf-8"))
        print(f"wrote the report to {args.out}")
    else:
        print(text, end="")
    for reason in reasons:
        print(f"tripwire: {reason}", file=sys.stderr)
    return EXIT_TRIPWIRE if reasons else EXIT_OK


def _inspect(args: argparse.Namespace) -> int:
    result = read_export(args.export)
    print(format_read_report(result.report), end="")
    return EXIT_OK


def _pull(args: argparse.Namespace) -> int:
    result = pull(args.out, timeout_seconds=args.timeout, browser=args.browser)
    print(result.summary_line())
    return EXIT_OK


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date like 2026-01-31") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opais", description=__doc__)
    parser.add_argument("--version", action="version", version=f"clinx-radar {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    snap = commands.add_parser("snapshot", help="read an export and write a snapshot")
    snap.add_argument("export", type=Path, help="the HRSA daily export (JSON)")
    snap.add_argument("--date", required=True, type=_iso_date, help="the day of the export")
    snap.add_argument("--out", required=True, type=Path, help="the snapshot file to write")
    snap.add_argument("--state", help="keep only entities whose street address is in this state")

    chg = commands.add_parser("changes", help="compare two snapshots")
    chg.add_argument("old", type=Path, help="the earlier snapshot")
    chg.add_argument("new", type=Path, help="the later snapshot")
    chg.add_argument("--format", choices=["md", "json"], default="md")
    chg.add_argument("--out", type=Path, help="write the report here instead of printing it")
    chg.add_argument("--state", help="compare only entities whose street address is in this state")
    chg.add_argument("--id", action="append", help="compare only this 340B ID (repeat for several)")

    ins = commands.add_parser("inspect", help="show which keys of an export the reader knows")
    ins.add_argument("export", type=Path, help="the HRSA daily export (JSON)")

    get = commands.add_parser("pull", help="get today's export from HRSA's public reports page")
    get.add_argument("--out", required=True, type=Path, help="the folder to save the zip in")
    get.add_argument("--browser", type=Path, help="path of an installed Chromium-family browser")
    get.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="seconds to wait for the download to start",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Return 0 ordinary, 2 error, 3 tripwire, 4 to 12 a stopped pull."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            return _snapshot(args)
        if args.command == "changes":
            return _changes(args)
        if args.command == "pull":
            return _pull(args)
        return _inspect(args)
    except PullError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.code
    except (ExportError, SnapshotError, FilterError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
