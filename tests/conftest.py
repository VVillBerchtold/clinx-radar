"""Made-up exports for the tests. Every entity, person and address here is invented."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

Record = dict[str, Any]
Writer = Callable[[object, str], Path]

# Values that must never reach a snapshot or a report.
SECRET_VALUES = (
    "Example Official Person",
    "Example Official Title",
    "555-0100",
    "Example Contact Person",
    "Example Contact Title",
    "555-0101",
    "555-0102",
    "Example free-text comment",
    "Example nested comment",
    "Example Nested Official",
    "Example Nested Contact",
    "555-0103",
    "555-0104",
    "9999",
)


def pharmacy(pharmacy_id: str, contract_id: str | None, **extra: str) -> Record:
    """A made-up contract pharmacy in the Excel column spelling."""
    record: Record = {
        "Pharmacy Name": f"Example Pharmacy {pharmacy_id}",
        "Pharmacy ID": pharmacy_id,
        "Contract Begin Date": "01/15/2024",
        "Pharmacy Address 1": "9 Example Street",
        "Pharmacy City": "Exampleton",
        "Pharmacy State": "RI",
        "Pharmacy Zip": "00001",
        "Pharmacy Phone": "555-0102",
    }
    if contract_id is not None:
        record["Contract ID"] = contract_id
    record.update(extra)
    return record


def entity(id_340b: str, name: str, **extra: Any) -> Record:
    """A made-up covered entity in the Excel column spelling, with personal fields."""
    record: Record = {
        "340B ID": id_340b,
        "CE ID": "1" + id_340b[-4:],
        "Entity Type": "CH",
        "Participating": "TRUE",
        "Participating Start Date": "2020-01-01T00:00:00",
        "Entity Name": name,
        "Street Address 1": "1 Example Street",
        "Street City": "Exampleton",
        "Street State": "RI",
        "Street Zip": "00001",
        "NPI": "0000000000",
        "Rural": "FALSE",
        "Edit Date": "2025-12-01",
        "Authorizing Official Name": "Example Official Person",
        "Authorizing Official Title": "Example Official Title",
        "Authorizing Official Phone": "555-0100",
        "Primary Contact Name": "Example Contact Person",
        "Primary Contact Title": "Example Contact Title",
        "Primary Contact Phone": "555-0101",
        "Entry Comments": "Example free-text comment",
        "Shipping Addresses": [],
        "Contract Pharmacies": [],
    }
    record.update(extra)
    return record


def base_day() -> list[Record]:
    """The first day: six entities."""
    return [
        entity(
            "CH99901",
            "Example Health Center",
            **{
                "Contract Pharmacies": [
                    pharmacy("P1", "C1"),
                    pharmacy("P2", "C2"),
                    pharmacy("P4", None),
                ],
                "Shipping Addresses": [
                    {
                        "340B ID Street Address (Yes/No)": "No",
                        "Shipping Organization": "Example Receiving",
                        "Shipping Address 1": "5 Example Street",
                        "Shipping City": "Exampleton",
                        "Shipping State": "RI",
                        "Shipping Zip": "00001",
                    }
                ],
            },
        ),
        entity("CH99902", "Example Clinic Two", **{"Street State": "ZZ"}),
        entity("CH99903", "Example Clinic Three"),
        entity(
            "CH99904",
            "Example Clinic Four",
            Participating="FALSE",
            **{"Termination Date": "2025-06-30", "Termination Reason": "Example reason"},
        ),
        entity("CH99905", "Example Clinic Five"),
        entity("CH99906", "Example Clinic Six"),
    ]


def later_day() -> list[Record]:
    """The second day: one of each kind of change, and one edit-date-only change."""
    records = copy.deepcopy(base_day())
    first, second, _third, fourth, fifth, sixth = records
    # Contract pharmacies: P1/C1 terminated, P2/C2 removed, P3/C3 added, P4 (no contract) kept.
    first["Contract Pharmacies"] = [
        pharmacy("P1", "C1", **{"Contract Termination Date": "02/01/2026"}),
        pharmacy("P3", "C3"),
        pharmacy("P4", None),
    ]
    # Terminated: a termination date appears.
    second["Participating"] = "FALSE"
    second["Termination Date"] = "2026-02-01"
    # Removed: CH99903 is gone (the third record is dropped below).
    # Reinstated: the termination date goes and participating becomes true.
    del fourth["Termination Date"]
    del fourth["Termination Reason"]
    fourth["Participating"] = "TRUE"
    # Field changes: a name and a street line.
    fifth["Entity Name"] = "Example Clinic Five Renamed"
    fifth["Street Address 1"] = "2 Example Street"
    # Edit date alone.
    sixth["Edit Date"] = "2026-02-01"
    added = entity("CH99907", "Example Clinic Seven")
    return [first, second, fourth, fifth, sixth, added]


@pytest.fixture
def write_json(tmp_path: Path) -> Writer:
    """Return a function that writes JSON to a file in the temp folder."""

    def write(data: object, name: str) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return write


@pytest.fixture
def day1(write_json: Writer) -> Path:
    return write_json(base_day(), "export-day1.json")


@pytest.fixture
def day2(write_json: Writer) -> Path:
    return write_json(later_day(), "export-day2.json")


def nested_address(line1: str, city: str, state: str, **extra: str) -> Record:
    """A made-up address object in the nested export shape."""
    record: Record = {
        "addressLine1": line1,
        "city": city,
        "state": state,
        "zip": "00001",
    }
    record.update(extra)
    return record


def nested_pharmacy(pharmacy_id: int, contract_id: int, **extra: Any) -> Record:
    """A made-up contract pharmacy in the nested export shape, with a phone number."""
    record: Record = {
        "contractId": contract_id,
        "pharmacyId": pharmacy_id,
        "name": f"Example Pharmacy {pharmacy_id}",
        "beginDate": "2024-01-15",
        "address": nested_address("9 Example Street", "Exampleton", "RI"),
        "phoneNumber": "555-0103",
        "phoneNumberExtension": "9999",
    }
    record.update(extra)
    return record


def nested_entity(id_340b: str, name: str, state: str = "RI", **extra: Any) -> Record:
    """A made-up covered entity in the nested export shape, with personal objects."""
    record: Record = {
        "ceId": int(id_340b[-4:]),
        "id340B": id_340b,
        "name": name,
        "subName": "Example Division",
        "entityType": "CH",
        "participating": "true",
        "participatingStartDate": "2020-01-01T00:00:00",
        "certifiedDecertifiedDate": "2020-01-01T00:00:00",
        "editDate": "2025-12-01T00:00:00",
        "grantNumber": "H00XX00000",
        "cmsCertificationNumber": "000000",
        "rural": False,
        "parentCeId": 1,
        "parentId340B": "CH00001",
        "comments": "Example nested comment",
        "nofoNumber": "X",
        "assistanceReceivedFromDate": "2020-01-01",
        "assistanceReceivedToDate": "2021-01-01",
        "streetAddress": nested_address("1 Example Street", "Exampleton", state, zip4="0002"),
        "billingAddress": nested_address(
            "2 Example Street", "Exampleton", state, organization="Example Billing"
        ),
        "shippingAddresses": [
            {
                **nested_address("5 Example Street", "Exampleton", state),
                "organization": "Example Receiving",
                "is340BStreetAddress": False,
            }
        ],
        "medicaidNumbers": [
            {"medicaidNumber": "M2", "state": "RI"},
            {"medicaidNumber": "M1", "state": "MA"},
        ],
        "npiNumbers": [
            {"npiNumber": "0000000002", "state": "RI"},
            {"npiNumber": "0000000001", "state": "RI"},
        ],
        "contractPharmacies": [nested_pharmacy(20, 2), nested_pharmacy(10, 1)],
        "authorizingOfficial": {"name": "Example Nested Official", "phone": "555-0104"},
        "primaryContact": {"name": "Example Nested Contact", "phone": "555-0104"},
    }
    record.update(extra)
    return record


def nested_day() -> dict[str, Any]:
    """A made-up export in the real nested shape: an object with a list of entities."""
    return {
        "coveredEntities": [
            nested_entity("CH99911", "Example Nested One"),
            nested_entity("CH99912", "Example Nested Two", state="ZZ"),
        ]
    }
