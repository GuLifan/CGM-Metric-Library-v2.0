"""Presentation rules shared by CSV and Excel exports."""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import lru_cache
from numbers import Integral, Real

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

FONT = "Times New Roman"
PLACES = Decimal("0.0001")


@lru_cache(maxsize=16384)
def four_places(value):
    """Round the decimal spelling of a finite float, including half ties away from zero."""
    number = Decimal(str(value))
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, number.adjusted() + 6)
        rounded = number.quantize(PLACES, rounding=ROUND_HALF_UP)
    return format(rounded if rounded else abs(rounded), "f")


def write_csv(table, path):
    # Mixed object columns can contain floats alongside dates or raw source text.
    table = table.copy(deep=False)
    for name in table.select_dtypes(include="object"):
        table[name] = table[name].map(
            lambda v: four_places(v) if isinstance(v, (float, np.floating)) and pd.notna(v) else v
        )
    table.to_csv(path, index=False, encoding="utf-8-sig", float_format=four_places)


def write_workbook(path, sheets):
    """Write (sheet title, DataFrame) pairs, retaining identifier types and numeric cells."""
    book = Workbook(write_only=True)
    body = Font(name=FONT, size=11)
    heading = Font(name=FONT, size=11, bold=True, color="FFFFFF")
    wrapped = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    book._fonts[0] = body
    for title, table in sheets:
        sheet = book.create_sheet(title)
        sheet.freeze_panes = "C2"
        for col, name in enumerate(table, 1):
            sheet.column_dimensions[get_column_letter(col)].width = min(56, max(15, len(name) + 3))
        headers = []
        for name in table:
            cell = WriteOnlyCell(sheet, value=name)
            cell.font = heading
            cell.fill = PatternFill("solid", fgColor="185B61")
            headers.append(cell)
        sheet.append(headers)
        time_indices = {i for i, name in enumerate(table) if name.endswith("_times")}
        for row_number, record in enumerate(table.itertuples(index=False, name=None), 2):
            cells = []
            lines = 1
            for index, value in enumerate(record):
                cell = WriteOnlyCell(sheet)
                cell.font = body
                if time_indices:
                    cell.alignment = top
                if index in time_indices:
                    cell.alignment = wrapped
                    if isinstance(value, str) and value:
                        lines = max(lines, value.count("; ") + 1)
                if pd.notna(value):
                    if isinstance(value, (bool, np.bool_)):
                        cell.value = bool(value)
                    elif isinstance(value, Integral):
                        cell.value = int(value)
                    elif isinstance(value, Real):
                        cell.value = float(four_places(value))
                        cell.number_format = "0.0000"
                    else:
                        cell.value = str(value)
                        cell.data_type = "s"
                cells.append(cell)
            if lines > 1:
                sheet.row_dimensions[row_number].height = min(200, 16 * lines)
            sheet.append(cells)
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(table.columns))}{len(table) + 1}"
    temp = path.with_suffix(".xlsx.tmp")
    book.save(temp)
    temp.replace(path)
