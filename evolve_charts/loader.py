"""Reads every Evolve export into tidy pandas tables.

Evolve exports three kinds of data, alone or bundled in the score screen's Export zip:

- **scores** (`scores.csv`): one score per workload category per loop, higher is better.
- **per frame** (`frametimes.csv`, also inside `evolve_results.csv`): GPU time per workload
  category, plus GPU sensor readings, for every frame.
- **deep analysis** (`deep_analysis.json`, Evolve Professional): the GPU time of every render pass
  in every frame.

`evolve_results.csv` combines system information, scores and per-frame data in one file.
"""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath

import pandas as pd

from .categories import WORKLOAD_ORDER, workloads

DEEP_ANALYSIS = "deep_analysis.json"

METADATA_COLUMNS = [
    "Evolve Version",
    "System Name",
    "CPU",
    "GPU",
    "OS Name",
    "OS Version",
    "GPU Driver Version",
    "Rendering Backend",
]

# Per-frame CSV column -> workload category name (as Evolve shows it).
WORKLOAD_COLUMNS = {
    "Ray Tracing (ns)": "Raytracing",
    "Acceleration Structure Build (ns)": "Acceleration Structure Builds",
    "Rasterization (ns)": "Rasterization",
    "Compute (ns)": "Compute",
    "Workgraphs (ns)": "Workgraphs",
    "NRC (ns)": "NRC",
    "Upscaling Performance (ns)": "Upscaling",
}

# Sensor columns in `Result.frames`, filled from deep analysis (GpuMetrics fields) or the per-frame CSV.
METRIC_FIELDS = {
    "usage_percentage": "gpu_usage_pct",
    "clock_speed_in_mhz": "gpu_clock_mhz",
    "vram_clock_speed_in_mhz": "vram_clock_mhz",
    "power_usage_in_w": "gpu_power_w",
    "board_power_usage_in_w": "board_power_w",
    "soc_power_usage_in_w": "soc_power_w",
    "voltage_in_mv": "voltage_mv",
    "vram_usage_in_mb": "vram_used_mb",
    "edge_temperature_in_c": "edge_temp_c",
    "hotspot_temperature_in_c": "hotspot_temp_c",
}
FAN_FIELDS = {"Rpm": "fan_rpm", "Percent": "fan_pct"}
METRIC_CSV_COLUMNS = {
    # Evolve writes board power into the column it calls "Energy".
    "Energy (W)": "board_power_w",
    "Gpu Usage (%)": "gpu_usage_pct",
    "Clock Speed (Mhz)": "gpu_clock_mhz",
    "Vram Clock Speed (Mhz)": "vram_clock_mhz",
    "Gpu Voltage (mV)": "voltage_mv",
    "Fan Speed (rpm)": "fan_rpm",
    "Fan Speed (%)": "fan_pct",
    "Edge Temperature (C)": "edge_temp_c",
    "Hot Spot Temperature (C)": "hotspot_temp_c",
}
SENSOR_COLUMNS = list(dict.fromkeys([*METRIC_FIELDS.values(), *FAN_FIELDS.values(), *METRIC_CSV_COLUMNS.values()]))


class ExportError(Exception):
    """A problem with an input file, worded for the person using the tool."""


@dataclass
class Result:
    id: str
    filename: str
    metadata: dict[str, str] = field(default_factory=dict)
    # Score name -> score, averaged over loops. Scores Evolve didn't produce for this run are absent.
    scores: dict[str, float] = field(default_factory=dict)
    # One row per (loop, frame): GPU milliseconds per workload category, one column each.
    workloads: pd.DataFrame | None = None
    # One row per (loop, frame): sensor readings, and from deep analysis the GPU time sum and span.
    frames: pd.DataFrame | None = None
    # Deep analysis only. One row per (loop, frame, pass): ms is the pass' own GPU time in that frame;
    # top_ms only counts instances not nested inside another scope, so summing it never double-counts.
    passes: pd.DataFrame | None = None
    # Deep analysis only: total GPU milliseconds per pass that Evolve doesn't assign to a workload category.
    left_out: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def gpu(self) -> str:
        return self.metadata.get("GPU") or self.filename

    @property
    def contents(self) -> list[str]:
        """What this result contains, in the words the tool uses."""
        return [
            name
            for name, present in [
                ("Scores", bool(self.scores)),
                ("Per frame", self.workloads is not None),
                ("Deep analysis", self.passes is not None),
            ]
            if present
        ]


