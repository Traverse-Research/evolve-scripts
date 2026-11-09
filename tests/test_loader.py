import io
import json
import zipfile

import pytest
from conftest import frame, make_recording, scope, simple_frames

from evolve_charts.categories import is_utility, workloads
from evolve_charts.loader import LoadError, load_recording


def test_full_recording():
    result = load_recording(make_recording(simple_frames(2.0), gpu="Gen 1 GPU"), "gen1.evolve")
    assert result.gpu == "Gen 1 GPU"
    assert result.metadata == {
        "Evolve Version": "17.0",
        "Benchmark": "RayTracingInline",
        "System Name": "host",
        "CPU": "CPU X",
        "GPU": "Gen 1 GPU",
        "OS Name": "Windows",
        "OS Version": "10.0.26200",
        "GPU Driver Version": "1.2.3",
        "Rendering Backend": "Dx12",
    }
    assert result.contents == ["Scores", "Passes"]
    assert set(result.passes["pass"]) == {"shadow-raytrace-inline", "shadow_filter_pass_0"}
    assert result.warnings == []


def test_per_frame_workloads_come_from_the_frames_table():
    result = load_recording(make_recording(simple_frames(2.0)), "x.evolve")
    frame_3 = result.workloads.set_index("frame").loc[3]
    assert frame_3["seq_s"] == pytest.approx(1.5)
    assert frame_3["Raytracing"] == pytest.approx(2.0)
    assert frame_3["Compute"] == pytest.approx(0.5)
    assert "Rasterization" not in result.workloads  # no frame has any


def test_recording_without_pass_timings():
    result = load_recording(make_recording(simple_frames(2.0), with_scopes=False), "x.evolve")
    assert result.contents == ["Scores"]
    assert result.passes is None
    assert result.frames["gpu_clock_mhz"].iloc[2] == 2502
    assert result.frames["board_power_w"].iloc[2] == 200.0


def test_uncategorized_scopes_are_left_out_but_counted():
    result = load_recording(make_recording(simple_frames(2.0)), "x.evolve")
    assert result.left_out == {"made-up-pass": pytest.approx(0.1 * 20)}
    assert result.frames["left_out_ms"].tolist() == pytest.approx([0.1] * 20, abs=1e-5)
    # The GPU frame span still covers all GPU work, including what's left out.
    assert result.frames["gpu_span_ms"].iloc[3] == pytest.approx(62.1)


def test_repeated_scopes_in_a_frame_are_summed():
    passes = load_recording(make_recording(simple_frames(2.0)), "x.evolve").passes
    filter_ms = passes[(passes["pass"] == "shadow_filter_pass_0") & (passes["frame"] == 3)]["ms"]
    assert filter_ms.item() == pytest.approx(0.5)


def test_nested_scopes_count_once_in_totals():
    nested = frame(0.0, [{"Build GBuffers": [scope(0, 10)], "shadow_prepare": [scope(2, 4)]}])
    result = load_recording(make_recording([nested]), "x.evolve")
    passes = result.passes.set_index("pass")
    assert passes.at["shadow_prepare", "ms"] == pytest.approx(2.0)
    assert passes.at["shadow_prepare", "top_ms"] == 0.0
    assert result.frames["gpu_sum_ms"].item() == pytest.approx(10.0)
    assert any("nested" in warning for warning in result.warnings)


def test_frame_span_and_overlap_across_command_buffers():
    overlapping = frame(0.0, [{"Build GBuffers": [scope(0, 6)]}, {"shadow_prepare": [scope(4, 10)]}])
    result = load_recording(make_recording([overlapping]), "x.evolve")
    assert result.frames["gpu_sum_ms"].item() == pytest.approx(12.0)
    assert result.frames["gpu_span_ms"].item() == pytest.approx(10.0)


def test_each_frame_gets_the_latest_sensor_sample():
    frames = [
        frame(0.0, [{"Build GBuffers": [scope(0, 1)]}], {"fan_percent": 40, "edge_temperature_c": 60.0}),
        frame(1.0, [{"Build GBuffers": [scope(0, 1)]}], None),
        frame(2.0, [{"Build GBuffers": [scope(0, 1)]}], {"fan_rpm": 1200, "vram_usage_mib": 4096}),
    ]
    sensors = load_recording(make_recording(frames), "x.evolve").frames
    assert sensors["fan_pct"].tolist()[:2] == [40, 40]
    assert sensors["edge_temp_c"].tolist()[1] == 60.0
    assert sensors["fan_rpm"].tolist()[2] == 1200
    assert sensors["vram_used_mb"].tolist()[2] == 4096
    assert sensors["gpu_clock_mhz"].isna().all()


def test_unreadable_inputs():
    with pytest.raises(LoadError, match="isn't an Evolve run file"):
        load_recording(b"not a zip", "broken.evolve")

    def container(manifest: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("datakit.json", json.dumps(manifest))
        return buffer.getvalue()

    with pytest.raises(LoadError, match="newer Evolve"):
        load_recording(container({"format": "datakit", "version": 2}), "future.evolve")
    with pytest.raises(LoadError, match="no frames table"):
        load_recording(container({"format": "datakit", "version": 1}), "empty.evolve")


def test_categories():
    assert workloads("shadow_filter_pass_1") == ["Compute"]
    assert workloads("DLSS evaluate") == ["Upscaling"]
    assert workloads("egui_render") == []
    assert workloads("not-in-evolve") == []
    assert workloads("shadow-raytrace-inline") == ["Raytracing"]
    assert workloads("vol-ris-initial-sampling") == ["Raytracing", "Compute"]
    # Renamed passes still count, so runs from older Evolve versions compare.
    assert workloads("channel_animation") == ["Compute"]


def test_utility_passes():
    assert is_utility("Copy buffer to buffer")
    assert is_utility("egui_render")
    # Uncategorized by Evolve's pass bucketing, but the work of a workload category of their own.
    assert not is_utility("DLSS evaluate")
    assert not is_utility("shadow_filter_pass_0")
