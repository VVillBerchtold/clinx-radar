"""Read one HRSA OPAIS "Covered Entity Daily Export" (JSON) into typed records.

The tables below list every spelling the reader accepts: the nested camelCase structure
of the real export (``streetAddress`` objects, ``medicaidNumbers`` lists and so on) and the
older flat column spellings. Keys are matched after folding: lower case,
with every character that is not a letter or a digit removed. So ``340B ID``,
``340b_id`` and ``340bId`` are the same key.

Run ``opais inspect`` on an export. It lists every key the tables did not recognise,
so a difference shows at once.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from opais.model import (
    Address,
    ContractPharmacy,
    CoveredEntity,
    ShippingAddress,
    StateNumber,
    pharmacy_key,
)

__all__ = [
    "DROPPED_PREFIXES",
    "ENTITY_KEYS",
    "ExportError",
    "ExportResult",
    "ReadReport",
    "fold",
    "parse_export",
    "read_export",
]


class ExportError(ValueError):
    """The export file is not in a shape the reader can use."""


def fold(key: str) -> str:
    """Lower-case a key and remove every character that is not a letter or a digit."""
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _keys(*spellings: str) -> frozenset[str]:
    return frozenset(fold(s) for s in spellings)


def _address_keys(prefix: str, *bare_prefixes: str) -> dict[str, frozenset[str]]:
    """Return the accepted spellings of the seven address parts, under one or more prefixes."""
    prefixes = (prefix, *bare_prefixes)
    parts = {
        "line1": ("Address 1", "Address Line 1"),
        "line2": ("Address 2", "Address Line 2"),
        "line3": ("Address 3", "Address Line 3"),
        "city": ("City",),
        "state": ("State",),
        "zip": ("Zip", "Zip Code", "Postal Code"),
        "zip4": ("Zip4", "Zip 4", "Zip Plus 4"),
    }
    return {
        name: _keys(*(f"{p} {s}" for p in prefixes for s in spellings))
        for name, spellings in parts.items()
    }


def _prefixed(prefix: str, table: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    return {f"{prefix}_{name}": keys for name, keys in table.items()}


# ---------------------------------------------------------------------------
# THE KEY TABLES. This is the one place that says which JSON key means what.
#
# The spellings below cover the key names of the real JSON export (nested objects and
# lists) and the column names of the Excel version of the same HRSA report. A key the
# tables do not know is listed by `opais inspect` as "unmapped"; add its spelling to
# the right set here. Spellings are folded, so case, spaces, dashes and underscores
# never need listing twice.
# ---------------------------------------------------------------------------

#: Fields of a covered entity (the top-level record).
ENTITY_KEYS: dict[str, frozenset[str]] = {
    "id_340b": _keys("340B ID", "ID 340B", "340B Identifier", "Entity 340B ID"),
    "ce_id": _keys("CE ID", "Covered Entity ID"),
    "parent_340b_id": _keys("Parent 340B ID", "Parent ID 340B"),
    "parent_ce_id": _keys("Parent CE ID"),
    "entity_type": _keys("Entity Type", "Type"),
    "participating": _keys("Participating", "Is Participating"),
    "participating_start_date": _keys("Participating Start Date", "Start Date"),
    "termination_date": _keys("Termination Date"),
    "termination_reason": _keys("Termination Reason"),
    "name": _keys("Entity Name", "Name", "Covered Entity Name"),
    "subdivision_name": _keys(
        "Entity Sub-Division Name", "Entity Subdivision Name", "Sub-Division", "Sub Name"
    ),
    "grant_number": _keys("Grant Number"),
    "site_id": _keys("Site ID"),
    # HRSA's own column heading is spelled "Provide", not "Provider".
    "medicare_provider_number": _keys(
        "Medicare Provide Number", "Medicare Provider Number", "CMS Certification Number"
    ),
    **_prefixed("street", _address_keys("Street", "")),
    "billing_organization": _keys("Billing Organization"),
    **_prefixed("billing", _address_keys("Billing")),
    "medicaid_number": _keys("Medicaid Number"),
    "npi": _keys("NPI"),
    "certified_date": _keys("Certified/Decertified Date", "Certified Date"),
    "rural": _keys("Rural", "Is Rural"),
    "edit_date": _keys("Edit Date"),
}

#: Fields of one shipping address (the address parts may be bare, as in the real export).
SHIPPING_KEYS: dict[str, frozenset[str]] = {
    "is_street_address": _keys(
        "340B ID Street Address (Yes/No)",
        "340B ID Street Address",
        "Street Address Flag",
        "Is 340B Street Address",
    ),
    "organization": _keys("Shipping Organization", "Organization"),
    **_prefixed("address", _address_keys("Shipping", "")),
}

#: The bare address parts of a nested address object (``streetAddress`` and the like).
ADDRESS_OBJECT_KEYS: dict[str, frozenset[str]] = _prefixed("address", _address_keys(""))

#: The nested billing address object has one more part.
BILLING_OBJECT_KEYS: dict[str, frozenset[str]] = {
    **ADDRESS_OBJECT_KEYS,
    "organization": _keys("Organization", "Billing Organization"),
}

#: One item of a Medicaid number list or an NPI list.
MEDICAID_ITEM_KEYS: dict[str, frozenset[str]] = {
    "number": _keys("Medicaid Number", "Number"),
    "state": _keys("State"),
}
NPI_ITEM_KEYS: dict[str, frozenset[str]] = {
    "number": _keys("NPI Number", "NPI", "Number"),
    "state": _keys("State"),
}

#: Fields of one contract pharmacy arrangement.
PHARMACY_KEYS: dict[str, frozenset[str]] = {
    "name": _keys("Pharmacy Name", "Name"),
    "contract_id": _keys("Contract ID"),
    "pharmacy_id": _keys("Pharmacy ID"),
    "begin_date": _keys("Contract Begin Date", "Begin Date"),
    "termination_date": _keys("Contract Termination Date", "Termination Date"),
    **_prefixed("address", _address_keys("Pharmacy")),
}

#: Keys of the nested lists inside an entity record.
SHIPPING_LIST_KEYS = _keys(
    "Shipping Addresses", "Shipping Address", "Shipping Address List", "Shipping"
)
PHARMACY_LIST_KEYS = _keys(
    "Contract Pharmacies",
    "Contract Pharmacy",
    "Contract Pharmacy List",
    "Pharmacies",
)

STREET_OBJECT_KEYS = _keys("Street Address", "Street Address Object")
BILLING_OBJECT = _keys("Billing Address", "Billing Address Object")
PHARMACY_ADDRESS_OBJECT = _keys("Address", "Pharmacy Address")
MEDICAID_LIST_KEYS = _keys("Medicaid Numbers", "Medicaid Number List")
NPI_LIST_KEYS = _keys("NPI Numbers", "NPI Number List")

#: Key prefixes (folded) that are DROPPED at read time and never stored: the people named
#: in the export, pharmacy phone numbers (business numbers we do not need) and the free
#: text comments. Only the key is counted in the report. The value is never kept.
DROPPED_PREFIXES: tuple[str, ...] = (
    "authorizingofficial",
    "primarycontact",
    "pharmacyphone",
    "phone",
    "entrycomment",
    "comments",
)

#: Known keys that carry no field we keep. Listed so they do not show as unmapped.
IGNORED_KEYS = _keys("NOFO Number", "Assistance Received From Date", "Assistance Received To Date")

_TRUE = frozenset({"true", "yes", "y", "1"})
_FALSE = frozenset({"false", "no", "n", "0"})


def _index(table: dict[str, frozenset[str]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for name, spellings in table.items():
        for spelling in spellings:
            if index.setdefault(spelling, name) != name:
                raise AssertionError(f"key spelling {spelling!r} is in the table twice")
    return index


_ENTITY_INDEX = _index(ENTITY_KEYS)
_SHIPPING_INDEX = _index(SHIPPING_KEYS)
_PHARMACY_INDEX = _index(PHARMACY_KEYS)
_ADDRESS_INDEX = _index(ADDRESS_OBJECT_KEYS)
_BILLING_INDEX = _index(BILLING_OBJECT_KEYS)
_MEDICAID_INDEX = _index(MEDICAID_ITEM_KEYS)
_NPI_INDEX = _index(NPI_ITEM_KEYS)


@dataclass(frozen=True, slots=True)
class ReadReport:
    """What the reader saw, so a person can check the key table against a real file.

    The report holds key names and counts only, never a value.
    """

    record_count: int = 0
    shipping_address_count: int = 0
    contract_pharmacy_count: int = 0
    #: ``"entity.name"`` style field names, with how many times a key for each was seen.
    mapped: dict[str, int] = field(default_factory=dict)
    #: ``"entity: Some Key"`` for each key the tables do not know, with counts.
    unmapped: dict[str, int] = field(default_factory=dict)
    #: Keys of dropped personal or free-text fields that were present, with counts.
    dropped: dict[str, int] = field(default_factory=dict)
    #: Known keys that carry nothing we keep, with counts.
    ignored: dict[str, int] = field(default_factory=dict)
    #: Yes/no fields whose value was not recognised (became blank), by field name. Never the value.
    unrecognised: dict[str, int] = field(default_factory=dict)
    #: Contract pharmacies dropped because an earlier one under the same entity has the same key.
    duplicate_pharmacies: int = 0


@dataclass(frozen=True, slots=True)
class ExportResult:
    """The entities read from an export, the report, and the file's hash and size."""

    entities: tuple[CoveredEntity, ...]
    report: ReadReport
    sha256: str = ""
    size_bytes: int = 0


