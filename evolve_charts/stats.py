"""Turns loaded results into the numbers the charts show. Everything here is plain pandas.

Two levels of detail: `"workload"` (Evolve's workload categories, the GPU work it scores) and
`"pass"` (the passes they are made of).
"""

from typing import Literal

import pandas as pd

from .categories import WORKLOAD_ORDER, workloads
from .loader import Result

Level = Literal["workload", "pass"]
# Narrows passes to one workload category, e.g. ("workload", "Raytracing").
Within = tuple[Literal["workload"], str] | None

# Sensor column -> (label, unit) in the order they're listed.
TELEMETRY = {
    "gpu_clock_mhz": ("GPU clock", "MHz"),
    "power_w": ("GPU power", "W"),
    "edge_temp_c": ("GPU temperature", "°C"),
    "hotspot_temp_c": ("GPU hotspot temperature", "°C"),
    "gpu_usage_pct": ("GPU usage", "%"),
    "vram_clock_mhz": ("Memory clock", "MHz"),
    "vram_used_mb": ("VRAM used", "MB"),
    "fan_rpm": ("Fan speed", "RPM"),
    "fan_pct": ("Fan speed", "%"),
    "voltage_mv": ("GPU voltage", "mV"),
}


def has_level(result: Result, level: Level) -> bool:
    if level == "workload":
        return result.workloads is not None and len(result.workloads.columns) > 3
    return result.passes is not None


def trimmed_frames(result: Result, skip_s: float) -> pd.DataFrame:
    frames = result.frames[result.frames["seq_s"] >= skip_s].copy()
    # Board power is what a wall meter sees; fall back to chip or SoC power where that's all there is.
    frames["power_w"] = frames["board_power_w"].fillna(frames["gpu_power_w"]).fillna(frames["soc_power_w"])
    return frames


def per_frame(result: Result, skip_s: float, level: Level, within: Within = None) -> pd.DataFrame:
    """GPU milliseconds per frame, one column per item; frames where an item didn't run count as 0."""
    if level == "workload":
        table = result.workloads[result.workloads["seq_s"] >= skip_s]
        return table.set_index(["loop", "frame"]).drop(columns="seq_s")

    passes = result.passes[result.passes["seq_s"] >= skip_s]
    if within is not None:
        _, name = within
        passes = passes[passes["pass"].map(lambda scope: name in workloads(scope))]
    wide = passes.pivot_table(index=["loop", "frame"], columns="pass", values="ms", aggfunc="sum")
    frame_index = trimmed_frames(result, skip_s).set_index(["loop", "frame"]).index
    return wide.reindex(frame_index).fillna(0.0)


def summary(results: dict[str, Result], skip_s: float, level: Level, within: Within = None) -> pd.DataFrame:
    """One row per (result, item) with mean/median/p5/p95 milliseconds per frame.

    Results without data for the level (e.g. no deep analysis) are left out.
    """
    rows = []
    for label, result in results.items():
        if not has_level(result, level):
            continue
        wide = per_frame(result, skip_s, level, within)
        total = per_frame(result, skip_s, level).sum(axis=1).mean() if within else wide.sum(axis=1).mean()
        for item in wide.columns:
            column = wide[item]
            rows.append(
                {
                    "result": label,
                    "item": item,
                    "workload": ", ".join(workloads(item)) if level == "pass" else "",
                    "mean_ms": column.mean(),
                    "median_ms": column.median(),
                    "p5_ms": column.quantile(0.05),
                    "p95_ms": column.quantile(0.95),
                    "share_pct": 100 * column.mean() / total if total else float("nan"),
                    "ran_in_pct_of_frames": 100 * (column > 0).mean(),
                }
            )
    columns = [
        "result",
        "item",
        "workload",
        "mean_ms",
        "median_ms",
        "p5_ms",
        "p95_ms",
        "share_pct",
        "ran_in_pct_of_frames",
    ]
    return pd.DataFrame(rows, columns=columns)


def ordered(items, level: Level) -> list[str]:
    """Items in Evolve's order for categories; passes keep the order they were given in."""
    order = WORKLOAD_ORDER if level == "workload" else None
    items = list(dict.fromkeys(items))
    return [item for item in order if item in items] if order else items


