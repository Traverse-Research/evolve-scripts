import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

METADATA_HEADER = "Evolve Version,System Name,CPU,GPU,OS Name,OS Version,GPU Driver Version,Rendering Backend"
SCORES_HEADER = "Ray Tracing,Rasterization,Compute,Work Graphs"
PER_FRAME_HEADER = (
    "Loop Index,Frame,Benchmark Time (ns),Ray Tracing (ns),Rasterization (ns),Compute (ns),Energy (W),Clock Speed (Mhz)"
)


def scope(start_ms: float, end_ms: float) -> dict:
    return {"start": int(start_ms * 1e6), "end": int(end_ms * 1e6)}


def frame(seq_s: float, buffers: list[dict[str, list[dict]]], metrics: dict | None = None) -> dict:
    return {
        "sequence_time_ns": int(seq_s * 1e9),
        "command_buffer_timings": {
            f"Command Buffer {index}": {"cpu_submit_time": 0, "gpu_submit_time": 0, "scope_timings": scopes}
            for index, scopes in enumerate(buffers)
        },
        "cpu_timings": {"DriverApiCall": [1000]},
        "metrics": metrics,
    }


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
                {"clock_speed_in_mhz": 2500 + index, "board_power_usage_in_w": 200.0, "fan_speed": {"Rpm": 1500}},
            )
        )
    return frames


def combined_csv(gpu: str, shadow_ms: float, count: int = 20, scores: str = "4000,5000,6000,0") -> str:
    """`evolve_results.csv`: system information, scores and per-frame workload times on every row."""
    rows = [f"{METADATA_HEADER},{SCORES_HEADER},{PER_FRAME_HEADER}"]
    for index in range(count):
        ray_tracing = int((shadow_ms + (50 if index == 0 else 0)) * 1e6)
        rows.append(
            f"15.10,host,CPU X,{gpu},Windows,11,1.2.3,Dx12,{scores},"
            f"1,{index},{int(index * 0.5e9)},{ray_tracing},,{int(0.5e6)},200.0,{2500 + index}"
        )
    return "\n".join(rows) + "\n"


def make_export(
    loops: list[list[dict]] | None,
    gpu: str = "Test GPU",
    truncated: bool = False,
    results_csv: str | None = None,
) -> bytes:
    """An Evolve Export zip; `loops=None` leaves out deep analysis like exports without Professional."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if loops is not None:
            text = json.dumps(
                [{"loop_index": index + 1, "per_frame_results": frames} for index, frames in enumerate(loops)]
            )
            archive.writestr("deep_analysis.json", text[:-1] if truncated else text)
        shadow_ms = 2.0 if "1" in gpu else 1.0
        archive.writestr("evolve_results.csv", results_csv if results_csv is not None else combined_csv(gpu, shadow_ms))
    return buffer.getvalue()


@pytest.fixture
def two_gpus(tmp_path: Path) -> Path:
    (tmp_path / "gen1.zip").write_bytes(make_export([simple_frames(2.0)], gpu="Gen 1 GPU"))
    (tmp_path / "gen2.zip").write_bytes(make_export([simple_frames(1.0)], gpu="Gen 2 GPU"))
    return tmp_path