@dataclass(slots=True)
class _Tally:
    mapped: Counter[str] = field(default_factory=Counter)
    unmapped: Counter[str] = field(default_factory=Counter)
    dropped: Counter[str] = field(default_factory=Counter)
    ignored: Counter[str] = field(default_factory=Counter)
    unrecognised: Counter[str] = field(default_factory=Counter)
    duplicates: int = 0
    shipping: int = 0
    pharmacies: int = 0


def _text(value: object) -> str | None:
    """Turn a JSON scalar into stripped text; empty or non-scalar becomes None."""
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or None


def _flag(text: str | None, name: str, tally: _Tally) -> bool | None:
    """Read a yes/no value. One that is not recognised is counted by field name."""
    if text is None:
        return None
    lowered = text.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    tally.unrecognised[name] += 1
    return None


def _read_scope(
    raw: dict[str, object],
    index: dict[str, str],
    scope: str,
    tally: _Tally,
    nested: frozenset[str] = frozenset(),
) -> dict[str, str | None]:
    """Map one record's keys to field names, counting everything that is not mapped."""
    fields: dict[str, str | None] = {}
    for key, value in raw.items():
        folded = fold(key)
        name = index.get(folded)
        if name is not None:
            tally.mapped[f"{scope}.{name}"] += 1
            if fields.get(name) is None:
                fields[name] = _text(value)
        elif folded.startswith(DROPPED_PREFIXES):
            tally.dropped[f"{scope}: {key}"] += 1
        elif folded in IGNORED_KEYS:
            tally.ignored[f"{scope}: {key}"] += 1
        elif folded not in nested:
            tally.unmapped[f"{scope}: {key}"] += 1
    return fields


