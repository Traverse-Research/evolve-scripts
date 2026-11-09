import numpy as np
import pandas as pd
import pytest
from conftest import frame, make_recording, scope, simple_frames

from evolve_charts import scores
from evolve_charts.loader import load_recording
from evolve_charts.score_catalog import MULTIPLIERS


def test_gpu_driver_and_energy_scores():
    result = load_recording(make_recording(simple_frames(2.0)), "x.evolve")
    desktop = MULTIPLIERS["Desktop"]["RayTracingInline"]
    # Average per frame over every frame, the warm-up frame included.
    ray_tracing_s = (20 * 2.0 + 50.0) / 20 / 1e3
    assert result.scores["Ray Tracing"] == int(desktop["RayTracing"] / ray_tracing_s)
    assert result.scores["Compute"] == int(desktop["Compute"] / 0.5e-3)
    assert result.scores["Driver"] == int(desktop["Driver"] / 1e-6)
    energy = np.float32(10_600) * np.exp(np.float32(-desktop["Energy"]) * np.float32(200.0))
    assert result.scores["Energy Consumption"] == int(energy)
    # In Evolve's order; workloads without GPU time have no score.
    assert list(result.scores) == ["Ray Tracing", "Compute", "Driver", "Energy Consumption"]


def test_benchmarks_only_have_their_own_scores():
    result = load_recording(make_recording(simple_frames(2.0), variant="Nrc"), "x.evolve")
    assert result.scores == {}


def test_phone_driver_multiplier_depends_on_the_evolve_version():
    assert scores.multiplier("Driver", "RayTracingInline", "Phone", (16, 1)) == 553.17
    assert scores.multiplier("Driver", "RayTracingInline", "Phone", (17, 0)) == 40.0
    assert scores.multiplier("Driver", "RayTracingInline", "Desktop", (16, 1)) == 11.93


def test_energy_counter_wins_over_sampled_power():
    metrics = pd.DataFrame(
        {
            "sample_time_ns": [0, 2_000_000_000],
            "gpu_energy_j": [100.0, 500.0],
            "board_power_w": [999.0, 999.0],
            "gpu_power_w": [None, None],
        }
    )
    assert scores._average_power_w(metrics) == pytest.approx(200.0)


def test_image_quality_scores():
    frames = [
        frame(index * 0.5, [{"Fsr execute": [scope(0, 1)]}], flip=0.3156 + index * 0.001, ssim=0.777)
        for index in range(20)
    ]
    result = load_recording(make_recording(frames, variant="Upscaling"), "x.evolve")
    # SSIM at its calibrated best scores 10000.
    assert result.scores["Image Quality 2"] == pytest.approx(10_000, abs=1)
    # FLIP pools the mean with the worst 10% of frames, half and half, between its best and worst.
    flip = [0.3156 + index * 0.001 for index in range(20)]
    pooled = 0.5 * np.mean(flip) + 0.5 * np.mean(sorted(flip)[-2:])
    assert result.scores["Image Quality 1"] == pytest.approx(10_000 * (0.4255 - pooled) / (0.4255 - 0.3156), abs=1)
    assert "Upscaler Performance" in result.scores
