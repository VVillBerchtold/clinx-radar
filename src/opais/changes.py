"""Compare two snapshots and say what changed, and whether the amount is unusual.

The report says what differs between two dates. It never says why.

Terminations, field changes and contract pharmacy changes are looked for only in
entities that appear in both snapshots. An entity that was added or removed is listed
once, as added or removed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from opais.model import (
    ContractPharmacy,
    CoveredEntity,
    date_text,
    in_state,
    numbers_text,
    pharmacy_key,
)
from opais.snapshot import Snapshot

__all__ = [
    "SECTIONS",
    "WATCHED_FIELDS",
    "ChangeFilter",
    "ChangeReport",
    "ChangeSummary",
    "EntityRef",
    "FieldChange",
    "FilterError",
    "PharmacyRef",
    "StatusChange",
    "compare",
    "tripwire",
]


class FilterError(ValueError):
    """A filter names a 340B ID that is in neither snapshot."""


@dataclass(frozen=True, slots=True)
class ChangeFilter:
    """Limit a comparison to some 340B IDs and/or one street-address state.

    When both are given, an entity must match both. IDs match ignoring case and
    surrounding spaces.
    """

    ids: tuple[str, ...] = ()
    state: str | None = None

    @classmethod
    def make(cls, ids: Iterable[str] = (), state: str | None = None) -> ChangeFilter:
        """Normalize IDs (strip, upper case, sorted, no repeats) and the state."""
        clean = tuple(sorted({i.strip().upper() for i in ids if i.strip()}))
        return cls(clean, state.strip().upper() if state and state.strip() else None)

    def describe(self) -> str:
        """Say in one plain line which filter was applied."""
        parts = []
        if self.ids:
            parts.append("340B ID " + ", ".join(self.ids))
        if self.state:
            parts.append(f"state {self.state}")
        return "Filter: " + "; ".join(parts)


@dataclass(frozen=True, slots=True)
class EntityRef:
    """An entity that is in one snapshot and not the other."""

    id_340b: str
    name: str | None


@dataclass(frozen=True, slots=True)
class StatusChange:
    """An entity whose termination date or participating flag changed."""

    id_340b: str
    name: str | None
    old_participating: bool | None
    new_participating: bool | None
    old_termination_date: str | None
    new_termination_date: str | None


@dataclass(frozen=True, slots=True)
class FieldChange:
    """One watched field of one entity, with its old and new value."""

    id_340b: str
    name: str | None
    field: str
    old: str | None
    new: str | None


@dataclass(frozen=True, slots=True)
class PharmacyRef:
    """A contract pharmacy arrangement under one entity."""

    id_340b: str
    pharmacy_id: str | None
    contract_id: str | None
    pharmacy_name: str | None
    termination_date: str | None


@dataclass(frozen=True, slots=True)
class ChangeSummary:
    """Counts, and the dates and source hashes of the two snapshots."""

    old_date: date
    new_date: date
    old_sha256: str
    new_sha256: str
    old_entities: int
    new_entities: int
    counts: dict[str, int] = field(default_factory=dict)
    filter: ChangeFilter | None = None


@dataclass(frozen=True, slots=True)
class ChangeReport:
    """Everything that differs between two snapshots, each kind sorted."""

    summary: ChangeSummary
    entities_added: tuple[EntityRef, ...] = ()
    entities_removed: tuple[EntityRef, ...] = ()
    terminations: tuple[StatusChange, ...] = ()
    reinstatements: tuple[StatusChange, ...] = ()
    field_changes: tuple[FieldChange, ...] = ()
    pharmacies_added: tuple[PharmacyRef, ...] = ()
    pharmacies_removed: tuple[PharmacyRef, ...] = ()
    pharmacies_terminated: tuple[PharmacyRef, ...] = ()

    @property
    def touched_entities(self) -> int:
        """How many distinct entities appear in any kind of change."""
        ids: set[str] = set()
        for attribute, _title in SECTIONS:
            ids.update(row.id_340b for row in getattr(self, attribute))
        return len(ids)


#: Each kind of change: the ChangeReport attribute and the title used in reports.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("entities_added", "Entities added"),
    ("entities_removed", "Entities removed"),
    ("terminations", "Terminations"),
    ("reinstatements", "Reinstatements"),
    ("field_changes", "Field changes"),
    ("pharmacies_added", "Contract pharmacies added"),
    ("pharmacies_removed", "Contract pharmacies removed"),
    ("pharmacies_terminated", "Contract pharmacies newly terminated"),
)

#: The entity fields compared. ``edit_date`` is left out on purpose: it changes whenever
#: HRSA's record is edited, and says nothing by itself.
WATCHED_FIELDS: tuple[tuple[str, Callable[[CoveredEntity], str | None]], ...] = (
    ("name", lambda e: e.name),
    ("subdivision_name", lambda e: e.subdivision_name),
    ("entity_type", lambda e: e.entity_type),
    ("street.line1", lambda e: e.street.line1),
    ("street.line2", lambda e: e.street.line2),
    ("street.line3", lambda e: e.street.line3),
    ("street.city", lambda e: e.street.city),
    ("street.state", lambda e: e.street.state),
    ("street.zip", lambda e: e.street.zip),
    ("street.zip4", lambda e: e.street.zip4),
    ("billing_organization", lambda e: e.billing_organization),
    ("medicaid_number", lambda e: numbers_text(e.medicaid_number, e.medicaid_numbers)),
    ("npi", lambda e: numbers_text(e.npi, e.npi_numbers)),
    ("medicare_provider_number", lambda e: e.medicare_provider_number),
    ("grant_number", lambda e: e.grant_number),
)


def _blank(value: str | None) -> str:
    return value or ""


def _pharmacy_ref(entity_id: str, pharmacy: ContractPharmacy) -> PharmacyRef:
    return PharmacyRef(
        id_340b=entity_id,
        pharmacy_id=pharmacy.pharmacy_id,
        contract_id=pharmacy.contract_id,
        pharmacy_name=pharmacy.name,
        termination_date=date_text(pharmacy.termination_date),
    )


def _pharmacy_sort(ref: PharmacyRef) -> tuple[str, str, str, str]:
    return (
        ref.id_340b,
        _blank(ref.pharmacy_id),
        _blank(ref.contract_id),
        _blank(ref.pharmacy_name),
    )


def _status_change(old: CoveredEntity, new: CoveredEntity) -> StatusChange:
    return StatusChange(
        id_340b=new.id_340b,
        name=new.name,
        old_participating=old.participating,
        new_participating=new.participating,
        old_termination_date=date_text(old.termination_date),
        new_termination_date=date_text(new.termination_date),
    )


def _pharmacy_changes(
    old: CoveredEntity, new: CoveredEntity
) -> tuple[list[PharmacyRef], list[PharmacyRef], list[PharmacyRef]]:
    before = {pharmacy_key(p): p for p in old.contract_pharmacies}
    after = {pharmacy_key(p): p for p in new.contract_pharmacies}
    added = [_pharmacy_ref(new.id_340b, after[k]) for k in after.keys() - before.keys()]
    removed = [_pharmacy_ref(old.id_340b, before[k]) for k in before.keys() - after.keys()]
    terminated = [
        _pharmacy_ref(new.id_340b, after[k])
        for k in after.keys() & before.keys()
        if before[k].termination_date is None and after[k].termination_date is not None
    ]
    return added, removed, terminated


def _filtered(snapshot: Snapshot, flt: ChangeFilter) -> Snapshot:
    entities = snapshot.entities
    if flt.ids:
        entities = tuple(e for e in entities if e.id_340b.strip().upper() in flt.ids)
    if flt.state:
        entities = in_state(entities, flt.state)
    return Snapshot(replace(snapshot.header, entity_count=len(entities)), entities)


def compare(old: Snapshot, new: Snapshot, flt: ChangeFilter | None = None) -> ChangeReport:
    """Compare two snapshots and return every difference, each kind sorted.

    With a filter, only the matching entities are compared, and the counts in the
    summary describe that set. A 340B ID in the filter that is in neither snapshot
    raises ``FilterError``, so a typo is not read as "no changes".
    """
    if flt is not None and (flt.ids or flt.state):
        known = {e.id_340b.strip().upper() for e in (*old.entities, *new.entities)}
        missing = [i for i in flt.ids if i not in known]
        if missing:
            raise FilterError("340B ID " + ", ".join(missing) + " is in neither snapshot")
        old, new = _filtered(old, flt), _filtered(new, flt)
    else:
        flt = None
    before = {e.id_340b: e for e in old.entities}
    after = {e.id_340b: e for e in new.entities}
    terminations: list[StatusChange] = []
    reinstatements: list[StatusChange] = []
    fields: list[FieldChange] = []
    added: list[PharmacyRef] = []
    removed: list[PharmacyRef] = []
    terminated: list[PharmacyRef] = []
    for entity_id in before.keys() & after.keys():
        was, now = before[entity_id], after[entity_id]
        ended = (was.termination_date is None and now.termination_date is not None) or (
            was.participating is True and now.participating is False
        )
        restored = (was.termination_date is not None and now.termination_date is None) or (
            was.participating is False and now.participating is True
        )
        if ended:
            terminations.append(_status_change(was, now))
        elif restored:
            reinstatements.append(_status_change(was, now))
        for label, getter in WATCHED_FIELDS:
            if getter(was) != getter(now):
                fields.append(FieldChange(entity_id, now.name, label, getter(was), getter(now)))
        p_added, p_removed, p_terminated = _pharmacy_changes(was, now)
        added += p_added
        removed += p_removed
        terminated += p_terminated

    def refs(ids: set[str], source: dict[str, CoveredEntity]) -> tuple[EntityRef, ...]:
        return tuple(EntityRef(i, source[i].name) for i in sorted(ids))

    def by_id(rows: list[StatusChange]) -> tuple[StatusChange, ...]:
        return tuple(sorted(rows, key=lambda r: r.id_340b))

    entities_added = refs(after.keys() - before.keys(), after)
    entities_removed = refs(before.keys() - after.keys(), before)
    terminations_sorted = by_id(terminations)
    reinstatements_sorted = by_id(reinstatements)
    field_changes = tuple(
        sorted(fields, key=lambda r: (r.id_340b, r.field, _blank(r.old), _blank(r.new)))
    )
    pharmacies_added = tuple(sorted(added, key=_pharmacy_sort))
    pharmacies_removed = tuple(sorted(removed, key=_pharmacy_sort))
    pharmacies_terminated = tuple(sorted(terminated, key=_pharmacy_sort))
    counts = {
        "entities_added": len(entities_added),
        "entities_removed": len(entities_removed),
        "terminations": len(terminations_sorted),
        "reinstatements": len(reinstatements_sorted),
        "field_changes": len(field_changes),
        "pharmacies_added": len(pharmacies_added),
        "pharmacies_removed": len(pharmacies_removed),
        "pharmacies_terminated": len(pharmacies_terminated),
    }
    return ChangeReport(
        summary=ChangeSummary(
            old_date=old.header.taken_on,
            new_date=new.header.taken_on,
            old_sha256=old.header.source_sha256,
            new_sha256=new.header.source_sha256,
            old_entities=len(before),
            new_entities=len(after),
            counts=counts,
            filter=flt,
        ),
        entities_added=entities_added,
        entities_removed=entities_removed,
        terminations=terminations_sorted,
        reinstatements=reinstatements_sorted,
        field_changes=field_changes,
        pharmacies_added=pharmacies_added,
        pharmacies_removed=pharmacies_removed,
        pharmacies_terminated=pharmacies_terminated,
    )


def tripwire(
    report: ChangeReport,
    *,
    max_removed_share: Decimal = Decimal("0.02"),
    max_changed_share: Decimal = Decimal("0.10"),
) -> tuple[str, ...]:
    """Return plain-word reasons the change looks unusual. Empty when it looks ordinary.

    The two shares are starting values, not findings. They are fractions of the old
    snapshot's entity count.
    """
    s = report.summary
    reasons: list[str] = []
    if s.new_entities == 0:
        reasons.append("The new snapshot has no entities.")
    if s.old_entities > 0:
        fell = s.old_entities - s.new_entities
        if Decimal(fell) > max_removed_share * s.old_entities:
            reasons.append(
                f"The entity count fell from {s.old_entities} to {s.new_entities} "
                f"({fell} fewer), more than {_percent(max_removed_share)} of the old count."
            )
        touched = report.touched_entities
        if Decimal(touched) > max_changed_share * s.old_entities:
            reasons.append(
                f"{touched} entities appear in a change, more than "
                f"{_percent(max_changed_share)} of the old count of {s.old_entities}."
            )
    if s.new_date <= s.old_date:
        reasons.append(
            f"The new snapshot is dated {s.new_date.isoformat()}, which is not later than the "
            f"old snapshot's date, {s.old_date.isoformat()}."
        )
    if s.new_sha256 == s.old_sha256:
        reasons.append("Both snapshots were made from a file with the same SHA-256.")
    return tuple(reasons)


def _percent(share: Decimal) -> str:
    return f"{(share * 100).normalize():f}%"
