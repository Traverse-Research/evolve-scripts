"""The Streamlit app: a page per question, with loaded results kept for the whole session.

Started by `evolve-charts.py`. Pages:

- Results: load and name exports, see what each contains and how Evolve's measurements relate.
- Scores, GPU time, Passes, GPU sensors: the analysis, with the loaded results and the
  "compare against" choice in a bar at the top.
- Export: CSV files for spreadsheets and newsroom chart tools.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from . import charts, stats
from .categories import WORKLOAD_DESCRIPTIONS, WORKLOAD_ORDER, is_utility, workloads
from .loader import ExportError, Result, load_export

APP_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "static"
# Written into the download by tools/package.py; a git checkout has none.
VERSION_FILE = APP_DIR / "VERSION"
# The first second includes one-off work like building the scene's ray tracing structures.
WARM_UP_S = 1.0
SMOOTHING_S = 1.0
CARDS_PER_ROW = 4
DEFAULT_WORKLOAD = "Raytracing"
TOP_PASSES = 15

# The workload category each score is the score of; the last few score something other than GPU work.
SCORE_WORKLOADS = {
    "Ray Tracing": "Raytracing",
    "Acceleration Structure": "Acceleration Structure Builds",
    "Rasterization": "Rasterization",
    "Compute": "Compute",
    "Work Graphs": "Workgraphs",
    "NRC": "NRC",
    "Upscaler Performance": "Upscaling",
    "Driver": "Not GPU work: CPU time in the graphics driver",
    "Energy Consumption": "Not GPU work: power use",
    "Image Quality 1": "Not GPU work: upscaled image quality (FLIP)",
    "Image Quality 2": "Not GPU work: upscaled image quality (SSIM)",
}

CSS = """
<style>
/* Evolve's white frames (`ui/styling.rs`, `white_frame`): charts sit on rounded white cards. */
[data-testid="stPlotlyChart"] {
    background: #FFFFFF;
    border-radius: 15px;
    padding: 14px 10px 6px 10px;
}
.block-container { padding-top: 4.5rem; max-width: 1400px; }
.result-swatch { height: 6px; border-radius: 3px; margin-bottom: 0.4rem; }
.result-meta { font-size: 0.85rem; line-height: 1.5; opacity: 0.85; }
.result-meta b { opacity: 1; }
.contents { font-size: 0.8rem; margin-top: 0.4rem; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; align-items: center; font-size: 0.9rem; }
.chip { display: inline-flex; align-items: center; gap: 0.4rem; white-space: nowrap; }
.dot { width: 0.7rem; height: 0.7rem; border-radius: 50%; display: inline-block; }
.lead { font-size: 1.05rem; opacity: 0.85; margin: -0.5rem 0 1rem 0; }
.quote {
    border-left: 4px solid #FD663A;
    background: #0F3F1D;
    padding: 0.8rem 1rem;
    border-radius: 4px;
    font-size: 1.05rem;
    margin-bottom: 1rem;
}
/* The "how Evolve measures" diagram on the Results page. */
.concepts {
    display: grid;
    grid-template-columns: 1fr auto 2fr;
    gap: 0.6rem;
    align-items: stretch;
}
.concept { border: 1px solid #3E703C; border-radius: 8px; padding: 0.7rem 0.9rem; background: #0F3F1D; }
.concept b { color: #FD663A; }
.concept small { opacity: 0.8; display: block; margin-top: 0.2rem; line-height: 1.4; }
.arrow { font-size: 1.4rem; opacity: 0.7; align-self: center; }
</style>
"""

CONCEPTS = """
<div class="concepts">
  <div class="concept"><b>Passes</b><small>Single blocks of GPU work, timed every frame.
    For example <i>shadow-raytrace-inline</i>.</small></div>
  <div class="arrow">→</div>
  <div class="concept"><b>Workload categories = scores</b><small>GPU work that logically belongs together, and
    what Evolve scores. All ray tracing work, such as <i>shadow-raytrace-inline</i>, is the Raytracing workload:
    the Ray Tracing score. Higher is better; there is no total score.</small></div>
</div>
"""

HOW_IT_WORKS = f"""
**Per frame.** A pass' time is the sum of all its executions in a frame; frames where it didn't run count as
0. Averages cover every frame of every loop; the first {WARM_UP_S:g} s are skipped because they contain
one-off setup work. Lines over time are smoothed over {SMOOTHING_S:g} s.

**Left out.** Passes Evolve doesn't assign to a workload category (copies, clears, the user interface, …)
and idle time between passes.

**Compare fairly.** Only compare runs of the same benchmark and Evolve version.
"""


@dataclass
class Context:
    results: dict[str, Result]
    labels: list[str]
    colors: dict[str, str]
    baseline: str
    image_format: str
    note: str | None


def main() -> None:
    st.set_page_config(page_title="Evolve Charts", page_icon=str(STATIC_DIR / "evolve-icon.png"), layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.logo(str(STATIC_DIR / "evolve-logo.png"), size="large")

    results = _loaded_results()
    st.session_state["results"] = results
    analysis = [
        st.Page(_scores_page, title="Scores", icon=":material/leaderboard:", url_path="scores"),
        st.Page(_gpu_time_page, title="GPU time", icon=":material/stacked_bar_chart:", url_path="gpu-time"),
        st.Page(_passes_page, title="Passes", icon=":material/list:", url_path="passes"),
        st.Page(_sensors_page, title="GPU sensors", icon=":material/thermostat:", url_path="sensors"),
        st.Page(_export_page, title="Export", icon=":material/download:", url_path="export"),
    ]
    results_page = st.Page(_results_page, title="Results", icon=":material/folder_open:", default=True)
    page = st.navigation([results_page, *analysis] if results else [results_page], position="top")

    if page.title != "Results":
        st.session_state["context"] = _context_bar(results)
    page.run()


# Loading ---------------------------------------------------------------------------------------------


@st.cache_data(show_spinner=False, max_entries=32)
def _load_file(path: str, modified: float) -> Result:
    return load_export(Path(path).read_bytes(), Path(path).name)


def _exports_dir() -> Path:
    return Path(os.environ.get("EVOLVE_CHARTS_EXPORTS", Path(__file__).resolve().parent.parent / "exports"))


def _store() -> dict:
    """Session state: uploaded results, load errors, removed results and names, kept across pages."""
    for key, value in [("uploaded", {}), ("errors", {}), ("removed", set()), ("labels", {}), ("upload_key", 0)]:
        st.session_state.setdefault(key, value)
    return st.session_state


def _on_upload() -> None:
    store = _store()
    for upload in st.session_state.get(f"uploader-{store['upload_key']}") or []:
        try:
            with st.spinner(f"Reading {upload.name}…"):
                result = load_export(upload.getvalue(), upload.name)
        except ExportError as error:
            store["errors"][upload.name] = str(error)
            continue
        store["errors"].pop(upload.name, None)
        store["uploaded"][result.id] = result
        store["removed"].discard(result.id)
    # A fresh uploader: the files now live on as result cards.
    store["upload_key"] += 1


def _loaded_results() -> dict[str, Result]:
    store = _store()
    loaded: list[Result] = []
    folder = _exports_dir()
    paths = sorted(folder.iterdir()) if folder.is_dir() else []
    for path in paths:
        if path.suffix.lower() not in {".zip", ".csv", ".json"}:
            continue
        try:
            with st.spinner(f"Reading {path.name}…"):
                loaded.append(_load_file(str(path), path.stat().st_mtime))
            store["errors"].pop(path.name, None)
        except ExportError as error:
            store["errors"][path.name] = str(error)
    loaded += store["uploaded"].values()

    results: dict[str, Result] = {}
    seen = set()
    for result in loaded:
        if result.id in seen or result.id in store["removed"]:
            continue
        seen.add(result.id)
        label = store["labels"].get(result.id) or _default_label(result, loaded)
        while label in results:
            label += " (2)"
        results[label] = result
    return results


def _default_label(result: Result, loaded: list[Result]) -> str:
    """The GPU name; when several results share a GPU, what tells their file names apart instead."""
    if sum(other.gpu == result.gpu for other in loaded) == 1:
        return result.gpu
    # "evolve_results_20261006_140239_ray-tracing-inline" -> "Ray tracing inline"
    stem = re.sub(r"^evolve_results_\d{8}_\d{6}_?", "", Path(result.filename).stem)
    return stem.replace("-", " ").replace("_", " ").strip().capitalize() or Path(result.filename).stem


# Shared page parts -----------------------------------------------------------------------------------


def _context_bar(results: dict[str, Result]) -> Context:
    """The loaded results, what to compare against and chart download settings, above every analysis page."""
    labels = list(results)
    colors = charts.result_colors(labels)
    chips, baseline_column, downloads, about = st.columns([4, 3, 1, 1], vertical_alignment="center")
    chips.markdown(
        '<div class="chips">'
        + "".join(
            f'<span class="chip"><span class="dot" style="background:{colors[label]}"></span>{label}</span>'
            for label in labels
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    baseline = baseline_column.selectbox(
        "Compare against",
        labels,
        key="baseline",
        format_func=lambda label: f"Compare against: {label}",
        label_visibility="collapsed",
        help="Differences are calculated relative to this result.",
    )
    with downloads.popover("Charts", icon=":material/download:", width="stretch"):
        st.caption("Hover over a chart and click 📷 in its top-right corner to download it.")
        image_format = st.radio("Format", ["png", "svg"], horizontal=True, format_func=str.upper, key="format")
        show_note = st.toggle("Source line on charts", value=True, key="note", help="GPUs, drivers, Evolve version")
    with about.popover("Help", icon=":material/help:", width="stretch"):
        st.markdown(CONCEPTS, unsafe_allow_html=True)
        st.markdown(HOW_IT_WORKS)
        st.caption(_version())
    st.divider()
    return Context(results, labels, colors, baseline, image_format, _source_note(results) if show_note else None)


def _context() -> Context:
    return st.session_state["context"]


def _title(title: str, lead: str) -> None:
    st.markdown(f"## {title}")
    st.markdown(f'<p class="lead">{lead}</p>', unsafe_allow_html=True)


def _source_note(results: dict[str, Result]) -> str:
    versions = sorted({result.metadata.get("Evolve Version", "?") for result in results.values()})
    # Results measured on the same system share one line, so the note stays short.
    systems: dict[str, list[str]] = {}
    for label, result in results.items():
        driver = result.metadata.get("GPU Driver Version")
        os_name = " ".join(filter(None, [result.metadata.get("OS Name"), result.metadata.get("OS Version")]))
        details = ", ".join(filter(None, [result.gpu, f"driver {driver}" if driver else "", os_name]))
        systems.setdefault(details, []).append(label)
    lines = [f"Source: Evolve {', '.join(versions)} · first {WARM_UP_S:g} s skipped · mean per frame"]
    if len(systems) == 1:
        lines.append(f"All results: {next(iter(systems))}")
    else:
        lines += [f"{', '.join(labels)}: {details}" for details, labels in systems.items()]
    return "<br>".join(lines)


def _show(fig, name: str, title: str, subtitle: str, height: int, note: str | None = ...) -> None:
    context = _context()
    note = context.note if note is ... else note
    if note:
        height += 20 * note.count("<br>")
    charts.style(fig, title, subtitle, note, height)
    st.plotly_chart(
        fig, theme=None, key=name, config=charts.download_config(_slug(title), context.image_format, height)
    )


def _missing(present: set[str], what: str) -> bool:
    """Says which results this page leaves out; True when none are left."""
    missing = [label for label in _context().labels if label not in present]
    if len(missing) == len(_context().labels):
        st.info(f"None of the loaded results contain {what}. See the Results page for what each file contains.")
        return True
    if missing:
        st.caption(f"Not included, because their exports contain no {what}: {', '.join(missing)}.")
    return False


def _comparison_columns(table: pd.DataFrame, labels: list[str], item_name: str) -> dict:
    config = {"item": st.column_config.TextColumn(item_name)}
    differences = tuple(f" vs {label}" for label in labels)
    for column in table.columns:
        if column in labels:
            config[column] = st.column_config.NumberColumn(column, format="%.2f ms")
        elif column.endswith(differences):
            other, baseline = column.split(" vs ", 1)
            config[column] = st.column_config.NumberColumn(
                f"Δ {other}", format="%+.0f%%", help=f"Difference from {baseline}"
            )
    return config


def _version() -> str:
    version = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "development version"
    return f"Evolve Charts {version} · https://github.com/Traverse-Research/evolve-scripts"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "chart"


# Results ---------------------------------------------------------------------------------------------


def _results_page() -> None:
    store = _store()
    results = st.session_state["results"]
    _title(
        "Results",
        "Load Evolve exports to compare them. Everything stays on this computer.",
    )

    columns = st.columns(CARDS_PER_ROW)
    with columns[0].container(border=True, height="stretch"):
        st.file_uploader(
            "**Add Evolve exports**",
            type=["zip", "csv", "json"],
            accept_multiple_files=True,
            key=f"uploader-{store['upload_key']}",
            on_change=_on_upload,
            help="The .zip from Export on Evolve's score screen, or the CSV and JSON files Evolve's command line "
            "exports. Files in the `exports` folder next to this tool load automatically.",
        )
    for error in store["errors"].values():
        st.error(error)

    if not results:
        columns[1].markdown(
            """
**How to start**

1. In Evolve, finish a benchmark and click **Export** on the score screen.
2. Repeat on every GPU or setting you want to compare, with the same benchmark.
3. Drop the files in the box on the left.
"""
        )
    colors = charts.result_colors(list(results))
    for index, (label, result) in enumerate(results.items()):
        slot = index + 1
        if slot % CARDS_PER_ROW == 0:
            columns = st.columns(CARDS_PER_ROW)
        with columns[slot % CARDS_PER_ROW].container(border=True, height="stretch"):
            _result_card(result, label, colors[label])

    if results:
        problems = []
        for key, what in [("Evolve Version", "Evolve versions"), ("Rendering Backend", "graphics APIs")]:
            values = {result.metadata.get(key, "unknown") for result in results.values()}
            if len(values) > 1:
                problems.append(f"different {what} ({', '.join(sorted(values))})")
        if problems:
            st.warning(f"These results use {' and '.join(problems)}. Render passes may differ; compare with care.")
        for result in results.values():
            for warning in result.warnings:
                st.info(warning)

    st.markdown("### How Evolve measures a GPU")
    st.markdown(CONCEPTS, unsafe_allow_html=True)
    st.write("")
    st.caption(_version())


def _result_card(result: Result, label: str, color: str) -> None:
    store = _store()
    st.markdown(f'<div class="result-swatch" style="background:{color}"></div>', unsafe_allow_html=True)
    name = st.text_input(
        "Name",
        value=label,
        key=f"label-{result.id}",
        label_visibility="collapsed",
        help="This name appears in every chart.",
    )
    if name.strip() and name.strip() != label:
        store["labels"][result.id] = name.strip()
        st.rerun()

    meta = result.metadata
    version = f"Evolve {meta['Evolve Version']}" if meta.get("Evolve Version") else ""
    driver = f"Driver {meta['GPU Driver Version']}" if meta.get("GPU Driver Version") else ""
    os_name = " ".join(filter(None, [meta.get("OS Name"), meta.get("OS Version")]))
    lines = [
        f"<b>{meta.get('GPU', 'Unknown GPU')}</b>",
        " · ".join(filter(None, [meta.get("Rendering Backend"), version])),
        " · ".join(filter(None, [driver, os_name])),
    ]
    per_frame = result.frames if result.frames is not None else result.workloads
    if per_frame is not None:
        frames = per_frame[per_frame["seq_s"] >= WARM_UP_S]
        duration = frames["seq_s"].max() - frames["seq_s"].min() if len(frames) else 0
        lines.append(f"{len(frames):,} frames · {duration // 60:.0f}:{duration % 60:02.0f} min")
    contents = "<br>".join(
        f"{'✓' if name in result.contents else '✗'} {name}" for name in ["Scores", "Per frame", "Deep analysis"]
    )
    body = "<br>".join(line for line in lines if line)
    st.markdown(f'<div class="result-meta">{body}<div class="contents">{contents}</div></div>', unsafe_allow_html=True)
    st.caption(result.filename)
    if st.button("Remove", key=f"remove-{result.id}", icon=":material/close:", type="tertiary"):
        store["removed"].add(result.id)
        st.rerun()


# Scores ----------------------------------------------------------------------------------------------


def _scores_page() -> None:
    context = _context()
    _title(
        "Scores",
        "Evolve scores each workload category: GPU work that logically belongs together, such as all ray tracing. "
        "Higher is better; there is no total score.",
    )
    table = stats.scores_table(context.results)
    if _missing(set(table.columns), "scores"):
        return
    # Scores are calculated by Evolve over the whole run, so the warm-up note doesn't apply.
    note = context.note and context.note.replace(f" · first {WARM_UP_S:g} s skipped · mean per frame", "")
    _show(
        charts.score_bars(table, context.colors),
        "scores",
        "Evolve scores",
        "Higher is better",
        charts.bars_height(len(table), len(table.columns)),
        note=note,
    )

    display = table.copy()
    baseline = context.baseline
    if baseline in table:
        for label in table.columns:
            if label != baseline:
                display[f"Δ {label}"] = 100 * (table[label] - table[baseline]) / table[baseline]
    display.insert(0, "Workload category", [SCORE_WORKLOADS.get(name, "") for name in display.index])
    config = {label: st.column_config.NumberColumn(label, format="%.0f") for label in table.columns}
    config |= {
        column: st.column_config.NumberColumn(column, format="%+.0f%%", help=f"Difference from {baseline}")
        for column in display.columns
        if column.startswith("Δ ")
    }
    st.dataframe(display.rename_axis("Score"), column_config=config, placeholder="–")
    st.caption("Open GPU time to see where each workload's GPU time goes over the run, and which passes it's made of.")


# GPU time --------------------------------------------------------------------------------------------


def _gpu_time_page() -> None:
    context = _context()
    _title(
        "GPU time",
        "GPU time per frame of each workload category: the GPU work Evolve scores, such as all ray tracing. "
        "Each workload category is made of passes.",
    )
    summary = stats.summary(context.results, WARM_UP_S, "workload")
    if _missing(set(summary["result"]), "per-frame data"):
        return
    present = [item for item in WORKLOAD_ORDER if summary.loc[summary["item"] == item, "mean_ms"].sum() > 0]

    overview, detail = st.tabs(["All workload categories", "One workload category"])
    with overview:
        unit = st.segmented_control(
            "Unit",
            ["ms per frame", "% of GPU time"],
            default="ms per frame",
            required=True,
            key="workload-unit",
            label_visibility="collapsed",
        )
        fig = charts.breakdown(
            summary,
            context.labels,
            unit != "ms per frame",
            WORKLOAD_ORDER,
            charts.WORKLOAD_STYLES,
            WORKLOAD_DESCRIPTIONS,
        )
        _show(
            fig,
            "workload-breakdown",
            "Where does the GPU time go?",
            "Average GPU time per frame, by workload category",
            max(240 + 70 * len(set(summary["result"])), 200 + 26 * len(fig.data)),
        )
        table = stats.comparison_table(summary, context.labels, context.baseline)
        table = table.set_index("item").reindex(present).drop(columns="workload").reset_index()
        st.dataframe(
            table,
            hide_index=True,
            column_config=_comparison_columns(table, context.labels, "Workload category"),
            placeholder="–",
        )

    with detail:
        item = st.selectbox(
            "Workload category",
            present,
            index=present.index(DEFAULT_WORKLOAD) if DEFAULT_WORKLOAD in present else 0,
            key="workload-item",
        )
        st.caption(WORKLOAD_DESCRIPTIONS.get(item, ""))
        sentence = stats.key_numbers(summary, item, context.baseline)
        if sentence:
            st.markdown(f'<div class="quote">{sentence}</div>', unsafe_allow_html=True)

        with_item = set(summary.loc[(summary["item"] == item) & (summary["mean_ms"] > 0), "result"])
        series = {
            label: stats.timeline(result, WARM_UP_S, "workload", [item], SMOOTHING_S)[item]
            for label, result in context.results.items()
            # A run without this workload category gets no line rather than a flat zero.
            if label in with_item
        }
        _show(
            charts.lines(series, context.colors, "GPU time (ms)", "ms"),
            "workload-timeline",
            f"{item} over the run",
            f"GPU time per frame, smoothed over {SMOOTHING_S:g} s",
            420,
        )

        # The passes this workload category is made of.
        inside = stats.summary(context.results, WARM_UP_S, "pass", within=("workload", item))
        inside = inside[inside["mean_ms"] > 0]
        if inside.empty:
            st.caption("Load exports with deep analysis to see the passes this workload category is made of.")
            return
        ranked = inside.groupby("item")["mean_ms"].max().sort_values(ascending=False)
        items = ranked.index[:TOP_PASSES].tolist()
        shown = inside[inside["item"].isin(items)]
        _show(
            charts.bars(shown, context.labels, context.colors, items),
            "workload-passes",
            f"{item}: passes",
            "Average GPU time per frame · whiskers: 5th to 95th percentile of frames",
            # Size by how many results share a row: inline and pipeline runs have differently named passes.
            charts.bars_height(len(items), shown.groupby("item")["result"].nunique().max()),
        )
        if len(ranked) > TOP_PASSES:
            st.caption(f"The {TOP_PASSES} largest of {len(ranked)} passes. The Passes page lists them all.")
        left_out = stats.frame_totals(context.results, WARM_UP_S)["left_out_ms"]
        if len(left_out):
            st.caption(
                f"Passes Evolve doesn't assign to any workload category (copies, clears, the user interface, …) "
                f"are left out: {left_out.min():.1f}–{left_out.max():.1f} ms per frame."
            )


# Passes ----------------------------------------------------------------------------------------------


def _passes_page() -> None:
    context = _context()
    _title("Passes", "Single blocks of GPU work, named as in Evolve. Tick passes to follow them over the run.")
    summary = stats.summary(context.results, WARM_UP_S, "pass")
    if _missing(set(summary["result"]), "deep analysis"):
        return
    labels = [label for label in context.labels if label in set(summary["result"])]
    baseline = context.baseline if context.baseline in labels else labels[0]
    if baseline != context.baseline:
        st.caption(f"Compared against {baseline}: {context.baseline} has no deep analysis.")
    table = stats.comparison_table(summary, labels, baseline)
    # Copies, clears and other support work still count towards their workload category, but aren't listed.
    utility = table["item"].map(is_utility)
    table = table[~utility].reset_index(drop=True)
    others = [label for label in labels if label != baseline]

    search, sort = st.columns([3, 2], vertical_alignment="bottom")
    query = search.text_input(
        "Search", placeholder="Search passes or categories, e.g. shadow", label_visibility="collapsed"
    )
    sort_options = ["Biggest difference", "Most GPU time"] if others else ["Most GPU time"]
    order = sort.segmented_control(
        "Sort by", sort_options, default=sort_options[0], required=True, key="passes-sort", label_visibility="collapsed"
    )
    if query:
        text = table["item"] + " " + table["workload"]
        table = table[text.str.contains(query, case=False, regex=False)]
    if order == "Biggest difference":
        # Rank by absolute time: a 300% change on a 0.01 ms pass matters less than 20% on a 2 ms pass.
        rank = table[others].sub(table[baseline], axis=0).abs().max(axis=1)
    else:
        rank = table[labels].max(axis=1)
    table = table.assign(_rank=rank).sort_values("_rank", ascending=False).drop(columns="_rank").reset_index(drop=True)

    event = st.dataframe(
        table,
        hide_index=True,
        height=360,
        column_config=_comparison_columns(table, labels, "Pass")
        | {
            "workload": st.column_config.TextColumn("Workload category"),
        },
        placeholder="–",
        on_select="rerun",
        selection_mode="multi-row",
        selection_default={"selection": {"rows": [0]}} if len(table) else None,
        key=f"passes-table-{query}-{order}-{baseline}",
    )
    picked = table.iloc[event.selection.rows]["item"].tolist() if len(table) else []
    if not picked:
        st.info("Tick at least one pass in the table.")
        return

    combine = len(picked) > 1 and st.toggle("Add the selected passes together", key="passes-combine")
    to_draw = [(" + ".join(picked), picked)] if combine else [(item, [item]) for item in picked]
    for index, (name, items) in enumerate(to_draw):
        series = {
            label: stats.timeline(result, WARM_UP_S, "pass", items, SMOOTHING_S).sum(axis=1)
            for label, result in context.results.items()
            if result.passes is not None and result.passes["pass"].isin(items).any()
        }
        _show(
            charts.lines(series, context.colors, "GPU time (ms)", "ms"),
            f"passes-timeline-{index}",
            name if len(name) < 80 else f"{len(items)} passes added together",
            f"GPU time per frame over the run, smoothed over {SMOOTHING_S:g} s",
            440,
        )


# GPU sensors -----------------------------------------------------------------------------------------


def _sensors_page() -> None:
    context = _context()
    _title("GPU sensors", "Clocks, power and temperature during the run. Falling clocks can mean throttling.")
    timelines = {
        label: stats.telemetry_timeline(result, WARM_UP_S, SMOOTHING_S)
        for label, result in context.results.items()
        if result.frames is not None
    }
    if _missing({label for label, timeline in timelines.items() if len(timeline.columns)}, "GPU sensor data"):
        return
    available = [column for column in stats.TELEMETRY if any(column in timeline for timeline in timelines.values())]
    names = {column: f"{stats.TELEMETRY[column][0]} ({stats.TELEMETRY[column][1]})" for column in available}
    column = st.pills(
        "Sensor",
        available,
        default=available[0],
        required=True,
        format_func=names.get,
        key="sensor",
        label_visibility="collapsed",
    )
    name, unit = stats.TELEMETRY[column]
    series = {label: timeline[column] for label, timeline in timelines.items() if column in timeline}
    _show(
        charts.lines(series, context.colors, f"{name} ({unit})", unit, from_zero=False),
        f"telemetry-{column}",
        f"{name} during the run",
        f"Smoothed over {SMOOTHING_S:g} s",
        460,
    )
    with st.expander("All sensors: averages and maximums"):
        summary = stats.telemetry_summary(context.results, WARM_UP_S)
        summary = summary.reindex([label for label in context.labels if label in timelines])
        st.dataframe(summary.T.style.format("{:.1f}", na_rep="–"))


# Export ----------------------------------------------------------------------------------------------


def _export_page() -> None:
    results = _context().results
    _title(
        "Export",
        "CSV files for Excel, Google Sheets, Datawrapper or Flourish. Numbers use a dot as decimal separator; "
        "in Dutch or German Excel import them with Data › From Text/CSV.",
    )
    # Each table is only built when its button is clicked; the per-frame one is tens of megabytes.
    downloads = [
        (
            "Scores",
            "One row per score, one column per result.",
            lambda: stats.scores_table(results).rename_axis("score").reset_index(),
            "scores.csv",
        ),
        (
            "Workload categories",
            "Average ms per frame per workload category, one column per result.",
            lambda: stats.wide_for_spreadsheets(stats.summary(results, WARM_UP_S, "workload")).drop(columns="workload"),
            "workload_categories.csv",
        ),
        (
            "Passes",
            "Mean, median and percentiles for every pass and result.",
            lambda: stats.summary(results, WARM_UP_S, "pass").rename(columns={"item": "pass"}),
            "passes.csv",
        ),
        (
            "Every frame",
            "GPU time of every pass in every frame. Large.",
            lambda: _per_frame_long(results, WARM_UP_S),
            "passes_per_frame.csv",
        ),
    ]
    columns = st.columns(3)
    for index, (title, description, table, filename) in enumerate(downloads):
        with columns[index % 3].container(border=True, height="stretch"):
            st.markdown(f"**{title}**")
            st.caption(description)
            st.download_button(
                "Download CSV",
                lambda table=table: table().to_csv(index=False, float_format="%.4f").encode("utf-8-sig"),
                file_name=filename,
                mime="text/csv",
                key=f"download-{index}",
                on_click="ignore",
                icon=":material/download:",
                type="primary",
            )

    left_out = pd.DataFrame(
        {label: _left_out_per_frame(result) for label, result in results.items() if result.left_out}
    )
    if not left_out.empty:
        with st.expander("Passes left out because Evolve doesn't assign them to a workload category"):
            st.dataframe(
                left_out.sort_values(left_out.columns[0], ascending=False).style.format("{:.3f} ms", na_rep="–")
            )


def _left_out_per_frame(result: Result) -> pd.Series:
    # Only totals over the whole run are kept for left-out passes, so this average includes the warm-up.
    frames = len(result.frames)
    return pd.Series({name: total / frames for name, total in result.left_out.items()}, dtype=float)


def _per_frame_long(results: dict[str, Result], skip_s: float) -> pd.DataFrame:
    frames = []
    for label, result in results.items():
        if result.passes is None:
            continue
        passes = result.passes[result.passes["seq_s"] >= skip_s]
        frames.append(
            passes.assign(result=label, workload=passes["pass"].map(lambda scope: ", ".join(workloads(scope))))[
                ["result", "loop", "frame", "seq_s", "workload", "pass", "ms"]
            ]
        )
    if not frames:
        return pd.DataFrame(columns=["result", "loop", "frame", "benchmark_time_s", "workload", "pass", "ms"])
    return pd.concat(frames).rename(columns={"seq_s": "benchmark_time_s"})
