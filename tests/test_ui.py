from pathlib import Path

from conftest import make_export
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parent.parent / "evolve-charts.py")
PAGES = ["_scores_page", "_gpu_time_page", "_passes_page", "_sensors_page", "_export_page"]

# Analysis pages are functions given to st.navigation, which AppTest can't switch to, so a small script renders
# one the way main() does: the shared context bar first, then the page.
PAGE_SCRIPT = """
import streamlit as st
from evolve_charts import ui

results = ui._loaded_results()
st.session_state["results"] = results
st.session_state["context"] = ui._context_bar(results)
getattr(ui, "{page}")()
"""


def run(monkeypatch, folder) -> AppTest:
    monkeypatch.setenv("EVOLVE_CHARTS_EXPORTS", str(folder))
    return AppTest.from_file(ENTRY, default_timeout=60).run()


def page(monkeypatch, folder, name: str) -> AppTest:
    monkeypatch.setenv("EVOLVE_CHARTS_EXPORTS", str(folder))
    app = AppTest.from_string(PAGE_SCRIPT.format(page=name), default_timeout=60).run()
    assert not app.exception, name
    return app


def visit_every_page(monkeypatch, folder) -> None:
    for name in PAGES:
        page(monkeypatch, folder, name)


def test_results_page_without_results(tmp_path, monkeypatch):
    app = run(monkeypatch, tmp_path)
    assert not app.exception
    assert any("How to start" in markdown.value for markdown in app.markdown)


def test_every_page_renders_with_two_results(two_gpus, monkeypatch):
    app = run(monkeypatch, two_gpus)
    assert not app.exception
    assert [box.value for box in app.text_input] == ["Gen 1 GPU", "Gen 2 GPU"]
    visit_every_page(monkeypatch, two_gpus)

    app = page(monkeypatch, two_gpus, "_gpu_time_page")
    assert any("Raytracing: 2.00 ms per frame on Gen 1 GPU" in markdown.value for markdown in app.markdown)
    app.selectbox(key="workload-item").set_value("Compute").run()
    assert not app.exception
    assert any("Compute: 0.50 ms per frame on Gen 1 GPU" in markdown.value for markdown in app.markdown)


def test_results_without_deep_analysis(tmp_path, monkeypatch):
    (tmp_path / "scores_only.zip").write_bytes(make_export(None, gpu="Gen 1 GPU"))
    (tmp_path / "scores.csv").write_text("Loop,Ray Tracing,Compute\n1,4000,6000\n")
    app = run(monkeypatch, tmp_path)
    assert not app.exception
    visit_every_page(monkeypatch, tmp_path)


def test_bad_file_shows_error(tmp_path, monkeypatch):
    (tmp_path / "broken.zip").write_bytes(b"not a zip")
    app = run(monkeypatch, tmp_path)
    assert not app.exception
    assert "not a zip" in app.error[0].value
