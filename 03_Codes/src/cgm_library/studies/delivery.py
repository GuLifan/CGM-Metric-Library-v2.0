"""261112 human-readable delivery schema; identifiers and clinical anchors are explicit."""

from cgm_library.contracts.fields import CONDITION_COUNTS, EVENT_COUNTS, FULL_FEATURES
from cgm_library.events.engine import CONFIRMED_RULES
from cgm_library.io.pump_request import PUMP_PREFIX

REVISION = "261112"
DEFAULT_PREFIX = "DRQ261112_CML2.0_2204"
LAYOUT_VERSION = 2
PERIODS = ("night_00to06", "day_06to24")
SLIM_MAIN = (
    [
        "MEAN",
        "SD",
        "CV_pct",
        "GMI",
        "LBGI",
        "HBGI",
        "LAGE",
        "GRI",
        "global_min",
        "P5",
        "P25",
        "P50",
        "P75",
        "P95",
        "TIR_pct",
        "TAR_pct",
        "TAR1_pct",
        "TAR2_pct",
        "TBR_pct",
        "TBR1_pct",
        "TBR2_pct",
        "TITR_pct",
        "MODD_mmol_L",
        "ADRR",
        "fasting_cgm_0600_cv_pct",
        "MAGE_candidate_mmol_L",
    ]
    + [k for k in EVENT_COUNTS + CONDITION_COUNTS if k.endswith("_n")]
    + [
        "below_1p8_valid_raw_n",
        "below_1p8_valid_raw_min",
    ]
)
SLIM_PERIOD = [
    "MEAN",
    "SD",
    "CV_pct",
    "GRI",
    "global_min",
    "P5",
    "TIR_pct",
    "TAR_pct",
    "TAR1_pct",
    "TAR2_pct",
    "TBR_pct",
    "TBR1_pct",
    "TBR2_pct",
    "TITR_pct",
] + [f"{r.event_type}_n" for r in CONFIRMED_RULES]
SLIM_METRICS = SLIM_MAIN + [f"{p}__{k}" for p in PERIODS for k in SLIM_PERIOD]
WINDOW_NAMES = ("all_record", "inpatient", "pre72h", "pre24h", "pump_d1", "pump_d3")
SCALAR_FIELDS = (
    [
        "MEAN",
        "SD",
        "CV_pct",
        "GMI",
        "LBGI",
        "HBGI",
        "LAGE",
        "MODD_mmol_L",
        "ADRR",
        "ADRR_complete_days",
        "adrr_partial_sensitivity_delta",
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
        "TIR_pct",
        "TAR_pct",
        "TAR1_pct",
        "TAR2_pct",
        "TBR_pct",
        "TBR1_pct",
        "TBR2_pct",
        "TITR_pct",
        "time_7p8_10_pct",
        "fasting_cgm_0600_cv_pct",
        "MAGE_candidate_mmol_L",
    ]
    + EVENT_COUNTS
    + CONDITION_COUNTS
)
SPARSE_FEATURES = [
    "sparse_mean_cgm_d1",
    "sparse_delta_mean_cgm_d3_d1",
    "sparse_mean_pre72h",
    "sparse_min_pre72h",
    "sparse_cv_pre72h_pct",
]
SUMMARY_METRICS = [
    "window_start",
    "window_end",
    "sufficient_flag",
    "valid_minutes",
    "coverage_pct",
    "MEAN",
    "CV_pct",
    "TIR_pct",
    "TBR_pct",
    "TAR_pct",
    "GMI",
    "ADRR",
    "hypo_episode_lt3p9_n",
    "level2_period_lt3p0_n",
    "fasting_cgm_0600_cv_pct",
]
SHORT_WINDOWS = {"pre24h", "pump_d1", "pump_d3"}
SHORT_UNUSED = {
    "MODD_mmol_L",
    "ADRR_complete_days",
    "adrr_partial_sensitivity_delta",
    "fasting_cgm_0600_cv_pct",
}


LOW_EVENT_COUNTS = {f"{r.event_type}_n" for r in CONFIRMED_RULES if not r.high} | {
    k for k in CONDITION_COUNTS if k.endswith("_n")
}


def event_time_column(count_column):
    """Only typed hypoglycemia counts get an adjacent readable interval column."""
    if count_column.rsplit("__", 1)[-1] in LOW_EVENT_COUNTS:
        return count_column.removesuffix("_n") + "_times"
    return None


def with_time_columns(columns):
    return [part for column in columns for part in (column, event_time_column(column)) if part]


def mode_columns(*, include_times=True):
    columns = [*PUMP_PREFIX, "window_start", "window_end", *SLIM_METRICS]
    return with_time_columns(columns) if include_times else columns


def scalar_columns():
    return [
        *PUMP_PREFIX,
        *[
            f"{w}__{k}"
            for w in WINDOW_NAMES
            for k in SCALAR_FIELDS
            if not (w in SHORT_WINDOWS and k in SHORT_UNUSED)
        ],
        *[f"Full7__{k}" for k in FULL_FEATURES],
        *[f"Sparse5__{k}" for k in SPARSE_FEATURES],
    ]


AFTER_DAY_COLUMNS = [
    *PUMP_PREFIX,
    "post_discharge_day",
    "window_start",
    "window_end",
    "computation_status",
    "valid_minutes",
    "coverage_pct",
    "sufficient_flag",
    "metric_reason",
    *[k for k in SLIM_METRICS if k not in ("MODD_mmol_L", "fasting_cgm_0600_cv_pct")],
    "MODD_vs_previous_discharge_day_mmol_L",
    *[f"{p}__{k}" for p in PERIODS for k in ("coverage_pct", "sufficient_flag")],
]


def after_day_columns(*, include_times=True):
    return with_time_columns(AFTER_DAY_COLUMNS) if include_times else list(AFTER_DAY_COLUMNS)


QC_COLUMNS = [
    *PUMP_PREFIX,
    "window_name",
    "post_discharge_day",
    "window_start",
    "window_end",
    "computation_status",
    "period",
    "coverage_pct",
    "sufficient_flag",
    "metric_reason",
]
EVENT_COLUMNS = [
    *PUMP_PREFIX,
    "window_name",
    "post_discharge_day",
    "period",
    "window_start",
    "window_end",
    "event_type",
    "event_start",
    "event_end",
    "duration_min",
    "condition_minutes",
    "nadir_mmol_L",
    "nadir_time",
    "left_censored",
    "right_censored",
    "complete_event_flag",
    "censor_reason",
    "hypo_cond_thresholds",
]


def summary_columns():
    return [
        *PUMP_PREFIX,
        "computation_status",
        "error_code",
        "error_message",
        "warning_codes",
        "device_link_basis",
        "source_folder",
        "pump_end_basis",
        "结果说明",
        "窗口数",
        "合格窗口数",
        *[
            f"{w}_{k}"
            for w in WINDOW_NAMES
            for k in SUMMARY_METRICS
            if not (w in SHORT_WINDOWS and k == "fasting_cgm_0600_cv_pct")
        ],
    ]
