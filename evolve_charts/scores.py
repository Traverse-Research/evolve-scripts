"""Evolve's scores, calculated from a run's tables the way Evolve does (`evolve-datakit-scores`).

A `.evolve` file holds the measurements, not the scores. The calibrated multipliers come from
`score_catalog.py`, generated from Evolve's Rust source by `tools/sync_scores.py`.
"""

import math

import numpy as np
import pandas as pd

from .categories import workload_variants
from .score_catalog import (
    DRIVER_EXCLUDES_PRESENT,
    ENERGY_SCALE,
    GPU_SCORES,
    IMAGE_QUALITY,
    MULTIPLIERS,
    PHONE_DRIVER_WITH_PRESENT,
    SCORE_NAMES,
    SCORE_ORDER,
)


def multiplier(score: str, variant: str, platform: str, version: tuple[int, int] | None = None) -> float | None:
    if score == "Driver" and platform == "Phone" and (version is None or version < DRIVER_EXCLUDES_PRESENT):
        return PHONE_DRIVER_WITH_PRESENT.get(variant)
    return MULTIPLIERS.get(platform, {}).get(variant, {}).get(score)


def calculate(
    variant: str,
    platform: str,
    version: tuple[int, int] | None,
    num_frames: int,
    gpu_scopes: pd.DataFrame,
    cpu_scope_ns: pd.Series,
    flip: pd.Series,
    ssim: pd.Series,
    metrics: pd.DataFrame,
) -> dict[str, float]:
    """Score name -> score, for every score the benchmark has on this platform, in Evolve's order.

    `gpu_scopes` has a `name` and `len_ns` column; `cpu_scope_ns` holds the duration of every driver call.
    """
    has = MULTIPLIERS.get(platform, {}).get(variant, {})
    scores: dict[str, int] = {}

    def per_frame(score: str, total_ns: int) -> int | None:
        factor = multiplier(score, variant, platform, version)
        if factor is None or total_ns == 0 or num_frames == 0:
            return None
        return _u32(factor / (round(total_ns / num_frames) / 1e9))

    if any(score in has for score in GPU_SCORES.values()):
        per_name = gpu_scopes.groupby("name", observed=True)["len_ns"].sum()
        totals = dict.fromkeys(GPU_SCORES, 0)
        for name, total in per_name.items():
            for workload in workload_variants(name):
                if workload in totals:
                    totals[workload] += int(total)
        for workload, score in GPU_SCORES.items():
            if (value := per_frame(score, totals[workload])) is not None:
                scores[score] = value

    if "Driver" in has and (value := per_frame("Driver", int(cpu_scope_ns.sum()))) is not None:
        scores["Driver"] = value

    for score, errors in [("UpscalerImageQuality1", flip), ("UpscalerImageQuality2", ssim)]:
        if score in has and (value := _image_quality(variant, score, errors.dropna().to_numpy())) is not None:
            scores[score] = value

    if "Energy" in has and (power := _average_power_w(metrics)) is not None:
        energy = np.float32(ENERGY_SCALE) * np.exp(np.float32(-has["Energy"]) * power)
        scores["Energy"] = _u32(float(energy))

    return {SCORE_NAMES[score]: float(scores[score]) for score in SCORE_ORDER if score in scores}


def _u32(value: float) -> int:
    """Rust's saturating `as u32`."""
    return 0 if math.isnan(value) else int(min(max(value, 0), 2**32 - 1))


def _f32_sum(values: np.ndarray) -> np.float32:
    """Summed one value at a time in f32, like Rust's `iter().sum::<f32>()`."""
    return np.cumsum(values.astype(np.float32), dtype=np.float32)[-1]


def _average_power_w(metrics: pd.DataFrame) -> np.float32 | None:
    """With an energy counter in the first and last samples, the energy used over the time between
    them; otherwise the mean sampled board power, or GPU power for a sample without it."""
    if metrics.empty:
        return None
    energy = metrics["gpu_energy_j"]
    if pd.notna(energy.iloc[0]) and pd.notna(energy.iloc[-1]):
        joules = np.float32(energy.iloc[-1] - energy.iloc[0])
        elapsed_ns = max(int(metrics["sample_time_ns"].iloc[-1]) - int(metrics["sample_time_ns"].iloc[0]), 0)
        return joules / np.float32(elapsed_ns / 1e9)
    power = metrics["board_power_w"].fillna(metrics["gpu_power_w"]).dropna().to_numpy()
    return _f32_sum(power) / np.float32(len(power)) if len(power) else None


def _image_quality(variant: str, score: str, errors: np.ndarray) -> int | None:
    if not len(errors):
        return None
    if variant == "UpscalingQualcommImageQuality":
        return 0
    errors = errors.astype(np.float32)
    worse_is_higher = score == "UpscalerImageQuality1"
    mean = _f32_sum(errors) / np.float32(len(errors))
    ordered = np.sort(errors)
    count = max(math.ceil(np.float32(len(errors)) * np.float32(IMAGE_QUALITY["WORST_CASE_FRACTION"])), 1)
    worst = ordered[len(ordered) - count :] if worse_is_higher else ordered[:count]
    weight = np.float32(IMAGE_QUALITY["WORST_CASE_POOL_WEIGHT"])
    pooled = (np.float32(1) - weight) * mean + weight * (_f32_sum(worst) / np.float32(len(worst)))
    if worse_is_higher:
        best, worst_value = np.float32(IMAGE_QUALITY["BEST_FLIP"]), np.float32(IMAGE_QUALITY["WORST_FLIP"])
        normalized = (worst_value - pooled) / (worst_value - best)
    else:
        best, worst_value = np.float32(IMAGE_QUALITY["BEST_SSIM"]), np.float32(IMAGE_QUALITY["WORST_SSIM"])
        normalized = (pooled - worst_value) / (best - worst_value)
    return _u32(float(max(normalized, np.float32(0)) * np.float32(10_000)))