def _address(fields: dict[str, str | None], prefix: str) -> Address:
    return Address(
        line1=fields.get(f"{prefix}_line1"),
        line2=fields.get(f"{prefix}_line2"),
        line3=fields.get(f"{prefix}_line3"),
        city=fields.get(f"{prefix}_city"),
        state=fields.get(f"{prefix}_state"),
        zip=fields.get(f"{prefix}_zip"),
        zip4=fields.get(f"{prefix}_zip4"),
    )


def _object(raw: dict[str, object], names: frozenset[str], tally: _Tally, scope: str) -> object:
    """Find a nested object by folded key. A value that is not an object is counted as unmapped."""
    for key, value in raw.items():
        if fold(key) not in names or value is None:
            continue
        if isinstance(value, dict):
            return value
        tally.unmapped[f"{scope}: {key}"] += 1
    return None


def _address_object(
    raw: dict[str, object],
    names: frozenset[str],
    scope: str,
    tally: _Tally,
    index: dict[str, str] | None = None,
) -> Address:
    """Read a nested address object, or return an empty address when there is none."""
    found = _object(raw, names, tally, scope)
    if not isinstance(found, dict):
        return Address()
    return _address(_read_scope(found, index or _ADDRESS_INDEX, scope, tally), "address")


def _numbers(
    raw: dict[str, object],
    names: frozenset[str],
    index: dict[str, str],
    scope: str,
    tally: _Tally,
) -> tuple[StateNumber, ...]:
    """Read a list of numbers with their states, without repeats, in a fixed order."""
    found: set[StateNumber] = set()
    for item in _items(raw, names, scope):
        f = _read_scope(item, index, scope, tally)
        number = f.get("number")
        if number is not None:
            found.add(StateNumber(number=number, state=f.get("state")))
    return tuple(sorted(found, key=lambda n: (n.state or "", n.number)))


