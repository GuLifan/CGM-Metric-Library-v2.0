"""ADRR 只取覆盖合格自然日的每日极值和，缺日不能按患者总均值替代。"""

import numpy as np
import pandas as pd

from cgm_library.metrics.core import risk_values
from cgm_library.metrics.daily import adrr_by_day
from cgm_library.timeline.groups import make_groups


def test_adrr_uses_daily_maxima_and_omits_coverage_failed_day():
    start = pd.Timestamp("2026-01-01", tz="Asia/Shanghai")
    times = pd.date_range(start, periods=2 * 288, freq="5min")
    values = np.full(len(times), 6.0)
    values[0] = 3.0
    values[1] = 13.9
    values[288:] = np.nan
    values[288:388] = 7.0  # 第二日覆盖不足 70%，不得降低第一日 ADRR。
    groups = make_groups(pd.DataFrame({"timestamp": times, "glucose_clean": values}), 5)
    result, days = adrr_by_day(groups, start, start + pd.Timedelta(days=2))
    low, high, _ = risk_values(np.array([3.0, 13.9, 6.0]))
    assert np.isclose(result["ADRR"], low.max() + high.max())
    assert result["adrr_valid_days_n"] == 1
    assert len(days) == 2
    assert days[1]["adrr_day_reason"] == "DAY_COVERAGE_BELOW_THRESHOLD"
