"""Reads Evolve's `.evolve` run files into tidy pandas tables.

Evolve saves every benchmark run as a `.evolve` file (in `Documents/Evolve/results` on Windows). It's a
zip, called a datakit recording, of:

- `datakit.json`: the format and its version.
- `tables/<name>.parquet`: the measurements, one Parquet table each:
  - `frames`: per frame, the GPU time of every workload category and the driver time.
  - `gpu_scopes`: the GPU start and duration of every pass in every frame.
  - `cpu_scopes`: the duration of every driver call.
  - `metrics`: GPU sensor readings, sampled a few times per second.
  - `command_buffers`: when each command buffer was submitted.
- `documents/client_data`: JSON with the system, driver and benchmark settings.

The scores aren't in the file; they're calculated from the tables the way Evolve does (`scores.py`).
"""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from . import scores
from .categories import workloads

DATAKIT_VERSION = 1
TABLES = ["frames", "gpu_scopes", "cpu_scopes", "metrics"]

# `frames` column -> workload category name (as Evolve shows it).
WORKLOAD_COLUMNS = {
    "gpu_ray_tracing_ns": "Raytracing",
    "gpu_acceleration_structure_builds_ns": "Acceleration Structure Builds",
    "gpu_rasterization_ns": "Rasterization",
    "gpu_compute_ns": "Compute",
    "gpu_workgraphs_ns": "Workgraphs",
    "gpu_nrc_ns": "NRC",
    "gpu_upscaler_performance_ns": "Upscaling",
}

# `metrics` column -> sensor column in `Result.frames`.
METRIC_COLUMNS = {
    "gpu_usage_percent": "gpu_usage_pct",
    "gpu_clock_mhz": "gpu_clock_mhz",
    "vram_clock_mhz": "vram_clock_mhz",
    "gpu_power_w": "gpu_power_w",
    "board_power_w": "board_power_w",
    "soc_power_w": "soc_power_w",
    "voltage_mv": "voltage_mv",
    "vram_usage_mib": "vram_used_mb",
    "fan_rpm": "fan_rpm",
    "fan_percent": "fan_pct",
    "edge_temperature_c": "edge_temp_c",
    "hotspot_temperature_c": "hotspot_temp_c",
}
SENSOR_COLUMNS = list(METRIC_COLUMNS.values())


class LoadError(Exception):
    """A problem with an input file, worded for the person using the tool."""


@dataclass
class Result:
    id: str
    filename: str
    metadata: dict[str, str] = field(default_factory=dict)
    # Score name -> score. Scores the benchmark doesn't have are absent.
    scores: dict[str, float] = field(default_factory=dict)
    # One row per (loop, frame): GPU milliseconds per workload category, one column each.
    workloads: pd.DataFrame | None = None
    # One row per (loop, frame): sensor readings, and the GPU time sum and span of the passes.
    frames: pd.DataFrame | None = None
    # One row per (loop, frame, pass): ms is the pass' own GPU time in that frame; top_ms only counts
    # instances not nested inside another scope, so summing it never double-counts.
    passes: pd.DataFrame | None = None
    # Total GPU milliseconds per pass that Evolve doesn't assign to a workload category.
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
                ("Passes", self.passes is not None),
            ]
            if present
        ]


def load_recording(data: bytes, filename: str) -> Result:
    result = Result(id=hashlib.sha256(data).hexdigest()[:12], filename=filename)
    tables, client_data = _read_container(data, filename)

    run_info = client_data.get("run_info") or {}
    variant = run_info.get("variant")
    if not variant:
        raise LoadError(f"{filename} doesn't say which benchmark it ran.")
    platform = client_data.get("platform") or "Desktop"
    version = client_data.get("evolve_version")
    version = (version["major"], version["minor"]) if version else None
    result.metadata = _metadata(client_data, variant)

    frames = tables["frames"]
    gpu_scopes = tables["gpu_scopes"]
    if not len(frames):
        raise LoadError(f"{filename} has no frames; the run didn't finish.")
    result.workloads = _workloads(frames)
    metrics = tables["metrics"]
    sensors = _sensors(frames, metrics)
    result.scores = scores.calculate(
        variant,
        platform,
        version,
        len(frames),
        gpu_scopes,
        tables["cpu_scopes"]["len_ns"],
        frames["flip"],
        frames["ssim"],
        metrics,
    )

    passes, totals, left_out = _passes(gpu_scopes, frames)
    result.frames = sensors.join(totals, on="frame")
    result.frames[["gpu_sum_ms", "left_out_ms"]] = result.frames[["gpu_sum_ms", "left_out_ms"]].fillna(0.0)
    if passes.empty:
        result.warnings.append(f"{filename} has no GPU work that Evolve assigns to a workload category.")
        return result
    result.passes, result.left_out = passes, left_out

    nested = passes["ms"].sum() - passes["top_ms"].sum()
    if nested > 0:
        result.warnings.append(
            f"{filename}: {nested / passes['ms'].sum():.1%} of measured GPU time is nested inside other passes. "
            "Totals only count it once."
        )
    return result


