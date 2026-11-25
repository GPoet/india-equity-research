import numpy as np
import pytest

from eqr.forecast.model import ForecastModel, evaluate, fit_horizon, forecast, shows_edge


def synth(n_dates=40, per=30, signal=0.03, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        for _ in range(per):
            mom = rng.normal(0, 0.3)
            vol = 0.02
            y = signal * mom / 0.3 + rng.normal(0, vol * np.sqrt(21))
            rows.append(
                {
                    "day": f"d{d:03d}",
                    "mom_12_1": mom,
                    "rev_1m": rng.normal(0, 0.1),
                    "surprise": None,
                    "value": rng.normal(0, 0.3),
                    "vol_daily": vol,
                    "vol_excess_daily": vol,
                    "jump_var": 0.0,
                    "event_21": 0,
                    "event_42": 0,
                    "y_1m": y,
                    "y_2m": None,
                }
            )
    return rows


def test_fit_finds_signal_and_calibrates() -> None:
    train, test = synth(seed=1), synth(seed=2)
    hm = fit_horizon(train, "1m")
    assert hm.coefs["mom_12_1"] > 0.02
    assert abs(hm.coefs["rev_1m"]) < 0.01
    assert hm.coefs["surprise"] == 0.0  # never known: no weight
    t = evaluate(hm, test, "1m")
    assert t["rank_ic"] > 0.1 and t["rank_ic_t"] > 2
    assert 0.75 <= t["coverage_80"] <= 0.85
    assert shows_edge(t)


def test_pure_noise_shows_no_edge() -> None:
    hm = fit_horizon(synth(signal=0.0, seed=3), "1m")
    assert not shows_edge(evaluate(hm, synth(signal=0.0, seed=4), "1m"))


def test_forecast_ranges_and_gate() -> None:
    hm = fit_horizon(synth(seed=1), "1m")
    x = {
        "mom_12_1": 0.6,
        "rev_1m": 0.0,
        "surprise": None,
        "value": 0.0,
        "vol_daily": 0.02,
        "vol_excess_daily": 0.015,
        "jump_var": 0.003,
        "event_21": 1,
    }
    gated = ForecastModel({"1m": hm}, "a", "b", {}, {"1m": False})
    f = forecast(gated, x, 100.0, 1.0, 0.12)[0]
    assert f.band80[0] < f.band50[0] < f.median < f.band50[1] < f.band80[1]
    assert f.results_in_window and f.lean == "no measured edge"
    assert 0.5 < f.p_beat_nifty < 1
    live = ForecastModel({"1m": hm}, "a", "b", {}, {"1m": True})
    assert forecast(live, x, 100.0, 1.0, 0.12)[0].lean == "lean buy"
    no_event = forecast(live, {**x, "event_21": 0}, 100.0, 1.0, 0.12)[0]
    assert (no_event.band80[1] - no_event.band80[0]) < (f.band80[1] - f.band80[0])


def test_save_load_roundtrip(tmp_path) -> None:
    hm = fit_horizon(synth(), "1m")
    m = ForecastModel({"1m": hm}, "2019-2023", "2024-2026", {"1m": {"n": 1}}, {"1m": True})
    m.save(tmp_path / "m.json")
    back = ForecastModel.load(tmp_path / "m.json")
    assert back.horizons["1m"].coefs == pytest.approx(hm.coefs)
    assert back.has_edge == {"1m": True}
