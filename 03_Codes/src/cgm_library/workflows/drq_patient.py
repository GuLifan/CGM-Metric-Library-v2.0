"""DRQ calculations reuse the v2.0.0 timeline, coverage, risk and event contracts."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from cgm_library.contracts.schema import CalculationError
from cgm_library.events.engine import confirmed_event_types
from cgm_library.io.reader import locate_source, parse_anchor, read_cgm
from cgm_library.io.tables import four_places
from cgm_library.metrics.core import pooled_metrics
from cgm_library.metrics.daily import adrr_by_day
from cgm_library.metrics.fasting import fasting_cv, fasting_values
from cgm_library.qc.raw import RawEvidenceError, clean_observations
from cgm_library.studies.drq import (
    CONDITIONAL_FIELDS,
    CORE,
    EVENT_FIELDS,
    PERIODS,
    research_windows,
)
from cgm_library.timeline.groups import OverfullMinuteSlot, make_groups
from cgm_library.windows.coverage import window_view
from cgm_library.workflows.periods import day_night_periods
from cgm_library.workflows.window import calculate_confirmed_window


def result_json(value):
    """Decimals are explicit four-place strings; timestamps retain their full precision."""

    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, (float, np.floating)):
            return four_places(v) if np.isfinite(v) else None
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if v is pd.NaT or v is pd.NA:
            return None
        return v

    return json.dumps(clean(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _event_fields(events, qualified):
    result = {}
    for kind in EVENT_FIELDS + CONDITIONAL_FIELDS:
        if kind in EVENT_FIELDS:
            selected = [event for event in events if event["event_type"] == kind]
        else:
            threshold = int(kind[-1]) / 10 + 3
            selected = [
                event
                for event in events
                if event["event_type"] == "hypo_episode_lt3p9" and event["nadir"] < threshold
            ]
        result[kind + "_n"] = len(selected) if qualified else np.nan
        result[kind + "_events_json"] = result_json(selected) if qualified else None
    return result


class DrqCalculator:
    """Per-patient caches use real window boundaries, never rounded export values."""

    def __init__(self, groups, observations, admission, discharge, coverage):
        self.groups = groups
        self.observations = observations
        self.admission = admission
        self.discharge = discharge
        self.coverage = coverage
        self.cache = {}
        self.period_cache = {}

    def period(self, start, end):
        key = start, end
        if key not in self.period_cache:
            view, qc = window_view(self.groups, start, end, threshold_pct=self.coverage)
            events = confirmed_event_types(self.groups, start, end)
            self.period_cache[key] = view, qc, events
        return self.period_cache[key]

    def calculate(self, start, end):
        key = start, end
        if key in self.cache:
            return self.cache[key]
        row, events = calculate_confirmed_window(
            self.groups, start, end, window_name="drq", coverage_min_pct=self.coverage
        )
        qualified = row["sufficient_flag"]
        adr, days = adrr_by_day(self.groups, start, end, coverage_min_pct=self.coverage)
        mornings = fasting_values(self.groups, start, end, self.admission, self.discharge)
        # Match the existing all_record fasting contract, whose mornings cover the admission.
        morning_cv = fasting_cv(mornings)
        if not qualified:
            for field in ("ADRR", "ADRR_complete_days", "adrr_partial_sensitivity_delta"):
                adr[field] = np.nan
            morning_cv["fasting_cgm_0600_cv_pct"] = np.nan
        row.update(adr)
        row.update(morning_cv)
        raw = self.observations.loc[
            self.observations.timestamp.ge(start) & self.observations.timestamp.lt(end),
            "glucose_clean",
        ]
        low = raw.loc[raw.gt(0) & raw.lt(1.8)]
        row["below_1p8_valid_raw_n"] = len(low) if qualified else np.nan
        row["below_1p8_valid_raw_min"] = float(low.min()) if qualified and len(low) else np.nan
        row.update(_event_fields(events, qualified))
        period_data = {p: [] for p in PERIODS}
        night_nadirs = []
        night_facts = []
        for period, date, left, right in day_night_periods(start, end):
            view, qc, facts = self.period(left, right)
            period_data[period].append((view, qc, facts))
            if period == "night_00to06":
                night_facts.extend(facts)
                valid = view.loc[view.glucose_clean.notna()]
                nadir = (
                    float(valid.glucose_clean.min())
                    if qc["sufficient_flag"] and len(valid)
                    else None
                )
                first = (
                    valid.loc[valid.glucose_clean.eq(nadir)].iloc[0] if nadir is not None else None
                )
                night_nadirs.append(
                    {
                        "date": date,
                        "window_start": left,
                        "window_end": right,
                        "nadir_mmol_L": nadir,
                        "first_observed_time": first.first_valid_raw_time
                        if first is not None
                        else None,
                        "group_start": first.group_start if first is not None else None,
                        "coverage_pct": qc["coverage_pct"],
                        "sufficient_flag": qc["sufficient_flag"],
                    }
                )
        for period, parts in period_data.items():
            valid_minutes = sum(qc["valid_minutes"] for _, qc, _ in parts)
            window_minutes = sum(qc["window_minutes"] for _, qc, _ in parts)
            coverage = 100 * valid_minutes / window_minutes if window_minutes else np.nan
            enough = valid_minutes > 0 and coverage >= self.coverage
            frame = pd.concat([view for view, _, _ in parts], ignore_index=True) if parts else None
            metrics = (
                pooled_metrics(frame.glucose_clean.to_numpy(), frame.support_minutes.to_numpy())
                if enough
                else pooled_metrics([])
            )
            metrics = {k: metrics[k] for k in CORE}
            facts = [fact for _, _, items in parts for fact in items]
            metrics.update(_event_fields(facts, enough))
            row.update({f"{period}__{k}": v for k, v in metrics.items()})
            row[f"{period}__coverage_pct"] = coverage
            row[f"{period}__sufficient_flag"] = enough
        row["night_00to06__nadirs_json"] = result_json(night_nadirs)
        evidence = {
            "events": events,
            "night_events": night_facts,
            "days": days,
            "mornings": mornings,
        }
        self.cache[key] = row, evidence
        return row, evidence


def calculate_drq_patient(request, config):
    source, source_config = locate_source(request, config)
    content = source.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    _, observations, raw_qc = clean_observations(
        read_cgm(source, source_config.unit, content=content)
    )
    try:
        groups = make_groups(observations, source_config.interval_min)
    except OverfullMinuteSlot as exc:
        raise RawEvidenceError("ERROR05", str(exc), pd.DataFrame()) from exc
    origin = observations.loc[observations.glucose_clean.notna(), "timestamp"].iloc[0]
    admission = parse_anchor(request["入院日期"])
    discharge = parse_anchor(request["出院日期"])
    if discharge <= admission:
        raise CalculationError("ERROR04", "出院须晚于入院", "patient")
    pump_reason = ""
    pump_start = pump_end = None
    try:
        start = str(request["胰岛素泵开始时间"]).strip()
        stop = str(request["胰岛素泵停止时间"]).strip()
        pump_start = parse_anchor(start, pump_start=True) if start else None
        pump_end = parse_anchor(stop) if stop else None
        if pump_start is None:
            pump_reason = "PUMP_START_MISSING"
        elif pump_end is None:
            pump_reason = "PUMP_STOP_MISSING"
        elif pump_end <= pump_start:
            pump_reason = "PUMP_STOP_NOT_AFTER_START"
    except CalculationError:
        pump_reason = "PUMP_TIME_INVALID"
    windows = research_windows(
        origin,
        groups.group_start.iloc[0],
        groups.group_end.iloc[-1],
        admission,
        discharge,
        pump_start,
        pump_end,
    )
    calculator = DrqCalculator(groups, observations, admission, discharge, config.coverage_pct)
    tables, audit = {}, {}
    daily_quality = {}
    for name, (start, end) in windows.items():
        reason = pump_reason if name == "pump_period" else ""
        if start is None or end is None or end <= start:
            reason = reason or "EMPTY_OR_REVERSED_WINDOW"
        if reason:
            tables[name] = {"window_start": start, "window_end": end}
            audit[name] = {"reason": reason, "sufficient_flag": False}
            continue
        row, evidence = calculator.calculate(start, end)
        row = row.copy()
        if name == "all_record":
            mornings = fasting_values(groups, admission, discharge, admission, discharge)
            f = fasting_cv(mornings)
            if not row["sufficient_flag"]:
                f["fasting_cgm_0600_cv_pct"] = np.nan
            row.update(f)
            evidence = evidence | {"mornings": mornings}
        if name.startswith("cgm_day_"):
            number = int(name.removeprefix("cgm_day_"))
            daily_quality[number] = row["sufficient_flag"]
            value = np.nan
            if number > 1 and row["sufficient_flag"] and daily_quality.get(number - 1, False):
                view, _ = window_view(groups, start, end)
                previous, _ = window_view(groups, start - pd.Timedelta(days=1), start)
                before = previous.set_index("group_start").glucose_clean.dropna()
                current = view.set_index("group_start").glucose_clean.dropna()
                aligned = before.reindex(current.index - pd.Timedelta(days=1)).to_numpy()
                diff = abs(current.to_numpy() - aligned)
                if np.isfinite(diff).any():
                    value = float(np.nanmean(diff))
            row["MODD_vs_previous_cgm_day_mmol_L"] = value
        tables[name] = row
        audit[name] = {
            "reason": row["metric_reason"],
            "coverage_pct": row["coverage_pct"],
            "sufficient_flag": row["sufficient_flag"],
            "expected_points": row["expected_points"],
            "valid_points": row["valid_points"],
            "mage_reason": row["mage_reason"],
            "mage_candidate_reason": row["mage_candidate_reason"],
            "window_start": start,
            "window_end": end,
            **evidence,
        }
    fbs = {}
    for number in range(1, 15):
        start, end = windows[f"cgm_day_{number}"]
        morning = fasting_values(groups, start, end, admission, discharge)
        fbs[f"cgm_d{number}__fasting_cgm_0600"] = (
            morning[0]["fasting_cgm_0600"] if morning else np.nan
        )
    return {
        "tables": tables,
        "fbs": fbs,
        "audit": audit,
        "source_sha256": digest,
        "source_interval_min": source_config.interval_min,
        "source_unit": source_config.unit,
        "raw_qc": raw_qc,
    }