def load_export(data: bytes, filename: str) -> Result:
    result = Result(id=hashlib.sha256(data).hexdigest()[:12], filename=filename)
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".zip":
        _read_zip(result, data)
    elif suffix == ".csv":
        _read_csv(result, data, filename)
    elif suffix == ".json":
        _read_deep_analysis(result, data, filename)
    else:
        raise ExportError(f"{filename}: use an Evolve export (.zip, .csv or deep analysis .json).")

    if not result.contents:
        raise ExportError(f"{filename} contains no Evolve scores, per-frame data or deep analysis.")
    if result.workloads is None and result.passes is not None:
        result.workloads = _workloads_from_passes(result.passes, result.frames)
    if not result.metadata:
        result.warnings.append(f"{filename} has no system information (GPU, driver); it's labelled by file name.")
    return result


def _read_zip(result: Result, data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExportError(f"{result.filename} is not a zip file.") from None
    members = {PurePath(name).name: name for name in archive.namelist()}

    # The combined CSV holds everything the separate CSVs do, plus system information.
    for name in ["evolve_results.csv", "frametimes.csv", "scores.csv"]:
        if name in members:
            _read_csv(result, archive.read(members[name]), f"{result.filename}/{name}")
    if DEEP_ANALYSIS in members:
        _read_deep_analysis(result, archive.read(members[DEEP_ANALYSIS]), result.filename)


def _read_csv(result: Result, data: bytes, name: str) -> None:
    try:
        table = pd.read_csv(io.BytesIO(data), encoding="utf-8-sig", dtype=dict.fromkeys(METADATA_COLUMNS, str))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError):
        raise ExportError(f"{name} can't be read as a CSV file.") from None
    columns = list(table.columns)

    if "Evolve Version" in columns and not result.metadata:
        first = table.iloc[0]
        result.metadata = {key: str(first[key]) for key in METADATA_COLUMNS if key in table and pd.notna(first[key])}
    if columns[:1] == ["Loop"] or "Evolve Version" in columns:
        loop = "Loop" if "Loop" in columns else "Loop Index"
        score_columns = columns[1:] if loop == "Loop" else columns[len(_metadata_prefix(columns)) : columns.index(loop)]
        if not result.scores:
            result.scores = _scores(table.drop_duplicates(loop), score_columns)
    if {"Loop Index", "Frame", "Benchmark Time (ns)"} <= set(columns) and result.workloads is None:
        result.workloads, sensors = _per_frame(table)
        if result.frames is None:
            result.frames = sensors
    if not columns or not (result.scores or result.workloads is not None or "Evolve Version" in columns):
        raise ExportError(f"{name} isn't an Evolve scores or per-frame export.")


def _metadata_prefix(columns: list[str]) -> list[str]:
    return [column for column in columns if column in METADATA_COLUMNS]


def _scores(per_loop: pd.DataFrame, columns: list[str]) -> dict[str, float]:
    scores = {}
    for column in columns:
        values = pd.to_numeric(per_loop[column], errors="coerce")
        # Evolve writes 0 for scores it didn't calculate for this benchmark (e.g. Work Graphs).
        values = values[values > 0]
        if len(values):
            scores[column] = float(values.mean())
    return scores


