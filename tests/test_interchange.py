import csv
import io

import pytest
from openpyxl import Workbook, load_workbook

from autodialer.interchange import EXPORT_COLUMNS, ImportErrorDetail, export_rows, parse_import


def workbook_bytes(*rows):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    contents = io.BytesIO()
    book.save(contents)
    return contents.getvalue()


@pytest.mark.parametrize("name,data", [
    ("records.csv", b"scenario,phone\r\naction_required,+1 (202) 555-0101\r\n"),
    ("records.txt", b"+1 (202) 555-0101\taction_required\n"),
    ("records.xlsx", workbook_bytes(("phone", "scenario"), ("+1 (202) 555-0101", "action_required"))),
])
def test_import_formats(name, data):
    assert parse_import(name, data) == [("+12025550101", "action_required")]


def test_txt_plain_preserves_leading_zeroes():
    assert parse_import("input.TXT", b"0012345\n") == [("0012345", "confirmed")]


@pytest.mark.parametrize("name,data,message", [
    ("records.csv", b"destination\n+12025550101\nnot-a-number", "Row 3"),
    ("records.txt", b"+12025550101\tunknown", "Choose a scenario"),
    ("records.txt", b"", "no destinations"),
    ("records.xlsx", b"bad archive", "could not be read"),
    ("records.xlsx", workbook_bytes(("destination",), ("=1+2",)), "Row 2"),
    ("records.pdf", b"hello", "Choose a CSV"),
])
def test_invalid_inputs_are_explained(name, data, message):
    with pytest.raises(ImportErrorDetail, match=message):
        parse_import(name, data)


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "txt"])
def test_export_escapes_formulas_and_round_trips_destinations(fmt):
    row = dict.fromkeys(EXPORT_COLUMNS)
    row.update(destination="+12025550101", scenario="confirmed", review_note="=1+2")
    data = export_rows([row], fmt)
    assert parse_import(f"results.{fmt}", data) == [("+12025550101", "confirmed")]
    if fmt == "xlsx":
        book = load_workbook(io.BytesIO(data))
        assert book.active["J2"].value == "=1+2"
        assert book.active["J2"].data_type == "s"
    else:
        records = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), delimiter="," if fmt == "csv" else "\t")
        assert next(records)["review_note"] == "'=1+2"
