import csv
import io
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .verification import SCENARIOS

MAX_UPLOAD = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_XLSX_COLUMNS = 256
EXPORT_COLUMNS = (
    "destination", "scenario", "status", "attempts", "fixture", "engine",
    "transcript", "label", "reason", "review_note", "reviewed_at",
)
FORMATS = {
    "csv": "text/csv",
    "txt": "text/plain",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class ImportErrorDetail(ValueError):
    pass


def destination_text(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Enter the destination as plain text.")
    raw = str(value).strip()
    if raw.startswith("'+"):
        raw = raw[1:]
    if not re.fullmatch(r"\+?[0-9 ()-]+", raw):
        raise ValueError("The destination contains unsupported characters.")
    number = re.sub(r"[ ()-]", "", raw)
    if not re.fullmatch(r"\+?[0-9]{3,15}", number):
        raise ValueError("The destination must contain 3–15 digits.")
    return number


def workbook_rows(data):
    with ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 200 or sum(entry.file_size for entry in entries) > 25 * 1024 * 1024:
            raise ImportErrorDetail("The expanded workbook exceeds the import limit.")
    workbook = load_workbook(io.BytesIO(data), read_only=True, keep_links=False)
    try:
        if not workbook.worksheets:
            raise ImportErrorDetail("The workbook has no worksheet.")
        sheet = workbook.worksheets[0]
        sheet.reset_dimensions()
        yield from sheet.iter_rows(max_col=MAX_XLSX_COLUMNS, values_only=True)
    finally:
        workbook.close()


def read_rows(data, suffix):
    if suffix == ".xlsx":
        yield from workbook_rows(data)
        return
    if suffix not in {".csv", ".txt"}:
        raise ImportErrorDetail("Choose a CSV, TXT or XLSX file.")
    text = data.decode("utf-8-sig")
    if suffix == ".csv":
        yield from csv.reader(io.StringIO(text, newline=""), strict=True)
    else:
        yield from csv.reader(io.StringIO(text, newline=""), delimiter="\t", strict=True)


def parse_import(filename, data):
    results = []
    destination_index = 0
    scenario_index = 1
    first = True
    try:
        for row_number, row in enumerate(read_rows(data, Path(filename).suffix.lower()), 1):
            if row_number > MAX_ROWS + 1:
                raise ImportErrorDetail(f"Import at most {MAX_ROWS:,} rows plus a header.")
            if all(value is None or str(value).strip() == "" for value in row):
                continue
            if first:
                first = False
                headings = [str(value).strip().casefold() for value in row]
                for heading in ("destination", "phone", "number"):
                    if heading in headings:
                        destination_index = headings.index(heading)
                        scenario_index = headings.index("scenario") if "scenario" in headings else None
                        break
                else:
                    heading = None
                if heading is not None:
                    continue
            destination = row[destination_index] if destination_index < len(row) else None
            scenario = (
                row[scenario_index] if scenario_index is not None and scenario_index < len(row) else None
            )
            try:
                number = destination_text(destination)
                scenario = str(scenario or "").strip().casefold() or SCENARIOS[0]
                if scenario not in SCENARIOS:
                    raise ValueError(f"Choose a scenario from {', '.join(SCENARIOS)}.")
            except ValueError as error:
                raise ImportErrorDetail(f"Row {row_number}: {error}") from error
            results.append((number, scenario))
    except ImportErrorDetail:
        raise
    except (BadZipFile, InvalidFileException, DefusedXmlException, UnicodeError,
            csv.Error, ValueError, KeyError, OSError, SyntaxError, IndexError, RuntimeError) as error:
        raise ImportErrorDetail("The file could not be read. Check its format and encoding.") from error
    if not results:
        raise ImportErrorDetail("The file has no destinations.")
    if len(results) > MAX_ROWS:
        raise ImportErrorDetail(f"Import at most {MAX_ROWS:,} destinations.")
    return results


def spreadsheet_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def export_rows(items, fmt):
    if fmt == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Verification results"
        sheet.freeze_panes = "A2"
        sheet.append(EXPORT_COLUMNS)
        for row_number, item in enumerate(items, start=2):
            values = [item[column] for column in EXPORT_COLUMNS]
            sheet.append(values)
            for column_number, value in enumerate(values, start=1):
                if isinstance(value, str):
                    sheet.cell(row=row_number, column=column_number).data_type = "s"
        sheet.auto_filter.ref = sheet.dimensions
        for column, width in {"A": 22, "B": 20, "C": 12, "F": 22, "G": 62, "I": 36, "J": 36}.items():
            sheet.column_dimensions[column].width = width
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="," if fmt == "csv" else "\t")
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows([spreadsheet_text(item[column]) for column in EXPORT_COLUMNS] for item in items)
    return output.getvalue().encode("utf-8-sig")
