"""Plotly figures with one shared, publication-ready style."""

import pandas as pd
import plotly.graph_objects as go

# Evolve's palette (`evolve/crates/evolve/src/ui/styling.rs`) nudged in lightness and chroma until every
# adjacent pair, and every pair among the first four, stays apart for colour-blind readers on white:
# Evolve green and orange lead, as the two results most comparisons have.
RESULT_COLORS = ["#296127", "#F0582A", "#8A5AA8", "#2E9C94", "#C48A2C", "#3F7FC8", "#7DAA4E", "#B5294A"]


GREEN, ORANGE, PURPLE, TEAL, GOLD, BLUE, LIGHT_GREEN, WINE = RESULT_COLORS

# (colour, hatch) per workload category, fixed so a category looks the same in every chart; every pair of
# neighbours in Evolve's order stays apart for colour-blind readers.
WORKLOAD_STYLES = {
    "Raytracing": (ORANGE, ""),
    "Acceleration Structure Builds": (PURPLE, ""),
    "Rasterization": (GREEN, ""),
    "Compute": (TEAL, ""),
    "Workgraphs": (GOLD, ""),
    "NRC": (WINE, ""),
    "Upscaling": (LIGHT_GREEN, ""),
}

# Evolve's Spartan, loaded into the page from `static/`; downloaded SVGs fall back when it isn't installed.
FONT = "Spartan, Segoe UI, Helvetica, Arial, sans-serif"
# Text on Evolve's white frames: GREEN_DARK for text, GRAY_DIM for secondary text, GRAY_LIGHT for grid lines.
TEXT = "#0F3F1D"
MUTED = "#696969"
GRID = "#EEEAEA"
EXPORT_WIDTH = 1200


def result_colors(labels: list[str]) -> dict[str, str]:
    return {label: RESULT_COLORS[index % len(RESULT_COLORS)] for index, label in enumerate(labels)}


def style(fig: go.Figure, title: str, subtitle: str, note: str | None, height: int) -> go.Figure:
    fig.update_layout(
        template="simple_white",
        height=height,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font={"family": FONT, "size": 15, "color": TEXT},
        title={
            "text": f"<b>{title}</b>",
            "subtitle": {"text": subtitle, "font": {"size": 15, "color": MUTED}},
            "x": 0.015,
            "xanchor": "left",
            "xref": "container",
            "y": 1 - 18 / height,
            "yanchor": "top",
            "yref": "container",
            "font": {"size": 22},
        },
        # Generous side margins: Plotly measures labels before the Spartan web font has loaded.
        margin={"l": 60, "r": 60, "t": 95 if subtitle else 65, "b": 130 if note else 60},
        # Beside the plot rather than above it, so long legends never run into the title.
        legend={
            "orientation": "v",
            "yanchor": "top",
            "y": 1.0,
            "x": 1.01,
            "xanchor": "left",
            "title": None,
            "traceorder": "normal",
        },
        hoverlabel={"font": {"family": FONT}},
    )
    # Plotly sizes the legend before the Spartan web font has loaded; an em space absorbs the wider text.
    for trace in fig.data:
        if trace.name and not trace.name.endswith("\u2003"):
            trace.name += "\u2003"
    axis = {"gridcolor": GRID, "linecolor": MUTED, "tickcolor": MUTED, "zerolinecolor": MUTED, "automargin": True}
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    if note:
        fig.add_annotation(
            text=note,
            xref="paper",
            yref="paper",
            x=0,
            y=0,
            yanchor="top",
            yshift=-70,
            xanchor="left",
            align="left",
            showarrow=False,
            font={"size": 12, "color": MUTED},
        )
    return fig


def download_config(filename: str, image_format: str, height: int) -> dict:
    return {
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "toImageButtonOptions": {
            "format": image_format,
            "filename": filename,
            "width": EXPORT_WIDTH,
            "height": height,
            "scale": 2 if image_format == "png" else 1,
        },
    }