def _per_frame(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = pd.DataFrame(
        {
            "loop": table["Loop Index"].astype(int),
            "frame": table["Frame"].astype(int),
            "seq_s": table["Benchmark Time (ns)"] / 1e9,
        }
    )
    workloads = base.copy()
    for column, name in WORKLOAD_COLUMNS.items():
        if column in table and table[column].notna().any():
            # Evolve leaves the cell empty when a workload took no time in that frame.
            workloads[name] = table[column].fillna(0) / 1e6
    sensors = base.copy()
    for column, name in METRIC_CSV_COLUMNS.items():
        sensors[name] = pd.to_numeric(table[column], errors="coerce") if column in table else float("nan")
    for name in SENSOR_COLUMNS:
        if name not in sensors:
            sensors[name] = float("nan")
    return workloads, sensors


def _read_deep_analysis(result: Result, data: bytes, filename: str) -> None:
    text = data.decode("utf-8")
    try:
        loops = json.loads(text)
    except json.JSONDecodeError:
        # Evolve only closes the array after the last loop, so an interrupted run misses the final "]".
        try:
            loops = json.loads(text.rstrip().rstrip(",") + "]")
        except json.JSONDecodeError:
            raise ExportError(f"{filename}: {DEEP_ANALYSIS} is damaged and can't be read.") from None
        result.warnings.append(f"{filename}: the run was interrupted; using the {len(loops)} completed loop(s).")
    if not isinstance(loops, list) or (loops and "per_frame_results" not in loops[0]):
        raise ExportError(f"{filename} isn't an Evolve deep analysis file.")

    passes, frames, left_out = _tabulate(loops)
    if passes.empty:
        result.warnings.append(
            f"{filename}: its deep analysis has no GPU work that Evolve assigns to a workload category."
        )
        return
    result.passes, result.frames, result.left_out = passes, frames, left_out

    nested = passes["ms"].sum() - passes["top_ms"].sum()
    if nested > 0:
        result.warnings.append(
            f"{filename}: {nested / passes['ms'].sum():.1%} of measured GPU time is nested inside other passes. "
            "Totals only count it once."
        )


def _tabulate(loops: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    # Pass name -> whether Evolve assigns it to a workload category.
    categorized: dict[str, bool] = {}
    left_out: dict[str, float] = {}
    pass_rows = []
    frame_rows = []
    for loop in loops:
        loop_index = loop["loop_index"]
        for frame_index, frame in enumerate(loop["per_frame_results"]):
            seq_s = frame["sequence_time_ns"] / 1e9
            own, top = {}, {}
            left_out_ms = 0.0
            first_start, last_end = None, None
            for command_buffer in frame["command_buffer_timings"].values():
                scopes = []
                for name, timings in command_buffer["scope_timings"].items():
                    if name not in categorized:
                        categorized[name] = bool(workloads(name))
                    for timing in timings:
                        start, end = timing["start"], timing["end"]
                        first_start = start if first_start is None else min(first_start, start)
                        last_end = end if last_end is None else max(last_end, end)
                        if not categorized[name]:
                            left_out[name] = left_out.get(name, 0.0) + (end - start) / 1e6
                            left_out_ms += (end - start) / 1e6
                        else:
                            scopes.append((start, end, name))

                # Sorted by start, longest first: a scope ending before the current outer one is nested in it.
                scopes.sort(key=lambda scope: (scope[0], -scope[1]))
                outer_end = None
                for start, end, name in scopes:
                    duration = (end - start) / 1e6
                    own[name] = own.get(name, 0.0) + duration
                    if outer_end is None or end > outer_end:
                        top[name] = top.get(name, 0.0) + duration
                        outer_end = end

            for name, ms in own.items():
                pass_rows.append((loop_index, frame_index, seq_s, name, ms, top.get(name, 0.0)))

            row = {
                "loop": loop_index,
                "frame": frame_index,
                "seq_s": seq_s,
                "gpu_sum_ms": sum(top.values()),
                "gpu_span_ms": (last_end - first_start) / 1e6 if first_start is not None else float("nan"),
                "left_out_ms": left_out_ms,
            }
            row.update(_metrics(frame.get("metrics")))
            frame_rows.append(row)

    passes = pd.DataFrame(pass_rows, columns=["loop", "frame", "seq_s", "pass", "ms", "top_ms"])

    frames = pd.DataFrame(frame_rows)
    for column in SENSOR_COLUMNS:
        if column not in frames:
            frames[column] = float("nan")
    return passes, frames, left_out


def _workloads_from_passes(passes: pd.DataFrame, frames: pd.DataFrame) -> pd.DataFrame:
    """Per-frame GPU time per workload category, the way Evolve sums it for its per-frame export."""
    membership = pd.DataFrame(
        [(name, workload) for name in passes["pass"].unique() for workload in workloads(name)],
        columns=["pass", "workload"],
    )
    if membership.empty:
        return frames[["loop", "frame", "seq_s"]].copy()
    per_workload = passes.merge(membership, on="pass").pivot_table(
        index=["loop", "frame"], columns="workload", values="ms", aggfunc="sum"
    )
    table = frames[["loop", "frame", "seq_s"]].join(per_workload, on=["loop", "frame"])
    present = [name for name in WORKLOAD_ORDER if name in table]
    return table[["loop", "frame", "seq_s", *present]].fillna({name: 0.0 for name in present})


def _metrics(metrics: dict | None) -> dict[str, float]:
    if not metrics:
        return {}
    values = {}
    for key, column in METRIC_FIELDS.items():
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            values[column] = float(value)
    fan = metrics.get("fan_speed")
    if isinstance(fan, dict):
        for unit, value in fan.items():
            if unit in FAN_FIELDS and isinstance(value, (int, float)):
                values[FAN_FIELDS[unit]] = float(value)
    return values
