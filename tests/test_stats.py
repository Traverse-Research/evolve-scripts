import pytest
from conftest import make_export, simple_frames

from evolve_charts import stats
from evolve_charts.loader import load_export


@pytest.fixture
def results():
    return {
        "Gen 1": load_export(make_export([simple_frames(2.0)], gpu="Gen 1 GPU"), "gen1.zip"),
        "Gen 2": load_export(make_export([simple_frames(1.0)], gpu="Gen 2 GPU"), "gen2.zip"),
    }


def summary_of(results, level, within=None, skip_s=1.0):
    return stats.summary(results, skip_s, level, within).set_index(["result", "item"])


def test_warm_up_is_skipped(results):
    assert summary_of(results, "pass", skip_s=0.0).at[("Gen 1", "shadow-raytrace-inline"), "mean_ms"] > 2.0
    assert summary_of(results, "pass").at[("Gen 1", "shadow-raytrace-inline"), "mean_ms"] == pytest.approx(2.0)


def test_frame_totals(results):
    totals = stats.frame_totals(results, 1.0).set_index("result")
    assert totals.at["Gen 1", "gpu_sum_ms"] == pytest.approx(2.5)
    assert totals.at["Gen 1", "left_out_ms"] == pytest.approx(0.1)


def test_workload_categories(results):
    workloads = summary_of(results, "workload")
    assert workloads.at[("Gen 2", "Raytracing"), "mean_ms"] == pytest.approx(1.0)
    assert workloads.at[("Gen 2", "Compute"), "mean_ms"] == pytest.approx(0.5)
    rows = workloads.loc["Gen 1"]
    assert rows["share_pct"].sum() == pytest.approx(100.0)


def test_passes_of_a_workload_category(results):
    passes = summary_of(results, "pass", ("workload", "Compute"))
    assert passes.index.get_level_values("item").unique().tolist() == ["shadow_filter_pass_0"]
    assert passes.at[("Gen 1", "shadow_filter_pass_0"), "workload"] == "Compute"


def test_results_without_deep_analysis_are_left_out_of_pass_views():
    results = {
        "Full": load_export(make_export([simple_frames(2.0)], gpu="Gen 1 GPU"), "a.zip"),
        "Scores only": load_export(make_export(None, gpu="Gen 2 GPU"), "b.zip"),
    }
    assert set(stats.summary(results, 1.0, "pass")["result"]) == {"Full"}
    assert set(stats.summary(results, 1.0, "workload")["result"]) == {"Full", "Scores only"}


def test_passes_missing_in_some_frames_count_as_zero(results):
    result = results["Gen 1"]
    even = (result.passes["pass"] == "shadow_filter_pass_0") & (result.passes["frame"] % 2 == 0)
    result.passes = result.passes[~even]
    row = stats.summary({"Gen 1": result}, 1.0, "pass").set_index("item").loc["shadow_filter_pass_0"]
    assert row["ran_in_pct_of_frames"] == pytest.approx(50.0, abs=5.0)
    assert row["mean_ms"] == pytest.approx(0.5 * row["ran_in_pct_of_frames"] / 100)


def test_scores_table(results):
    table = stats.scores_table(results)
    assert table.index.tolist() == ["Ray Tracing", "Rasterization", "Compute"]
    assert table.at["Compute", "Gen 2"] == 6000


def test_comparison_table_and_key_numbers(results):
    summary = stats.summary(results, 1.0, "pass")
    table = stats.comparison_table(summary, ["Gen 1", "Gen 2"], "Gen 1").set_index("item")
    assert table.at["shadow-raytrace-inline", "Gen 2"] == pytest.approx(1.0)
    assert table.at["shadow-raytrace-inline", "Gen 2 vs Gen 1"] == pytest.approx(-50.0)
    workloads = stats.summary(results, 1.0, "workload")
    assert stats.key_numbers(workloads, "Raytracing", "Gen 1") == (
        "Raytracing: 2.00 ms per frame on Gen 1, 1.00 ms on Gen 2 (50% less)."
    )


def test_timeline_averages_loops_and_smooths():
    result = load_export(make_export([simple_frames(2.0), simple_frames(4.0)]), "x.zip")
    raw = stats.timeline(result, 1.0, "pass", ["shadow-raytrace-inline"], 0.0)
    assert raw["shadow-raytrace-inline"].tolist() == pytest.approx([3.0] * len(raw))
    smooth = stats.timeline(result, 1.0, "pass", ["shadow-raytrace-inline"], 2.0)
    assert len(smooth) == len(raw)
    assert len(stats.timeline(result, 1.0, "workload", ["Raytracing"], 0.0)) > 0


def test_telemetry(results):
    summary = stats.telemetry_summary(results, 1.0)
    assert summary.at["Gen 1", "GPU power avg (W)"] == pytest.approx(200.0)
    assert "Fan speed avg (RPM)" in summary.columns


def test_wide_for_spreadsheets(results):
    wide = stats.wide_for_spreadsheets(stats.summary(results, 1.0, "pass"))
    assert list(wide.columns) == ["workload", "item", "Gen 1", "Gen 2"]