def breakdown(
    summary: pd.DataFrame,
    labels: list[str],
    percent: bool,
    order: list[str],
    styles: dict[str, tuple[str, str]],
    descriptions: dict[str, str],
) -> go.Figure:
    """Stacked horizontal bar per result, split by category."""
    value = "share_pct" if percent else "mean_ms"
    labels = [label for label in labels if label in set(summary["result"])]
    fig = go.Figure()
    present = [item for item in order if summary.loc[summary["item"] == item, "mean_ms"].sum() > 0]
    for item in present:
        rows = summary[summary["item"] == item].set_index("result").reindex(labels)
        color, hatch = styles.get(item, ("#A8A8A8", ""))
        fig.add_bar(
            name=item,
            y=labels,
            x=rows[value],
            orientation="h",
            marker={
                "color": color,
                "pattern": {"shape": hatch, "fgcolor": "#FFFFFF", "solidity": 0.35},
                # A 2px white gap between stacked segments keeps neighbouring categories apart.
                "line": {"color": "#FFFFFF", "width": 2},
            },
            customdata=list(zip(rows["mean_ms"], rows["share_pct"])),
            hovertemplate=f"<b>{item}</b><br>%{{customdata[0]:.2f}} ms per frame (%{{customdata[1]:.1f}}%)"
            f"<br><i>{_wrap(descriptions.get(item, ''))}</i><extra>%{{y}}</extra>",
        )
    if not percent:
        totals = summary.groupby("result")["mean_ms"].sum().reindex(labels)
        for label, total in totals.items():
            fig.add_annotation(x=total, y=label, text=f"  {total:.1f} ms", xanchor="left", showarrow=False)
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="Share of GPU time (%)" if percent else "GPU time per frame (ms)")
    return fig


def score_bars(scores: pd.DataFrame, colors: dict[str, str]) -> go.Figure:
    """Grouped horizontal bars: one row per score, one bar per result."""
    fig = go.Figure()
    for label in scores.columns:
        fig.add_bar(
            name=label,
            y=scores.index,
            x=scores[label],
            orientation="h",
            marker_color=colors[label],
            text=[f"{value:,.0f}" if pd.notna(value) else "" for value in scores[label]],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x:,.0f}<extra>" + label + "</extra>",
        )
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05, barcornerradius=4)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="Score (higher is better)", rangemode="tozero")
    return fig


def bars(summary: pd.DataFrame, labels: list[str], colors: dict[str, str], items: list[str]) -> go.Figure:
    """Grouped horizontal bars: one row per item, one bar per result, whiskers from p5 to p95."""
    fig = go.Figure()
    for label in labels:
        rows = summary[summary["result"] == label].set_index("item").reindex(items)
        # Results without any of these items (no shadows in path tracing) get no bars or legend entry.
        if rows["mean_ms"].isna().all():
            continue
        fig.add_bar(
            name=label,
            y=items,
            x=rows["mean_ms"],
            orientation="h",
            marker_color=colors[label],
            error_x={
                "type": "data",
                "symmetric": False,
                "array": rows["p95_ms"] - rows["mean_ms"],
                "arrayminus": rows["mean_ms"] - rows["p5_ms"],
                "color": "#888888",
                "thickness": 1.2,
                "width": 3,
            },
            customdata=list(zip(rows["median_ms"], rows["p5_ms"], rows["p95_ms"], rows["ran_in_pct_of_frames"])),
            hovertemplate="<b>%{y}</b><br>mean %{x:.3f} ms · median %{customdata[0]:.3f} ms"
            "<br>5–95% of frames: %{customdata[1]:.3f}–%{customdata[2]:.3f} ms"
            "<br>runs in %{customdata[3]:.0f}% of frames<extra>" + label + "</extra>",
        )
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05, barcornerradius=4)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="GPU time per frame (ms)", rangemode="tozero")
    return fig


def bars_height(items: int, results: int) -> int:
    return int(220 + items * max(results, 1) * 22 + items * 10)


def lines(
    series: dict[str, pd.Series], colors: dict[str, str], y_title: str, unit: str, from_zero: bool = True
) -> go.Figure:
    """One line per result over benchmark time. Sensors zoom in (`from_zero=False`) so small drifts show."""
    fig = go.Figure()
    for label, values in series.items():
        fig.add_scatter(
            name=label,
            x=values.index,
            y=values.values,
            mode="lines",
            line={"color": colors[label], "width": 2},
            hovertemplate=f"%{{y:.2f}} {unit} at %{{x:.1f}} s<extra>{label}</extra>",
        )
    fig.update_xaxes(title="Benchmark time (s)")
    fig.update_yaxes(title=y_title, rangemode="tozero" if from_zero else "normal")
    fig.update_layout(hovermode="x unified")
    return fig


def _wrap(text: str, width: int = 60) -> str:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return "<br>".join([*lines, line])
