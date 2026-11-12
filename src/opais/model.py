"""The records the library reads, stores and compares.

Every field is plain text, a bool or None. Dates stay as text; ``parse_date`` turns
the common forms into a ``datetime.date`` when you need one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

__all__ = [
    "Address",
    "ContractPharmacy",
    "CoveredEntity",
    "ShippingAddress",
    "StateNumber",
    "date_text",
    "in_state",
    "numbers_text",
    "parse_date",
    "pharmacy_key",
]

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


@dataclass(frozen=True, slots=True)
class Address:
    """A postal address. Every part may be missing."""

    line1: str | None = None
    line2: str | None = None
    line3: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    zip4: str | None = None


@dataclass(frozen=True, slots=True)
class StateNumber:
    """A Medicaid number or an NPI, with the state it is listed under."""

    number: str
    state: str | None = None


@dataclass(frozen=True, slots=True)
class ShippingAddress:
    """One shipping address listed under a covered entity."""

    is_street_address: bool | None = None
    organization: str | None = None
    address: Address = Address()


@dataclass(frozen=True, slots=True)
class ContractPharmacy:
    """One contract pharmacy arrangement listed under a covered entity."""

    contract_id: str | None = None
    pharmacy_id: str | None = None
    name: str | None = None
    begin_date: str | None = None
    termination_date: str | None = None
    address: Address = Address()


@dataclass(frozen=True, slots=True)
class CoveredEntity:
    """One 340B covered entity.

    The people named in the export (authorizing official, primary contact), pharmacy
    phone numbers and free-text comments are never read into this record.
    """

    id_340b: str
    ce_id: str | None = None
    parent_340b_id: str | None = None
    parent_ce_id: str | None = None
    entity_type: str | None = None
    participating: bool | None = None
    participating_start_date: str | None = None
    termination_date: str | None = None
    termination_reason: str | None = None
    name: str | None = None
    subdivision_name: str | None = None
    grant_number: str | None = None
    site_id: str | None = None
    medicare_provider_number: str | None = None
    street: Address = Address()
    billing_organization: str | None = None
    billing: Address = Address()
    medicaid_number: str | None = None
    npi: str | None = None
    medicaid_numbers: tuple[StateNumber, ...] = ()
    npi_numbers: tuple[StateNumber, ...] = ()
    certified_date: str | None = None
    rural: bool | None = None
    edit_date: str | None = None
    shipping_addresses: tuple[ShippingAddress, ...] = ()
    contract_pharmacies: tuple[ContractPharmacy, ...] = ()


def parse_date(text: str | None) -> date | None:
    """Read ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM:SS...`` or ``MM/DD/YYYY``.

    Return None for anything else, and for a date that does not exist. Nothing is guessed.
    """
    if text is None:
        return None
    value = text.strip()
    iso = _ISO_DATE.match(value)
    us = _US_DATE.match(value)
    try:
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3]))
        if us:
            return date(int(us[3]), int(us[1]), int(us[2]))
    except ValueError:
        return None
    return None


def date_text(text: str | None) -> str | None:
    """Return the ISO date when ``text`` parses, otherwise the text as given."""
    parsed = parse_date(text)
    return parsed.isoformat() if parsed else text


def in_state(entities: Iterable[CoveredEntity], state: str) -> tuple[CoveredEntity, ...]:
    """Keep the entities whose street address state matches ``state`` (ignoring case)."""
    wanted = state.strip().upper()
    return tuple(e for e in entities if (e.street.state or "").upper() == wanted)


def pharmacy_key(pharmacy: ContractPharmacy) -> tuple[str, str, str]:
    """Identify a contract pharmacy arrangement under one entity.

    The key is the pharmacy ID and the contract ID. When the contract ID is missing,
    the pharmacy name is used instead.
    """
    pharmacy_id = pharmacy.pharmacy_id or ""
    if pharmacy.contract_id is not None:
        return (pharmacy_id, "contract", pharmacy.contract_id)
    return (pharmacy_id, "name", pharmacy.name or "")


def numbers_text(single: str | None, items: Iterable[StateNumber]) -> str | None:
    """Join a single number and a list of numbers into one text, in a fixed order.

    Each listed number reads ``STATE number``, or ``number`` when it has no state.
    Return None when there is nothing to join.
    """
    parts = [single] if single else []
    parts += [f"{n.state} {n.number}" if n.state else n.number for n in items]
    return "; ".join(sorted(parts)) or None