def _items(raw: dict[str, object], names: frozenset[str], where: str) -> list[dict[str, object]]:
    """Find a nested list by folded key. A single object counts as a list of one."""
    found: list[dict[str, object]] = []
    for key, value in raw.items():
        if fold(key) not in names or value is None:
            continue
        entries = value if isinstance(value, list) else [value]
        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise ExportError(f"{where}: item {position} of {key!r} is not an object")
            found.append(entry)
    return found


def _shipping(raw: dict[str, object], where: str, tally: _Tally) -> tuple[ShippingAddress, ...]:
    out = []
    for item in _items(raw, SHIPPING_LIST_KEYS, where):
        f = _read_scope(item, _SHIPPING_INDEX, "shipping", tally)
        tally.shipping += 1
        out.append(
            ShippingAddress(
                is_street_address=_flag(
                    f.get("is_street_address"), "shipping.is_street_address", tally
                ),
                organization=f.get("organization"),
                address=_address(f, "address"),
            )
        )
    return tuple(out)


def _pharmacies(raw: dict[str, object], where: str, tally: _Tally) -> tuple[ContractPharmacy, ...]:
    out: dict[tuple[str, str, str], ContractPharmacy] = {}
    for item in _items(raw, PHARMACY_LIST_KEYS, where):
        f = _read_scope(item, _PHARMACY_INDEX, "pharmacy", tally, PHARMACY_ADDRESS_OBJECT)
        flat_address = _address(f, "address")
        nested_address = _address_object(item, PHARMACY_ADDRESS_OBJECT, "pharmacy.address", tally)
        pharmacy = ContractPharmacy(
            contract_id=f.get("contract_id"),
            pharmacy_id=f.get("pharmacy_id"),
            name=f.get("name"),
            begin_date=f.get("begin_date"),
            termination_date=f.get("termination_date"),
            address=nested_address if nested_address != Address() else flat_address,
        )
        key = pharmacy_key(pharmacy)
        if key in out:
            tally.duplicates += 1  # keep the first
            continue
        out[key] = pharmacy
        tally.pharmacies += 1
    return tuple(out.values())


