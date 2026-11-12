"""Write and read a normalized, deterministic snapshot file.

A snapshot is one JSON document. The same input always gives the same bytes: keys are
sorted, entities are sorted by 340B ID, and dates are ISO text when they could be parsed
(the original text otherwise). Nothing in it comes from a clock.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from opais.model import (
    Address,
    ContractPharmacy,
    CoveredEntity,
    ShippingAddress,
    StateNumber,
    date_text,
)

__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "Snapshot",
    "SnapshotError",
    "SnapshotHeader",
    "read_snapshot",
    "write_snapshot",
]

FORMAT_NAME = "clinx-radar snapshot"
FORMAT_VERSION = 1

Doc = dict[str, object]


class SnapshotError(ValueError):
    """A snapshot file is missing, damaged or of a version this library does not read."""


@dataclass(frozen=True, slots=True)
class SnapshotHeader:
    """The facts about a snapshot that are not entities."""

    taken_on: date
    source_sha256: str
    source_bytes: int
    entity_count: int
    format_version: int = FORMAT_VERSION


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A header and the entities, sorted by 340B ID."""

    header: SnapshotHeader
    entities: tuple[CoveredEntity, ...]


# --- writing ---------------------------------------------------------------


def _put(doc: Doc, key: str, value: object) -> None:
    if value is not None:
        doc[key] = value


def _address_doc(address: Address) -> Doc:
    doc: Doc = {}
    _put(doc, "line1", address.line1)
    _put(doc, "line2", address.line2)
    _put(doc, "line3", address.line3)
    _put(doc, "city", address.city)
    _put(doc, "state", address.state)
    _put(doc, "zip", address.zip)
    _put(doc, "zip4", address.zip4)
    return doc


def _canonical(doc: Doc) -> str:
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def _shipping_doc(item: ShippingAddress) -> Doc:
    doc: Doc = {}
    _put(doc, "is_street_address", item.is_street_address)
    _put(doc, "organization", item.organization)
    _put(doc, "address", _address_doc(item.address) or None)
    return doc


def _pharmacy_doc(item: ContractPharmacy) -> Doc:
    doc: Doc = {}
    _put(doc, "contract_id", item.contract_id)
    _put(doc, "pharmacy_id", item.pharmacy_id)
    _put(doc, "name", item.name)
    _put(doc, "begin_date", date_text(item.begin_date))
    _put(doc, "termination_date", date_text(item.termination_date))
    _put(doc, "address", _address_doc(item.address) or None)
    return doc


def _numbers_doc(items: Iterable[StateNumber]) -> list[Doc]:
    docs = []
    for item in items:
        doc: Doc = {"number": item.number}
        _put(doc, "state", item.state)
        docs.append(doc)
    return sorted(docs, key=lambda d: (str(d.get("state", "")), str(d["number"])))


def _entity_doc(entity: CoveredEntity) -> Doc:
    doc: Doc = {"id_340b": entity.id_340b}
    _put(doc, "ce_id", entity.ce_id)
    _put(doc, "parent_340b_id", entity.parent_340b_id)
    _put(doc, "parent_ce_id", entity.parent_ce_id)
    _put(doc, "entity_type", entity.entity_type)
    _put(doc, "participating", entity.participating)
    _put(doc, "participating_start_date", date_text(entity.participating_start_date))
    _put(doc, "termination_date", date_text(entity.termination_date))
    _put(doc, "termination_reason", entity.termination_reason)
    _put(doc, "name", entity.name)
    _put(doc, "subdivision_name", entity.subdivision_name)
    _put(doc, "grant_number", entity.grant_number)
    _put(doc, "site_id", entity.site_id)
    _put(doc, "medicare_provider_number", entity.medicare_provider_number)
    _put(doc, "street", _address_doc(entity.street) or None)
    _put(doc, "billing_organization", entity.billing_organization)
    _put(doc, "billing", _address_doc(entity.billing) or None)
    _put(doc, "medicaid_number", entity.medicaid_number)
    _put(doc, "npi", entity.npi)
    medicaid_numbers = _numbers_doc(entity.medicaid_numbers)
    npi_numbers = _numbers_doc(entity.npi_numbers)
    if medicaid_numbers:
        doc["medicaid_numbers"] = medicaid_numbers
    if npi_numbers:
        doc["npi_numbers"] = npi_numbers
    _put(doc, "certified_date", date_text(entity.certified_date))
    _put(doc, "rural", entity.rural)
    _put(doc, "edit_date", date_text(entity.edit_date))
    shipping = sorted((_shipping_doc(s) for s in entity.shipping_addresses), key=_canonical)
    pharmacies = sorted(
        (_pharmacy_doc(p) for p in entity.contract_pharmacies),
        key=lambda d: (str(d.get("pharmacy_id", "")), str(d.get("contract_id", "")), _canonical(d)),
    )
    if shipping:
        doc["shipping_addresses"] = shipping
    if pharmacies:
        doc["contract_pharmacies"] = pharmacies
    return doc


