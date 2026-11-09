import io
import json
import sys
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evolve_charts.categories import workload_variants

# WorkloadCategory variant -> `frames` column.
FRAME_COLUMNS = {
    "RayTracing": "gpu_ray_tracing_ns",
    "AccelerationStructureBuilds": "gpu_acceleration_structure_builds_ns",
    "Rasterization": "gpu_rasterization_ns",
    "Compute": "gpu_compute_ns",
    "Workgraphs": "gpu_workgraphs_ns",
    "Nrc": "gpu_nrc_ns",
    "UpscalingPerformance": "gpu_upscaler_performance_ns",
}
METRICS_SCHEMA = {
    "simulation_time_ns": pa.uint64(),
    "sample_time_ns": pa.uint64(),
    "gpu_usage_percent": pa.float64(),
    "gpu_clock_mhz": pa.uint32(),
    "vram_clock_mhz": pa.uint32(),
    "gpu_power_w": pa.float64(),
    "board_power_w": pa.float64(),
    "gpu_energy_j": pa.float64(),
    "soc_power_w": pa.float64(),
    "soc_energy_j": pa.float64(),
    "voltage_mv": pa.uint32(),
    "vram_usage_mib": pa.uint32(),
    "fan_rpm": pa.uint32(),
    "fan_percent": pa.uint32(),
    "edge_temperature_c": pa.float64(),
    "hotspot_temperature_c": pa.float64(),
}


def scope(start_ms: float, end_ms: float) -> tuple[int, int]:
    return int(start_ms * 1e6), int(end_ms * 1e6)


def frame(
    seq_s: float,
    buffers: list[dict[str, list[tuple[int, int]]]],
    metrics: dict | None = None,
    driver_ns: int = 1000,
    flip: float | None = None,
    ssim: float | None = None,
) -> dict:
    """One frame: per command buffer, the scopes of every pass; and the sensor sample taken at this frame."""
    return {"seq_s": seq_s, "buffers": buffers, "metrics": metrics, "driver_ns": driver_ns, "flip": flip, "ssim": ssim}


def simple_frames(shadow_ms: float, count: int = 20) -> list[dict]:
    """Frames 0.5 s apart; frame 0 is a slow warm-up frame.

    Per frame: shadow ray tracing (Raytracing workload), 2 × 0.25 ms of shadow filtering (Compute workload)
    and 0.1 ms of work Evolve doesn't assign to a workload category.
    """
    frames = []
    for index in range(count):
        base = index * 100.0
        extra = 50.0 if index == 0 else 0.0
        frames.append(
            frame(
                index * 0.5,
                [
                    {
                        "shadow-raytrace-inline": [scope(base, base + shadow_ms + extra)],
                        "shadow_filter_pass_0": [scope(base + 60, base + 60.25), scope(base + 61, base + 61.25)],
                        "made-up-pass": [scope(base + 62, base + 62.1)],
                    }
                ],
                {"gpu_clock_mhz": 2500 + index, "board_power_w": 200.0, "fan_rpm": 1500},
            )
        )
    return frames


def _parquet(columns: dict[str, pa.Array]) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(pa.table(columns), buffer)
    return buffer.getvalue()


def make_recording(
    frames: list[dict],
    gpu: str = "Test GPU",
    variant: str = "RayTracingInline",
    platform: str = "Desktop",
    version: tuple[int, int] = (17, 0),
    with_scopes: bool = True,
) -> bytes:
    """A `.evolve` file the way Evolve writes it: per-frame workload times summed from the scopes, like Evolve."""
    workload_ns = {column: [] for column in FRAME_COLUMNS.values()}
    scope_rows = {"frame": [], "command_buffer": [], "name": [], "start_ns": [], "len_ns": []}
    metric_rows = {name: [] for name in METRICS_SCHEMA}
    for index, spec in enumerate(frames):
        totals = dict.fromkeys(FRAME_COLUMNS.values(), 0)
        for buffer, scopes in enumerate(spec["buffers"]):
            for name, timings in scopes.items():
                for start, end in timings:
                    for workload in workload_variants(name):
                        if workload in FRAME_COLUMNS:
                            totals[FRAME_COLUMNS[workload]] += end - start
                    if with_scopes:
                        for key, value in zip(scope_rows, [index, buffer, name, start, end - start]):
                            scope_rows[key].append(value)
        for column, total in totals.items():
            workload_ns[column].append(total or None)
        if spec["metrics"] is not None:
            sample = {"simulation_time_ns": int(spec["seq_s"] * 1e9), "sample_time_ns": int(spec["seq_s"] * 1e9)}
            sample.update(spec["metrics"])
            for name in METRICS_SCHEMA:
                metric_rows[name].append(sample.get(name))

    seq_ns = [int(spec["seq_s"] * 1e9) for spec in frames]
    tables = {
        "frames": {
            "frame": pa.array(range(len(frames)), pa.uint32()),
            "simulation_time_ns": pa.array(seq_ns, pa.uint64()),
            **{column: pa.array(values, pa.uint64()) for column, values in workload_ns.items()},
            "cpu_driver_ns": pa.array([spec["driver_ns"] for spec in frames], pa.uint64()),
            "flip": pa.array([spec["flip"] for spec in frames], pa.float32()),
            "ssim": pa.array([spec["ssim"] for spec in frames], pa.float32()),
        },
        "metrics": {name: pa.array(values, METRICS_SCHEMA[name]) for name, values in metric_rows.items()},
        "gpu_scopes": {
            "frame": pa.array(scope_rows["frame"], pa.uint32()),
            "command_buffer": pa.array(scope_rows["command_buffer"], pa.uint8()),
            "name": pa.array(scope_rows["name"], pa.string()).dictionary_encode(),
            "start_ns": pa.array(scope_rows["start_ns"], pa.uint64()),
            "len_ns": pa.array(scope_rows["len_ns"], pa.uint64()),
        },
        "cpu_scopes": {
            "frame": pa.array(range(len(frames)), pa.uint32()),
            "thread": pa.array(["main"] * len(frames)).dictionary_encode(),
            "name": pa.array(["ExecuteCommandLists"] * len(frames)).dictionary_encode(),
            "start_ns": pa.array(seq_ns, pa.int64()),
            "len_ns": pa.array([spec["driver_ns"] for spec in frames], pa.uint64()),
        },
    }
    client_data = {
        "evolve_version": {"major": version[0], "minor": version[1]},
        "run_info": {"variant": variant},
        "platform": platform,
        "rendering_backend": "Dx12",
        "driver_info": {"device_name": gpu, "version": {"major": 1, "minor": 2, "patch": 3}},
        "system_info": {
            "host_name": "host",
            "cpu_name": "CPU X  ",
            "os_info": {"os_type": "Windows", "version": {"Semantic": [10, 0, 26200]}},
        },
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("datakit.json", json.dumps({"format": "datakit", "version": 1}))
        for name, columns in tables.items():
            archive.writestr(f"tables/{name}.parquet", _parquet(columns))
        archive.writestr("documents/client_data", json.dumps(client_data))
    return buffer.getvalue()


@pytest.fixture
def two_gpus(tmp_path: Path) -> Path:
    (tmp_path / "gen1.evolve").write_bytes(make_recording(simple_frames(2.0), gpu="Gen 1 GPU"))
    (tmp_path / "gen2.evolve").write_bytes(make_recording(simple_frames(1.0), gpu="Gen 2 GPU"))
    return tmp_path