def _entity(raw: dict[str, object], position: int, tally: _Tally) -> CoveredEntity:
    where = f"record {position}"
    nested = (
        SHIPPING_LIST_KEYS
        | PHARMACY_LIST_KEYS
        | STREET_OBJECT_KEYS
        | BILLING_OBJECT
        | MEDICAID_LIST_KEYS
        | NPI_LIST_KEYS
    )
    f = _read_scope(raw, _ENTITY_INDEX, "entity", tally, nested)
    id_340b = f.get("id_340b")
    if id_340b is None:
        raise ExportError(f"{where}: the record has no 340B ID")
    street = _address_object(raw, STREET_OBJECT_KEYS, "street", tally)
    billing_object = _object(raw, BILLING_OBJECT, tally, "billing")
    billing_fields: dict[str, str | None] = {}
    if isinstance(billing_object, dict):
        billing_fields = _read_scope(billing_object, _BILLING_INDEX, "billing", tally)
    nested_billing = _address(billing_fields, "address")
    return CoveredEntity(
        id_340b=id_340b,
        ce_id=f.get("ce_id"),
        parent_340b_id=f.get("parent_340b_id"),
        parent_ce_id=f.get("parent_ce_id"),
        entity_type=f.get("entity_type"),
        participating=_flag(f.get("participating"), "entity.participating", tally),
        participating_start_date=f.get("participating_start_date"),
        termination_date=f.get("termination_date"),
        termination_reason=f.get("termination_reason"),
        name=f.get("name"),
        subdivision_name=f.get("subdivision_name"),
        grant_number=f.get("grant_number"),
        site_id=f.get("site_id"),
        medicare_provider_number=f.get("medicare_provider_number"),
        street=street if street != Address() else _address(f, "street"),
        billing_organization=f.get("billing_organization") or billing_fields.get("organization"),
        billing=nested_billing if nested_billing != Address() else _address(f, "billing"),
        medicaid_number=f.get("medicaid_number"),
        npi=f.get("npi"),
        medicaid_numbers=_numbers(raw, MEDICAID_LIST_KEYS, _MEDICAID_INDEX, "medicaid", tally),
        npi_numbers=_numbers(raw, NPI_LIST_KEYS, _NPI_INDEX, "npi", tally),
        certified_date=f.get("certified_date"),
        rural=_flag(f.get("rural"), "entity.rural", tally),
        edit_date=f.get("edit_date"),
        shipping_addresses=_shipping(raw, where, tally),
        contract_pharmacies=_pharmacies(raw, where, tally),
    )


def _records(data: object) -> list[object]:
    """Find the list of records: the top level itself, or the one list inside an object."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        lists = [key for key, value in data.items() if isinstance(value, list)]
        if len(lists) == 1:
            found = data[lists[0]]
            if isinstance(found, list):
                return found
        if not lists:
            raise ExportError("the top level is an object with no list of records in it")
        raise ExportError(
            "the top level is an object with several lists, and the reader cannot tell "
            f"which holds the records: {', '.join(sorted(lists))}"
        )
    raise ExportError("the top level must be a list of records or an object holding one list")


def parse_export(data: object) -> ExportResult:
    """Read already-parsed JSON into entities and a report of the keys seen."""
    tally = _Tally()
    entities: list[CoveredEntity] = []
    seen: dict[str, int] = {}
    for position, raw in enumerate(_records(data), start=1):
        if not isinstance(raw, dict):
            raise ExportError(f"record {position}: the record is not an object")
        entity = _entity(raw, position, tally)
        if entity.id_340b in seen:
            raise ExportError(
                f"record {position}: 340B ID {entity.id_340b} already appears in "
                f"record {seen[entity.id_340b]}"
            )
        seen[entity.id_340b] = position
        entities.append(entity)
    report = ReadReport(
        record_count=len(entities),
        shipping_address_count=tally.shipping,
        contract_pharmacy_count=tally.pharmacies,
        mapped=dict(sorted(tally.mapped.items())),
        unmapped=dict(sorted(tally.unmapped.items())),
        dropped=dict(sorted(tally.dropped.items())),
        ignored=dict(sorted(tally.ignored.items())),
        unrecognised=dict(sorted(tally.unrecognised.items())),
        duplicate_pharmacies=tally.duplicates,
    )
    return ExportResult(entities=tuple(entities), report=report)


def read_export(path: Path) -> ExportResult:
    """Read an export file. The result carries the file's SHA-256 and size in bytes."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as error:  # JSON errors and bad UTF-8 are both ValueError
        raise ExportError(f"{path.name}: not valid JSON ({error})") from error
    parsed = parse_export(data)
    return ExportResult(
        entities=parsed.entities,
        report=parsed.report,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
