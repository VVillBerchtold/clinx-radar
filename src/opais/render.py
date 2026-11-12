"""Turn a change report, or a read report, into Markdown, JSON or plain text.

The wording says what changed between two dates. It never says why.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from opais.changes import SECTIONS, ChangeReport
from opais.export import ReadReport

__all__ = ["ROW_CAP", "format_read_report", "to_json", "to_markdown"]

#: A Markdown section shows at most this many rows. The JSON report has all of them.
ROW_CAP = 200

_ENTITY = (("340B ID", "id_340b"), ("Name", "name"))
_STATUS = (
    ("340B ID", "id_340b"),
    ("Name", "name"),
    ("Participating before", "old_participating"),
    ("Participating after", "new_participating"),
    ("Termination date before", "old_termination_date"),
    ("Termination date after", "new_termination_date"),
)
_PHARMACY = (
    ("340B ID", "id_340b"),
    ("Pharmacy ID", "pharmacy_id"),
    ("Contract ID", "contract_id"),
    ("Pharmacy name", "pharmacy_name"),
)
_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "entities_added": _ENTITY,
    "entities_removed": _ENTITY,
    "terminations": _STATUS,
    "reinstatements": _STATUS,
    "field_changes": (
        ("340B ID", "id_340b"),
        ("Name", "name"),
        ("Field", "field"),
        ("Before", "old"),
        ("After", "new"),
    ),
    "pharmacies_added": _PHARMACY,
    "pharmacies_removed": _PHARMACY,
    "pharmacies_terminated": (*_PHARMACY, ("Termination date", "termination_date")),
}


def _cell(value: object) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _table(rows: tuple[object, ...], columns: tuple[tuple[str, str], ...]) -> list[str]:
    lines = [
        "| " + " | ".join(title for title, _ in columns) + " |",
        "|" + "|".join(" --- " for _ in columns) + "|",
    ]
    for row in rows[:ROW_CAP]:
        cells = (_cell(getattr(row, attribute)) for _, attribute in columns)
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def to_markdown(report: ChangeReport, reasons: tuple[str, ...]) -> str:
    """Render a readable report. Sections over ``ROW_CAP`` rows say how many more the JSON has."""
    s = report.summary
    lines = [
        f"# Changes between {s.old_date.isoformat()} and {s.new_date.isoformat()}",
        "",
        f"- Old snapshot: {s.old_date.isoformat()}, source SHA-256 `{s.old_sha256}`",
        f"- New snapshot: {s.new_date.isoformat()}, source SHA-256 `{s.new_sha256}`",
        f"- Entities: {s.old_entities} before, {s.new_entities} after",
    ]
    if s.filter is not None:
        lines.insert(1, "")
        lines.insert(2, s.filter.describe())
    lines += [
        "",
        "## Summary",
        "",
        "| Kind | Count |",
        "| --- | --- |",
    ]
    lines += [f"| {title} | {s.counts[attribute]} |" for attribute, title in SECTIONS]
    lines += ["", "## Tripwire", ""]
    if s.filter is not None:
        lines += ["The tripwire is computed on the whole file, not on the filtered set.", ""]
    if reasons:
        lines.append("The amount of change is unusual for these reasons:")
        lines.append("")
        lines += [f"- {reason}" for reason in reasons]
    else:
        lines.append("No tripwire reason was found.")
    for attribute, title in SECTIONS:
        rows = getattr(report, attribute)
        if not rows:
            continue
        lines += ["", f"## {title} ({len(rows)})", ""]
        lines += _table(rows, _COLUMNS[attribute])
        if len(rows) > ROW_CAP:
            lines += ["", f"{len(rows) - ROW_CAP} more rows are in the JSON report."]
    return "\n".join(lines) + "\n"


def to_json(report: ChangeReport, reasons: tuple[str, ...]) -> str:
    """Render the full report as JSON with sorted keys. The same report gives the same text."""
    s = report.summary
    document = {
        "summary": {
            "old_date": s.old_date.isoformat(),
            "new_date": s.new_date.isoformat(),
            "old_source_sha256": s.old_sha256,
            "new_source_sha256": s.new_sha256,
            "old_entities": s.old_entities,
            "new_entities": s.new_entities,
            "counts": s.counts,
        },
        "filter": {"ids": list(s.filter.ids), "state": s.filter.state}
        if s.filter
        else {"ids": [], "state": None},
        "tripwire": {
            "reasons": list(reasons),
            "computed_on": "all entities in both snapshots, whatever the filter",
        },
        "changes": {
            attribute: [asdict(row) for row in getattr(report, attribute)]
            for attribute, _title in SECTIONS
        },
    }
    return json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def _counts(title: str, counts: dict[str, int], none: str) -> list[str]:
    lines = [f"{title}:"]
    lines += [f"  {key}: {count}" for key, count in counts.items()] or [f"  {none}"]
    return lines


def format_read_report(report: ReadReport) -> str:
    """Describe what the reader saw: counts, mapped fields, unmapped keys and dropped fields.

    Only key names and counts appear. No value from the export is ever printed.
    """
    lines = [
        f"records read: {report.record_count}",
        f"shipping addresses: {report.shipping_address_count}",
        f"contract pharmacies: {report.contract_pharmacy_count}",
    ]
    lines += _counts("mapped fields seen (keys found)", report.mapped, "none")
    lines += _counts("unmapped keys (not in the key table; not stored)", report.unmapped, "none")
    lines += _counts(
        "personal or free-text fields dropped (never stored)", report.dropped, "none seen"
    )
    lines += _counts("known keys with nothing we keep", report.ignored, "none seen")
    lines += _counts(
        "unrecognised yes/no values (read as blank; values not shown)",
        report.unrecognised,
        "none seen",
    )
    lines.append(
        f"duplicate contract pharmacies (first kept, later ones dropped): "
        f"{report.duplicate_pharmacies}"
    )
    return "\n".join(lines) + "\n"
