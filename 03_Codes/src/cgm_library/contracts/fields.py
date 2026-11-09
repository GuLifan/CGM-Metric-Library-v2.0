"""批次 CSV 的固定列，按资产粒度声明；用户附加列仅扩展要求复制请求的资产。"""

from __future__ import annotations

from dataclasses import dataclass

from cgm_library.contracts.schema import CalculationError
from cgm_library.events.engine import CONFIRMED_RULES

SCHEMA_VERSION = "2.0-review.1"
COVERAGE = "window_start window_end expected_points valid_points coverage_pct missing_points max_gap_min valid_minutes window_minutes sufficient_flag"
RAW_QC = "raw_points duplicate_count duplicate_conflict_count invalid_value_count below_1p8_valid_count zero_count negative_count unparseable_time_count date_only_imputed_count device_invalid_count"
RANGE_PCT = [
    f"{k}_pct" for k in ("TIR", "TAR", "TAR1", "TAR2", "TBR", "TBR1", "TBR2", "TITR", "time_7p8_10")
]
EVENT_COUNTS = [f"{r.event_type}_{suffix}" for r in CONFIRMED_RULES for suffix in ("n", "any")]
CONDITION_COUNTS = [f"hypo_cond_lt3p{i}_{suffix}" for i in range(9) for suffix in ("n", "any")]
WINDOW = (
    "window_name "
    + COVERAGE
    + " metric_reason MEAN SD CV_pct cv_prop GMI LBGI HBGI LAGE GRI GRI_raw"
    " hypoglycemia_component hyperglycemia_component global_min min_value_qc_flag risk_transform_domain_flag risk_domain_invalid_n"
    " P5 P25 P50 P75 P95 TIR_minutes TAR_minutes TBR_minutes TITR_minutes MODD_mmol_L modd_matched_pairs_n modd_valid_day_pairs_n"
    " MAGE MAGE_candidate_mmol_L mage_reason mage_candidate_reason "
    + " ".join(RANGE_PCT + EVENT_COUNTS + CONDITION_COUNTS)
)
EVENT = (
    "window_name window_start window_end event_id event_type event_start event_end duration_min condition_minutes "
    "max_continuous_condition_min nadir peak nadir_time peak_time left_censored right_censored complete_event_flag "
    "censor_reason event_start_period first_observed_time extreme_observed_time outcome_qualified parent_event_id continuous_low_segments_n continuous_low_segments_json"
)
FULL_FEATURES = [
    "mean_pump_d1",
    "delta_mean_pump_d3_d1",
    "mean_pre72h",
    "cv_pre72h_pct",
    "lbgi_pre72h",
    "day_p5_pre24h",
    "night_p5_pre24h",
]


@dataclass(frozen=True)
class Asset:
    path: str
    fields: tuple[str, ...]
    request_fields: bool
    optional: frozenset[str]

    def columns(self, request):
        return [*(request if self.request_fields else ["analysis_id"]), *self.fields]


def _asset(path, names, *, request=True, optional=""):
    return Asset(path, tuple(names.split()), request, frozenset(optional.split()))


ASSETS = {
    "window": _asset(
        "metric_outputs/patient_window_metrics.csv",
        RAW_QC
        + " "
        + WINDOW
        + " ADRR ADRR_complete_days adrr_complete_valid_days_n adrr_complete_reason adrr_partial_sensitivity_delta"
        " adrr_valid_days_n adrr_day_windows_n adrr_reason fasting_cgm_0600_cv_pct fasting_valid_days_n fasting_cv_reason",
    ),
    "day_night": _asset(
        "metric_outputs/patient_day_night_long.csv",
        WINDOW
        + " parent_window period date is_partial_period night_nadir night_nadir_time night_nadir_group_start night_nadir_count",
        optional="night_nadir night_nadir_time night_nadir_group_start night_nadir_count",
    ),
    "daily_risk": _asset(
        "qc_and_coverage/daily_risk.csv",
        "parent_window date is_partial_day day_window_start day_window_end "
        + COVERAGE
        + " adrr_daily_max_low adrr_daily_max_high adrr_daily_sum adrr_day_accepted adrr_day_reason",
        request=False,
    ),
    "fasting": _asset(
        "qc_and_coverage/fasting_day.csv",
        "window_name date fasting_window_start fasting_window_end fasting_expected_points fasting_valid_points fasting_cgm_0600 fasting_reason",
        request=False,
    ),
    "event": _asset(
        "metric_outputs/event_level_long_table.csv",
        EVENT,
        optional="parent_event_id continuous_low_segments_n continuous_low_segments_json",
    ),
    "night_event": _asset(
        "metric_outputs/night_event_level_long_table.csv",
        EVENT,
        optional="parent_event_id continuous_low_segments_n continuous_low_segments_json",
    ),
    "sparse20": _asset(
        "metric_outputs/attd_sparse20_targets.csv",
        "target_id window_name window_start window_end clock target_time actual_time glucose diff_min matched_source_row candidate_n nearest_candidate_n reason",
        request=False,
    ),
    "candidates": _asset(
        "metric_outputs/attd_sparse20_candidates.csv",
        "target_id candidate_time glucose source_row distance_min is_nearest",
        request=False,
    ),
    "sparse5": _asset(
        "metric_outputs/attd_sparse5.csv",
        "sparse_mean_cgm_d1 sparse_delta_mean_cgm_d3_d1 sparse_mean_pre72h sparse_min_pre72h sparse_cv_pre72h_pct sparse_d1_valid_n sparse_d3_valid_n sparse_pre72h_valid_n sparse_mean_cgm_d1_reason sparse_delta_mean_cgm_d3_d1_reason sparse_pre72h_reason sparse_protocol",
    ),
    "full7": _asset(
        "metric_outputs/attd_full7.csv",
        " ".join(FULL_FEATURES)
        + " mean_pump_d3_qc day_pre24h_expected_points day_pre24h_valid_points day_pre24h_coverage_pct"
        " night_pre24h_expected_points night_pre24h_valid_points night_pre24h_coverage_pct pump_d1d3_reason "
        + " ".join(f"{key}_reason" for key in FULL_FEATURES),
    ),
    "file_qc": _asset(
        "qc_and_coverage/patient_file_qc.csv",
        RAW_QC
        + " source_sha256 source_interval_min source_unit first_raw_time cgm_start_first_valid_raw_time invalid_leading_unique_timestamps_n"
        " pump_start_precision pump_end_precision pump_start_parsed pump_end_parsed pump_end_missing pump_end_not_after_start pending_rule_gates pump_qc_reason",
    ),
    "intervals": _asset("qc_and_coverage/raw_intervals.csv", "interval_seconds adjacent_pairs_n"),
    "anomalies": _asset(
        "qc_and_coverage/raw_anomalies.csv",
        "raw_time glucose_raw source_row source_unit device_state timestamp date_only_imputed glucose_numeric_mmol_L glucose_clean below_1p8_flag duplicate_conflict_flag qc_reason raw_qc_reason is_representative",
        request=False,
        optional="device_state",
    ),
    "status": _asset(
        "logs/patient_status.csv",
        "patient_status error_code error_message pump_qc_reason computation_status warning_codes",
    ),
}


def check_request_columns(columns, *, internal=False):
    # analysis_id 是合法的输入身份键。request_row 仅由请求读取器生成。
    reserved = {name for asset in ASSETS.values() for name in asset.fields} | {"run_id"}
    if not internal:
        reserved.add("request_row")
    clash = sorted(reserved.intersection(columns))
    if clash:
        raise CalculationError("ERROR03", "请求列与结果列重名：" + ", ".join(clash), "batch")
