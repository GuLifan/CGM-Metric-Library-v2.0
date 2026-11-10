"""Approved DRQ research windows and result columns."""

from __future__ import annotations

import pandas as pd

from cgm_library.contracts.fields import CONDITION_COUNTS, EVENT_COUNTS, RANGE_PCT
from cgm_library.events.engine import CONFIRMED_RULES

PREFIX = "DRQ260723_2204"
GROUP_FILES = {
    "cgm_d1_3": "Mode0_Day1-3_group_Results.csv",
    "cgm_d1_5": "Mode0_Day1-5_group_Results.csv",
    "cgm_d1_7": "Mode0_Day1-7_group_Results.csv",
    "cgm_d1_14": "Mode0_Day1-14_group_Results.csv",
    "cgm_d6_11": "Mode1_Day6-11_group_Results.csv",
    "cgm_d7_14": "Mode1_Day7-14_group_Results.csv",
    "cgm_d9_14": "Mode1_Day9-14_group_Results.csv",
    "all_record": "Mode2_Dayall_group_Results.csv",
    "pre72h": "Mode3_Day3BeforeDischarge_group_Results.csv",
    "inpatient": "Mode4_DayDuringHospitalization_group_Results.csv",
    "post7d": "Mode5_Day7AfterDischarge_group_Results.csv",
    "post_record": "Mode6_DayallAfterDischarge_group_Results.csv",
    "pump_period": "Mode7_DayDuringInsulinPump_group_Results.csv",
}
CORE = [
    "MEAN",
    "SD",
    "CV_pct",
    "GMI",
    "LBGI",
    "HBGI",
    "LAGE",
    "GRI",
    "GRI_raw",
    "hypoglycemia_component",
    "hyperglycemia_component",
    "global_min",
    "P5",
    "P25",
    "P50",
    "P75",
    "P95",
    "TIR_minutes",
    "TAR_minutes",
    "TBR_minutes",
    "TITR_minutes",
    *RANGE_PCT,
]
MAIN = [
    "window_start",
    "window_end",
    *CORE,
    "MODD_mmol_L",
    "ADRR",
    "ADRR_complete_days",
    "adrr_partial_sensitivity_delta",
    "fasting_cgm_0600_cv_pct",
    "MAGE",
    "MAGE_candidate_mmol_L",
    *EVENT_COUNTS,
    *CONDITION_COUNTS,
    "below_1p8_valid_raw_n",
    "below_1p8_valid_raw_min",
]
PERIODS = ("night_00to06", "day_06to24")
EVENT_FIELDS = [rule.event_type for rule in CONFIRMED_RULES]
CONDITIONAL_FIELDS = [f"hypo_cond_lt3p{i}" for i in range(9)]
PERIOD_RESULT = CORE + [key for key in EVENT_COUNTS + CONDITION_COUNTS if key.endswith("_n")]


def result_columns(request_columns, daily=False):
    columns = [
        *request_columns,
        *MAIN,
        *[f"{p}__{key}" for p in PERIODS for key in PERIOD_RESULT],
        *[f"{key}_events_json" for key in EVENT_FIELDS + CONDITIONAL_FIELDS],
        *[f"{p}__{key}_events_json" for p in PERIODS for key in EVENT_FIELDS + CONDITIONAL_FIELDS],
        "night_00to06__nadirs_json",
    ]
    if daily:
        columns.append("MODD_vs_previous_cgm_day_mmol_L")
    if len(columns) != len(set(columns)):
        raise ValueError("Request columns collide with DRQ output columns")
    return columns


def research_windows(origin, record_start, record_end, admission, discharge, pump_start, pump_end):
    day = pd.Timedelta(days=1)
    windows = {
        **{f"cgm_d1_{n}": (origin, origin + n * day) for n in (3, 5, 7, 14)},
        **{
            f"cgm_d{a}_{b}": (origin + (a - 1) * day, origin + b * day)
            for a, b in ((6, 11), (7, 14), (9, 14))
        },
        "all_record": (record_start, record_end),
        "pre72h": (discharge - 3 * day, discharge),
        "inpatient": (admission, discharge),
        "post7d": (discharge, discharge + 7 * day),
        "post_record": (discharge, record_end),
        "pump_period": (pump_start, pump_end),
        **{f"cgm_day_{n}": (origin + (n - 1) * day, origin + n * day) for n in range(1, 15)},
    }
    return windows
