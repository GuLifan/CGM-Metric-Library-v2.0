"""不依赖R的医学边界断言；不能替代完整参考验收。"""

import numpy as np
import pandas as pd
import pytest

from cgm_library.metrics.mage import calculate_mage, directional_excursions


def test_amplitude_equal_to_sd_is_excluded():
    assert directional_excursions(np.array([4.0, 6.0, 4.0]), 2.0, True) == []
    assert directional_excursions(np.array([4.0, 6.1, 4.0]), 2.0, True) == [(0, 1)]


def test_all_segments_receive_whole_window_sample_sd(monkeypatch):
    from cgm_library.metrics import mage

    values = np.r_[np.tile([4.0, 6.0], 60), np.full(80, np.nan), np.tile([5.0, 13.0], 60)]
    times = pd.date_range("2026-01-01", periods=len(values), freq="5min")
    observed = []
    original = mage.segment_mage

    def record(x, t, threshold):
        observed.append(threshold)
        return original(x, t, threshold)

    monkeypatch.setattr(mage, "segment_mage", record)
    calculate_mage(times, values)
    expected = np.std(values[np.isfinite(values)], ddof=1) * 18
    assert len(observed) == 2
    assert observed == pytest.approx([expected, expected])


@pytest.mark.parametrize(
    "times,values",
    [
        ([1, 2], [4, 5]),
        (pd.date_range("2026-01-01", periods=2), [5]),
        ([pd.Timestamp("2026-01-01")] * 2, [5, 6]),
        ([pd.NaT], [5]),
        (pd.date_range("2026-01-01", periods=2)[::-1], [5, 6]),
        (pd.date_range("2026-01-01", periods=2), [np.inf, 5]),
    ],
)
def test_mage_rejects_ambiguous_inputs(times, values):
    with pytest.raises(ValueError, match="MAGE"):
        calculate_mage(times, values)