def write_snapshot(
    entities: Iterable[CoveredEntity],
    path: Path,
    *,
    taken_on: date,
    source_sha256: str,
    source_bytes: int,
) -> SnapshotHeader:
    """Write a snapshot file and return its header. Parent folders are created."""
    ordered = sorted(entities, key=lambda e: e.id_340b)
    header = SnapshotHeader(
        taken_on=taken_on,
        source_sha256=source_sha256,
        source_bytes=source_bytes,
        entity_count=len(ordered),
    )
    document: Doc = {
        "format": FORMAT_NAME,
        "format_version": header.format_version,
        "taken_on": taken_on.isoformat(),
        "source_sha256": source_sha256,
        "source_bytes": source_bytes,
        "entity_count": header.entity_count,
        "entities": [_entity_doc(e) for e in ordered],
    }
    text = json.dumps(document, sort_keys=True, indent=1, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return header


# --- reading ---------------------------------------------------------------


def _doc(value: object, where: str) -> Doc:
    if not isinstance(value, dict):
        raise SnapshotError(f"{where}: expected an object")
    return value


def _str(doc: Doc, key: str, where: str) -> str | None:
    value = doc.get(key)
    if value is None or isinstance(value, str):
        return value
    raise SnapshotError(f"{where}: {key} must be text")


def _bool(doc: Doc, key: str, where: str) -> bool | None:
    value = doc.get(key)
    if value is None or isinstance(value, bool):
        return value
    raise SnapshotError(f"{where}: {key} must be true or false")


def _address(value: object, where: str) -> Address:
    if value is None:
        return Address()
    d = _doc(value, where)
    return Address(
        line1=_str(d, "line1", where),
        line2=_str(d, "line2", where),
        line3=_str(d, "line3", where),
        city=_str(d, "city", where),
        state=_str(d, "state", where),
        zip=_str(d, "zip", where),
        zip4=_str(d, "zip4", where),
    )


def _list(doc: Doc, key: str, where: str) -> list[object]:
    value = doc.get(key, [])
    if not isinstance(value, list):
        raise SnapshotError(f"{where}: {key} must be a list")
    return value


def _numbers(doc: Doc, key: str, where: str) -> tuple[StateNumber, ...]:
    out = []
    for item in _list(doc, key, where):
        d = _doc(item, where)
        number = _str(d, "number", where)
        if number is None:
            raise SnapshotError(f"{where}: an item of {key} has no number")
        out.append(StateNumber(number=number, state=_str(d, "state", where)))
    return tuple(out)


def _entity(value: object, position: int) -> CoveredEntity:
    where = f"entity {position}"
    d = _doc(value, where)
    id_340b = _str(d, "id_340b", where)
    if id_340b is None:
        raise SnapshotError(f"{where}: no 340B ID")
    shipping = tuple(
        ShippingAddress(
            is_street_address=_bool(s, "is_street_address", where),
            organization=_str(s, "organization", where),
            address=_address(s.get("address"), where),
        )
        for s in (_doc(x, where) for x in _list(d, "shipping_addresses", where))
    )
    pharmacies = tuple(
        ContractPharmacy(
            contract_id=_str(p, "contract_id", where),
            pharmacy_id=_str(p, "pharmacy_id", where),
            name=_str(p, "name", where),
            begin_date=_str(p, "begin_date", where),
            termination_date=_str(p, "termination_date", where),
            address=_address(p.get("address"), where),
        )
        for p in (_doc(x, where) for x in _list(d, "contract_pharmacies", where))
    )
    return CoveredEntity(
        id_340b=id_340b,
        ce_id=_str(d, "ce_id", where),
        parent_340b_id=_str(d, "parent_340b_id", where),
        parent_ce_id=_str(d, "parent_ce_id", where),
        entity_type=_str(d, "entity_type", where),
        participating=_bool(d, "participating", where),
        participating_start_date=_str(d, "participating_start_date", where),
        termination_date=_str(d, "termination_date", where),
        termination_reason=_str(d, "termination_reason", where),
        name=_str(d, "name", where),
        subdivision_name=_str(d, "subdivision_name", where),
        grant_number=_str(d, "grant_number", where),
        site_id=_str(d, "site_id", where),
        medicare_provider_number=_str(d, "medicare_provider_number", where),
        street=_address(d.get("street"), where),
        billing_organization=_str(d, "billing_organization", where),
        billing=_address(d.get("billing"), where),
        medicaid_number=_str(d, "medicaid_number", where),
        npi=_str(d, "npi", where),
        medicaid_numbers=_numbers(d, "medicaid_numbers", where),
        npi_numbers=_numbers(d, "npi_numbers", where),
        certified_date=_str(d, "certified_date", where),
        rural=_bool(d, "rural", where),
        edit_date=_str(d, "edit_date", where),
        shipping_addresses=shipping,
        contract_pharmacies=pharmacies,
    )


def read_snapshot(path: Path) -> Snapshot:
    """Read a snapshot file. An unknown ``format_version`` is refused."""
    try:
        data = json.loads(path.read_bytes())
    except ValueError as error:
        raise SnapshotError(f"{path.name}: not valid JSON ({error})") from error
    top = _doc(data, path.name)
    if top.get("format") != FORMAT_NAME:
        raise SnapshotError(f"{path.name}: not an {FORMAT_NAME} file")
    version = top.get("format_version")
    if version != FORMAT_VERSION:
        raise SnapshotError(
            f"{path.name}: format_version {version!r} is not supported (this library reads "
            f"version {FORMAT_VERSION})"
        )
    taken = top.get("taken_on")
    sha = top.get("source_sha256")
    size = top.get("source_bytes")
    if not (isinstance(taken, str) and isinstance(sha, str) and isinstance(size, int)):
        raise SnapshotError(f"{path.name}: the header is incomplete")
    try:
        taken_on = date.fromisoformat(taken)
    except ValueError as error:
        raise SnapshotError(f"{path.name}: taken_on {taken!r} is not a date") from error
    items = _list(top, "entities", path.name)
    entities = tuple(_entity(item, n) for n, item in enumerate(items, start=1))
    if top.get("entity_count") != len(entities):
        raise SnapshotError(f"{path.name}: entity_count does not match the entities listed")
    header = SnapshotHeader(
        taken_on=taken_on, source_sha256=sha, source_bytes=size, entity_count=len(entities)
    )
    return Snapshot(header=header, entities=entities)
