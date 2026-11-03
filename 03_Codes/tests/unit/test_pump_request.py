"""合成请求表验证：身份匹配、前六列和日期精度均不得静默变化。"""

import pytest

from cgm_library.io.pump_request import (
    RequestMatchError,
    augment_request,
    parse_local_datetime,
)

REQUEST_HEADERS = ["住院号", "出院日期", "入院日期", "设备文件名", "analysis_id", "附加列"]
PATIENT_HEADERS = [
    "住院号",
    "出院日期",
    "入院日期",
    "探头编号",
    "手机号",
    "设备文件名",
    "胰岛素泵开始时间",
    "胰岛素泵停止时间",
    "德谷开始时间",
    "甘精开立时间",
]


def request_row():
    return {
        "住院号": "0001",
        "出院日期": "2026-01-04 09:35",
        "入院日期": "2026-01-01 08:20",
        "设备文件名": "synthetic.csv",
        "analysis_id": "SYN0001",
        "附加列": "保留原文",
    }


def patient_row(**changes):
    row = {
        "住院号": "0001",
        "出院日期": "2026-01-04 10:00",
        "入院日期": "2026-01-01 08:00",
        "探头编号": "",
        "手机号": "",
        "设备文件名": "synthetic.csv",
        "胰岛素泵开始时间": "2026-01-01",
        "胰岛素泵停止时间": "",
        "德谷开始时间": "2026-01-03 09:00",
        "甘精开立时间": "2026-01-03 08:00",
    }
    row.update(changes)
    return row


def test_unique_match_preserves_columns_and_earlier_fallback():
    headers, rows, qc = augment_request(
        REQUEST_HEADERS, [request_row()], PATIENT_HEADERS, [patient_row()]
    )
    assert headers[:6] == [
        "住院号",
        "出院日期",
        "入院日期",
        "设备文件名",
        "胰岛素泵开始时间",
        "胰岛素泵停止时间",
    ]
    assert headers[6:] == ["analysis_id", "附加列"]
    assert rows[0]["住院号"] == "0001"
    assert rows[0]["附加列"] == "保留原文"
    assert rows[0]["胰岛素泵停止时间"] == "2026-01-03 08:00"
    assert qc[0]["pump_end_source"] == "甘精开立时间"
    assert qc[0]["pump_start_precision"] == "DATE_ONLY_NOON_ON_CALCULATION"
    assert parse_local_datetime(rows[0]["胰岛素泵开始时间"], date_only_hour=12).hour == 12


def test_direct_pump_end_wins_over_fallback():
    _, rows, qc = augment_request(
        REQUEST_HEADERS,
        [request_row()],
        PATIENT_HEADERS,
        [patient_row(胰岛素泵停止时间="2026-01-02 18:00")],
    )
    assert rows[0]["胰岛素泵停止时间"] == "2026-01-02 18:00"
    assert qc[0]["pump_end_source"] == "胰岛素泵停止时间"


def test_duplicate_stay_must_match_exact_time():
    rows = [patient_row(), patient_row(出院日期="2026-01-04 11:00")]
    with pytest.raises(RequestMatchError, match="禁止推断选行"):
        augment_request(REQUEST_HEADERS, [request_row()], PATIENT_HEADERS, rows)
    rows.append(patient_row(入院日期=request_row()["入院日期"], 出院日期=request_row()["出院日期"]))
    _, _, qc = augment_request(REQUEST_HEADERS, [request_row()], PATIENT_HEADERS, rows)
    assert qc[0]["match_mode"] == "UNIQUE_EXACT_STAY_TIME"


def test_unique_id_with_different_stay_day_is_rejected():
    with pytest.raises(RequestMatchError, match="自然日不一致"):
        augment_request(
            REQUEST_HEADERS,
            [request_row()],
            PATIENT_HEADERS,
            [patient_row(入院日期="2026-01-02 08:00")],
        )


def test_manual_physical_csv_row_is_checked_and_audited():
    unrelated = patient_row(住院号="0002")
    chosen = patient_row(胰岛素泵开始时间="2026-01-01", 胰岛素泵停止时间="2026-01-03 8:48")
    other_stay = patient_row(入院日期="2026-01-02")
    _, rows, qc = augment_request(
        REQUEST_HEADERS,
        [request_row()],
        PATIENT_HEADERS,
        [unrelated, chosen, other_stay],
        source_row_overrides={"0001": 3},
    )
    assert rows[0]["胰岛素泵停止时间"] == "2026-01-03 8:48"
    assert qc[0]["patient_source_csv_row"] == 3
    assert qc[0]["patient_source_candidates_n"] == 2
    assert qc[0]["match_mode"] == "MANUAL_SOURCE_ROW"
    with pytest.raises(RequestMatchError, match="住院号"):
        augment_request(
            REQUEST_HEADERS,
            [request_row()],
            PATIENT_HEADERS,
            [unrelated, chosen, other_stay],
            source_row_overrides={"0001": 2},
        )
    with pytest.raises(RequestMatchError, match="自然日"):
        augment_request(
            REQUEST_HEADERS,
            [request_row()],
            PATIENT_HEADERS,
            [unrelated, chosen, other_stay],
            source_row_overrides={"0001": 4},
        )
