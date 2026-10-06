import io
import zipfile

import pytest
from conftest import PER_FRAME_HEADER, combined_csv, frame, make_export, scope, simple_frames

from evolve_charts.categories import workloads
from evolve_charts.loader import ExportError, load_export


def test_full_export():
    result = load_export(make_export([simple_frames(2.0)], gpu="Gen 1 GPU"), "gen1.zip")
    assert result.gpu == "Gen 1 GPU"
    assert result.metadata["Evolve Version"] == "15.10"
    assert result.metadata["Rendering Backend"] == "Dx12"
    # A score of 0 means Evolve didn't calculate it for this benchmark.
    assert result.scores == {"Ray Tracing": 4000, "Rasterization": 5000, "Compute": 6000}
    assert result.contents == ["Scores", "Per frame", "Deep analysis"]
    assert set(result.passes["pass"]) == {"shadow-raytrace-inline", "shadow_filter_pass_0"}
    assert result.warnings == []


def test_per_frame_workloads_come_from_the_csv():
    result = load_export(make_export([simple_frames(2.0)], gpu="Gen 1 GPU"), "gen1.zip")
    frame_3 = result.workloads.set_index("frame").loc[3]
    assert frame_3["Raytracing"] == pytest.approx(2.0)
    assert frame_3["Compute"] == pytest.approx(0.5)
    assert "Rasterization" not in result.workloads  # an all-empty column


def test_export_without_deep_analysis():
    result = load_export(make_export(None, gpu="Gen 1 GPU"), "gen1.zip")
    assert result.contents == ["Scores", "Per frame"]
    assert result.passes is None
    assert result.frames["gpu_clock_mhz"].iloc[2] == 2502
    assert result.frames["board_power_w"].iloc[2] == 200.0


def test_standalone_csv_exports():
    scores = load_export(b"Loop,Ray Tracing,Compute\n1,4000,6000\n2,4200,0\n", "scores.csv")
    assert scores.scores == {"Ray Tracing": 4100, "Compute": 6000}
    assert scores.contents == ["Scores"]
    assert any("system information" in warning for warning in scores.warnings)

    per_frame = load_export(f"{PER_FRAME_HEADER}\n1,0,0,1000000,,500000,150,2600\n".encode(), "frametimes.csv")
    assert per_frame.contents == ["Per frame"]
    assert per_frame.workloads["Raytracing"].item() == pytest.approx(1.0)

    combined = load_export(combined_csv("Gen 2 GPU", 1.0).encode(), "evolve_results.csv")
    assert combined.gpu == "Gen 2 GPU"
    assert combined.contents == ["Scores", "Per frame"]


def test_standalone_deep_analysis_derives_workloads():
    data = zipfile.ZipFile(io.BytesIO(make_export([simple_frames(2.0)]))).read("deep_analysis.json")
    result = load_export(data, "deep_analysis.json")
    assert result.contents == ["Per frame", "Deep analysis"]
    frame_3 = result.workloads.set_index("frame").loc[3]
    assert frame_3["Raytracing"] == pytest.approx(2.0)
    assert frame_3["Compute"] == pytest.approx(0.5)


def test_uncategorized_scopes_are_left_out_but_counted():
    result = load_export(make_export([simple_frames(2.0)]), "x.zip")
    assert result.left_out == {"made-up-pass": pytest.approx(0.1 * 20)}
    assert result.frames["left_out_ms"].tolist() == pytest.approx([0.1] * 20, abs=1e-5)
    # The GPU frame span still covers all GPU work, including what's left out.
    assert result.frames["gpu_span_ms"].iloc[3] == pytest.approx(62.1)


def test_repeated_scopes_in_a_frame_are_summed():
    passes = load_export(make_export([simple_frames(2.0)]), "x.zip").passes
    filter_ms = passes[(passes["pass"] == "shadow_filter_pass_0") & (passes["frame"] == 3)]["ms"]
    assert filter_ms.item() == pytest.approx(0.5)


def test_nested_scopes_count_once_in_totals():
    nested = frame(0.0, [{"Build GBuffers": [scope(0, 10)], "shadow_prepare": [scope(2, 4)]}])
    result = load_export(make_export([[nested]]), "x.zip")
    passes = result.passes.set_index("pass")
    assert passes.at["shadow_prepare", "ms"] == pytest.approx(2.0)
    assert passes.at["shadow_prepare", "top_ms"] == 0.0
    assert result.frames["gpu_sum_ms"].item() == pytest.approx(10.0)
    assert any("nested" in warning for warning in result.warnings)


def test_frame_span_and_overlap_across_command_buffers():
    overlapping = frame(0.0, [{"Build GBuffers": [scope(0, 6)]}, {"shadow_prepare": [scope(4, 10)]}])
    result = load_export(make_export([[overlapping]]), "x.zip")
    assert result.frames["gpu_sum_ms"].item() == pytest.approx(12.0)
    assert result.frames["gpu_span_ms"].item() == pytest.approx(10.0)


def test_metrics_null_and_fan_units():
    frames = [
        frame(0.0, [{"Build GBuffers": [scope(0, 1)]}], None),
        frame(1.0, [{"Build GBuffers": [scope(0, 1)]}], {"fan_speed": {"Percent": 40}, "edge_temperature_in_c": 60.0}),
        frame(2.0, [{"Build GBuffers": [scope(0, 1)]}], {"fan_speed": {"Rpm": 1200}, "clock_speed_in_mhz": None}),
    ]
    result = load_export(make_export([frames]), "x.zip")
    assert result.frames["fan_pct"].tolist()[1] == 40
    assert result.frames["fan_rpm"].tolist()[2] == 1200
    assert result.frames["gpu_clock_mhz"].isna().all()


def test_interrupted_multi_loop_run_is_recovered():
    result = load_export(make_export([simple_frames(2.0, 5), simple_frames(2.0, 5)], truncated=True), "x.zip")
    assert result.frames["loop"].nunique() == 2
    assert any("interrupted" in warning for warning in result.warnings)


def test_unreadable_inputs():
    with pytest.raises(ExportError, match="not a zip"):
        load_export(b"{}", "broken.zip")
    with pytest.raises(ExportError, match="isn't an Evolve"):
        load_export(b"a,b\n1,2\n", "other.csv")
    with pytest.raises(ExportError, match="use an Evolve export"):
        load_export(b"", "picture.png")


def test_categories():
    assert workloads("shadow_filter_pass_1") == ["Compute"]
    assert workloads("DLSS evaluate") == ["Upscaling"]
    assert workloads("egui_render") == []
    assert workloads("not-in-evolve") == []
    assert workloads("shadow-raytrace-inline") == ["Raytracing"]
    assert workloads("vol-ris-initial-sampling") == ["Raytracing", "Compute"]


def test_utility_passes():
    from evolve_charts.categories import is_utility

    assert is_utility("Copy buffer to buffer")
    assert is_utility("egui_render")
    # Uncategorized by Evolve's pass bucketing, but the work of a workload category of their own.
    assert not is_utility("DLSS evaluate")
    assert not is_utility("shadow_filter_pass_0")