def _read_container(data: bytes, filename: str) -> tuple[dict[str, pd.DataFrame], dict]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(archive.read("datakit.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise LoadError(
            f"{filename} isn't an Evolve run file. Use the .evolve files Evolve saves for every run."
        ) from None
    if manifest.get("format") != "datakit":
        raise LoadError(f"{filename} isn't an Evolve run file.")
    if manifest.get("version") != DATAKIT_VERSION:
        raise LoadError(f"{filename} was saved by a newer Evolve. Download the latest Evolve Charts to read it.")

    names = set(archive.namelist())
    tables = {}
    for name in TABLES:
        path = f"tables/{name}.parquet"
        if path not in names:
            raise LoadError(f"{filename} has no {name} table; it was saved by an Evolve version this tool can't read.")
        tables[name] = pq.read_table(io.BytesIO(archive.read(path))).to_pandas()
    try:
        client_data = json.loads(archive.read("documents/client_data"))
    except (KeyError, json.JSONDecodeError):
        raise LoadError(f"{filename} has no readable system information.") from None
    return tables, client_data


def _metadata(client_data: dict, variant: str) -> dict[str, str]:
    system = client_data.get("system_info") or {}
    os_info = system.get("os_info") or {}
    driver = client_data.get("driver_info") or {}
    version = client_data.get("evolve_version")
    driver_version = driver.get("version")
    metadata = {
        "Evolve Version": f"{version['major']}.{version['minor']}" if version else "",
        "Benchmark": variant,
        "System Name": system.get("host_name") or "",
        "CPU": (system.get("cpu_name") or "").strip(),
        "GPU": driver.get("device_name") or "",
        "OS Name": os_info.get("os_type") or "",
        "OS Version": _os_version(os_info.get("version")),
        "GPU Driver Version": (
            f"{driver_version['major']}.{driver_version['minor']}.{driver_version['patch']}" if driver_version else ""
        ),
        "Rendering Backend": client_data.get("rendering_backend") or "",
    }
    return {key: value for key, value in metadata.items() if value}


def _os_version(version: dict | str | None) -> str:
    """The `os_info` crate's version: {"Semantic": [10, 0, 26200]}, {"Rolling": ...}, {"Custom": ...}."""
    if isinstance(version, dict):
        for kind, value in version.items():
            if kind == "Semantic":
                return ".".join(str(part) for part in value)
            return str(value) if value else kind
    return "" if version in (None, "Unknown") else str(version)


def _base(frames: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"loop": 1, "frame": frames["frame"].astype(int), "seq_s": frames["simulation_time_ns"] / 1e9})


def _workloads(frames: pd.DataFrame) -> pd.DataFrame:
    table = _base(frames)
    for column, name in WORKLOAD_COLUMNS.items():
        if column in frames and frames[column].notna().any():
            # Empty when a workload took no time in that frame.
            table[name] = frames[column].fillna(0) / 1e6
    return table


def _sensors(frames: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Each frame gets the latest sensor sample taken at or before it, like Evolve's own exports."""
    table = _base(frames)
    sample_times = metrics["simulation_time_ns"].to_numpy(dtype=float) if len(metrics) else np.array([])
    rows = np.searchsorted(sample_times, frames["simulation_time_ns"].to_numpy(dtype=float), side="right") - 1
    valid = rows >= 0
    if len(metrics):
        valid &= ~np.isnan(sample_times[np.clip(rows, 0, None)])
    for column, name in METRIC_COLUMNS.items():
        values = np.full(len(frames), np.nan)
        if column in metrics and len(metrics):
            readings = pd.to_numeric(metrics[column], errors="coerce").to_numpy(dtype=float)
            values[valid] = readings[rows[valid]]
        table[name] = values
    return table


def _passes(gpu_scopes: pd.DataFrame, frames: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    """Per (frame, pass) GPU time, and per frame the summed and spanned GPU time and what was left out."""
    scopes = pd.DataFrame(
        {
            "frame": gpu_scopes["frame"].astype(int),
            "command_buffer": gpu_scopes["command_buffer"].astype(int),
            "pass": gpu_scopes["name"].astype(str),
            "start": gpu_scopes["start_ns"].astype("int64"),
            "len": gpu_scopes["len_ns"].astype("int64"),
        }
    )
    scopes["end"] = scopes["start"] + scopes["len"]
    categorized = {name: bool(workloads(name)) for name in scopes["pass"].unique()}
    scopes["categorized"] = scopes["pass"].map(categorized).astype(bool)

    totals = scopes.groupby("frame").agg(first_start=("start", "min"), last_end=("end", "max"))
    totals["gpu_span_ms"] = (totals["last_end"] - totals["first_start"]) / 1e6
    totals = totals[["gpu_span_ms"]]

    left = scopes[~scopes["categorized"]]
    totals["left_out_ms"] = left.groupby("frame")["len"].sum() / 1e6
    left_out = (left.groupby("pass")["len"].sum() / 1e6).to_dict()

    # Sorted by start, longest first: a scope ending no later than every earlier one in its command buffer is
    # nested inside one of them.
    kept = scopes[scopes["categorized"]]
    kept = kept.iloc[np.lexsort((-kept["end"], kept["start"], kept["command_buffer"], kept["frame"]))]
    earlier_end = kept.groupby(["frame", "command_buffer"])["end"].cummax()
    earlier_end = earlier_end.groupby([kept["frame"], kept["command_buffer"]]).shift(1)
    kept = kept.assign(ms=kept["len"] / 1e6, top_ms=np.where(earlier_end.isna() | (kept["end"] > earlier_end), 1, 0))
    kept["top_ms"] *= kept["ms"]

    passes = kept.groupby(["frame", "pass"], as_index=False, sort=True)[["ms", "top_ms"]].sum()
    totals["gpu_sum_ms"] = passes.groupby("frame")["top_ms"].sum()
    seq_s = frames.set_index("frame")["simulation_time_ns"] / 1e9
    passes.insert(0, "loop", 1)
    passes.insert(2, "seq_s", passes["frame"].map(seq_s))
    return passes[["loop", "frame", "seq_s", "pass", "ms", "top_ms"]], totals, left_out
