import csv

import pandas as pd
from openpyxl import load_workbook

from cgm_library.io.tables import write_csv, write_workbook


def test_export_rounds_half_ties_after_calculation_and_preserves_identifiers(tmp_path):
    frame = pd.DataFrame(
        {"id": ["0001", "0002", "=literal", "0004"], "value": [1.23445, -1.23445, -0.00001, None]}
    )
    write_csv(frame, tmp_path / "test.csv")
    with (tmp_path / "test.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.reader(handle))[1:] == [
            ["0001", "1.2345"],
            ["0002", "-1.2345"],
            ["=literal", "0.0000"],
            ["0004", ""],
        ]
    path = tmp_path / "test.xlsx"
    write_workbook(path, [("Results", frame)])
    book = load_workbook(path)
    sheet = book.active
    assert all(c.font.name == "Times New Roman" for row in sheet for c in row)
    assert sheet["A2"].value == "0001" and sheet["A4"].data_type == "s"
    assert sheet["B2"].value == 1.2345 and sheet["B3"].value == -1.2345
    assert sheet["B2"].number_format == "0.0000" and sheet["B5"].value is None
    assert frame.value.iloc[0] == 1.23445
    book.close()