def frame_totals(results: dict[str, Result], skip_s: float) -> pd.DataFrame:
    """Deep analysis only: GPU time per frame of all categorized passes, what was left out, and the span."""
    rows = []
    for label, result in results.items():
        if result.passes is None:
            continue
        frames = trimmed_frames(result, skip_s)
        rows.append(
            {
                "result": label,
                "gpu_sum_ms": frames["gpu_sum_ms"].mean(),
                "left_out_ms": frames["left_out_ms"].mean(),
                "gpu_span_ms": frames["gpu_span_ms"].mean(),
            }
        )
    return pd.DataFrame(rows, columns=["result", "gpu_sum_ms", "left_out_ms", "gpu_span_ms"])


def timeline(
    result: Result, skip_s: float, level: Level, items: list[str], smooth_s: float, within: Within = None
) -> pd.DataFrame:
    """Per-frame milliseconds over benchmark time, averaged over loops by frame index."""
    wide = per_frame(result, skip_s, level, within).reindex(columns=items, fill_value=0.0)
    source = result.workloads if level == "workload" else trimmed_frames(result, skip_s)
    wide["seq_s"] = source.set_index(["loop", "frame"])["seq_s"]
    return _smooth(wide.groupby(level="frame").mean().set_index("seq_s"), smooth_s)


def telemetry_timeline(result: Result, skip_s: float, smooth_s: float) -> pd.DataFrame:
    frames = trimmed_frames(result, skip_s)
    columns = [column for column in TELEMETRY if frames[column].notna().any()]
    return _smooth(frames.groupby("frame")[["seq_s", *columns]].mean().set_index("seq_s"), smooth_s)


def telemetry_summary(results: dict[str, Result], skip_s: float) -> pd.DataFrame:
    rows = []
    for label, result in results.items():
        if result.frames is None:
            continue
        frames = trimmed_frames(result, skip_s)
        row = {"result": label}
        for column, (name, unit) in TELEMETRY.items():
            if frames[column].notna().any():
                row[f"{name} avg ({unit})"] = frames[column].mean()
                row[f"{name} max ({unit})"] = frames[column].max()
        rows.append(row)
    return pd.DataFrame(rows).set_index("result")


def scores_table(results: dict[str, Result]) -> pd.DataFrame:
    """Scores as rows (in the order Evolve exports them), results as columns."""
    names = list(dict.fromkeys(name for result in results.values() for name in result.scores))
    return pd.DataFrame(
        {label: [result.scores.get(name) for name in names] for label, result in results.items() if result.scores},
        index=names,
    )


def comparison_table(item_summary: pd.DataFrame, labels: list[str], baseline: str) -> pd.DataFrame:
    """One row per item: mean ms per result, then each other result's % difference from the baseline."""
    labels = [label for label in labels if label in set(item_summary["result"])]
    wide = item_summary.pivot_table(index=["item", "workload"], columns="result", values="mean_ms").reindex(
        columns=labels
    )
    table = wide.copy()
    for label in labels:
        if label != baseline and baseline in wide:
            table[f"{label} vs {baseline}"] = 100 * (wide[label] - wide[baseline]) / wide[baseline]
    return table.reset_index()


def key_numbers(item_summary: pd.DataFrame, item: str, baseline: str) -> str:
    """A sentence a journalist can quote, e.g. "Shadows Tracing: 1.44 ms per frame on A, 0.80 ms on B (44% less)"."""
    rows = item_summary[item_summary["item"] == item].set_index("result")["mean_ms"]
    if rows.empty or baseline not in rows:
        return ""
    base = rows[baseline]
    parts = [f"{base:.2f} ms per frame on {baseline}"]
    for label, ms in rows.items():
        if label == baseline:
            continue
        if base > 0:
            change = 100 * (ms - base) / base
            relation = f"{abs(change):.0f}% {'more' if change > 0 else 'less'}" if abs(change) >= 0.5 else "the same"
            parts.append(f"{ms:.2f} ms on {label} ({relation})")
        else:
            parts.append(f"{ms:.2f} ms on {label}")
    return f"{item}: " + ", ".join(parts) + "."


def wide_for_spreadsheets(item_summary: pd.DataFrame, value: str = "mean_ms") -> pd.DataFrame:
    """Items as rows, results as columns: the shape Datawrapper and Excel charts expect."""
    return item_summary.pivot_table(index=["workload", "item"], columns="result", values=value).reset_index()


def _smooth(by_time: pd.DataFrame, smooth_s: float) -> pd.DataFrame:
    """Centred rolling mean over `smooth_s` seconds of benchmark time; exports differ a lot in frames per second."""
    if smooth_s <= 0 or len(by_time) < 2:
        return by_time
    step = pd.Series(by_time.index).diff().median()
    window = round(smooth_s / step) if step > 0 else 1
    if window <= 1:
        return by_time
    return by_time.rolling(window, center=True, min_periods=1).mean()
