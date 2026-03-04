import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import argparse
import sys
import os

METADATA_COLS = (
    "Evolve Version", "System Name", "CPU", "GPU",
    "OS Name", "OS Version", "GPU Driver Version",
)
FRAME_ID_COLS = ("Loop Index", "Frame")

TIMING_COLS = (
    "Sequence Time (ns)",
    "Ray Tracing (ns)",
    "Acceleration Structure Build (ns)",
    "Rasterization (ns)",
    "Compute (ns)",
    "Workgraphs (ns)",
    "Driver (ns)",
)

SCORE_COLS = (
    "Run Score: Raytracing",
    "Run Score: Acceleration Structure Builds",
    "Run Score: Rasterization",
    "Run Score: Compute",
    "Run Score: Workgraphs",
    "Run Score: Driver",
    "Run Score: Energy",
)

LINE_STYLES = ["-", "--", ":", "-."]

# Evolve brand palette (from evolve source)
EVOLVE_COLORS = [
    "#FD663A",  # Red medium
    "#94C191",  # Green light
    "#FFBDAE",  # Red light
    "#3E703C",  # Green medium
    "#CC3232",  # Red dark
    "#9B8D51",  # Brown dark
    "#EFE6BF",  # Brown medium
    "#F7F4E7",  # Brown light
]
EVOLVE_BG = "#07190b"       # Green darkest
EVOLVE_PANEL = "#0d3618"    # Green darker
EVOLVE_TEXT = "#F7F4E7"      # Brown light
EVOLVE_GRID = "#0F3F1D"     # Green dark


def load_csv(path):
    """Load and validate a single evolve_results.csv file."""
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except pd.errors.ParserError as e:
        print(f"Error: Failed to parse {path}: {e}", file=sys.stderr)
        sys.exit(1)

    df = df.replace("N/A", np.nan)

    for col in FRAME_ID_COLS:
        if col not in df.columns:
            print(
                f"Error: Required column '{col}' missing from {path}", file=sys.stderr
            )
            sys.exit(1)

    df["Loop Index"] = df["Loop Index"].astype(int)
    df["Frame"] = df["Frame"].astype(int)

    present_timing_cols = [col for col in TIMING_COLS if col in df.columns]
    missing_timing_cols = [col for col in TIMING_COLS if col not in df.columns]

    if missing_timing_cols:
        print(
            f"Warning: {path} is missing timing columns: {', '.join(missing_timing_cols)}",
            file=sys.stderr,
        )

    for col in present_timing_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in SCORE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_all(paths, labels):
    """Load all CSV files and compute the intersection of available timing columns."""
    datasets = {}
    for path, label in zip(paths, labels):
        datasets[label] = load_csv(path)

    available_per_file = [
        set(col for col in TIMING_COLS if col in df.columns)
        for df in datasets.values()
    ]
    common_timing_cols = list(TIMING_COLS)
    if available_per_file:
        common_set = set.intersection(*available_per_file)
        common_timing_cols = [col for col in TIMING_COLS if col in common_set]

    skipped = set(TIMING_COLS) - set(common_timing_cols)
    if skipped:
        print(
            f"Warning: Skipping columns not present in all files: {', '.join(skipped)}",
            file=sys.stderr,
        )

    # Drop columns that are entirely NaN across all files
    all_nan_cols = []
    for col in common_timing_cols:
        if all(df[col].isna().all() for df in datasets.values()):
            all_nan_cols.append(col)
    if all_nan_cols:
        print(
            f"Warning: Dropping all-NaN columns: {', '.join(all_nan_cols)}",
            file=sys.stderr,
        )
        common_timing_cols = [
            col for col in common_timing_cols if col not in all_nan_cols
        ]

    if not common_timing_cols:
        print("Error: No common timing columns across input files", file=sys.stderr)
        sys.exit(1)

    return datasets, common_timing_cols


def make_labels(paths, explicit_labels):
    """Derive display labels from file paths or explicit --labels argument."""
    if explicit_labels is not None:
        labels = [l.strip() for l in explicit_labels.split(",")]
        if len(labels) != len(paths):
            print(
                f"Error: --labels has {len(labels)} entries but {len(paths)} files were provided",
                file=sys.stderr,
            )
            sys.exit(1)
        return labels

    basenames = [os.path.basename(p) for p in paths]
    if len(set(basenames)) == len(basenames):
        return basenames

    # Basenames collide — prepend parent directory
    return [os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p)) for p in paths]


def extract_system_info(df):
    """Extract system metadata from the first row of a dataset."""
    row = df.iloc[0]
    info = {}
    for col in METADATA_COLS:
        if col in df.columns:
            val = row[col]
            info[col] = str(val).strip() if pd.notna(val) else "N/A"
    return info


def format_system_subtitle(datasets):
    """Build a subtitle string with system info for each input, one line per input."""
    lines = []
    for label, df in datasets.items():
        info = extract_system_info(df)
        gpu = info.get("GPU", "?")
        cpu = info.get("CPU", "?")
        driver = info.get("GPU Driver Version", "?")
        os_name = info.get("OS Name", "")
        os_ver = info.get("OS Version", "")
        os_str = f"{os_name} {os_ver}".strip()
        lines.append(f"{label}: {gpu} (driver {driver}), {cpu}, {os_str}")
    return "\n".join(lines)


def plot_timings(datasets, timing_cols):
    """Show a subplot grid of timing comparisons plotted against sequence time."""
    # Sequence Time is the X-axis, not a plotted column
    plot_cols = [col for col in timing_cols if col != "Sequence Time (ns)"]
    if "Sequence Time (ns)" not in timing_cols:
        print(
            "Error: 'Sequence Time (ns)' column is required for the X-axis",
            file=sys.stderr,
        )
        sys.exit(1)

    n_cols = len(plot_cols)
    ncols_grid = min(n_cols, 4)
    nrows_grid = (n_cols + ncols_grid - 1) // ncols_grid

    fig, axes = plt.subplots(
        nrows_grid, ncols_grid, figsize=(5 * ncols_grid, 4 * nrows_grid), squeeze=False,
        facecolor=EVOLVE_BG,
    )

    labels = list(datasets.keys())

    # Collect all unique loop indices across all datasets
    all_loops = sorted(
        set(
            loop
            for df in datasets.values()
            for loop in df["Loop Index"].unique()
        )
    )

    for idx, col in enumerate(plot_cols):
        row, c = divmod(idx, ncols_grid)
        ax = axes[row][c]

        ax.set_facecolor(EVOLVE_PANEL)
        for label_idx, (label, df) in enumerate(datasets.items()):
            color = EVOLVE_COLORS[label_idx % len(EVOLVE_COLORS)]
            for loop_idx_pos, loop_val in enumerate(all_loops):
                loop_data = df[df["Loop Index"] == loop_val].sort_values("Sequence Time (ns)")
                if loop_data.empty:
                    continue

                style = LINE_STYLES[loop_idx_pos % len(LINE_STYLES)]
                line_label = f"{label}" if len(all_loops) == 1 else f"{label} (loop {loop_val})"

                x_vals = loop_data["Sequence Time (ns)"].values / 1e9

                ax.plot(
                    x_vals,
                    loop_data[col].values / 1e6,
                    color=color,
                    linestyle=style,
                    linewidth=1,
                    label=line_label,
                    alpha=0.8,
                )

        short_name = col.replace(" (ns)", "")
        ax.set_title(short_name, fontsize=10, color=EVOLVE_TEXT)
        ax.set_xlabel("Sequence Time (s)", color=EVOLVE_TEXT)
        ax.set_ylabel("Time (ms)", color=EVOLVE_TEXT)
        ax.tick_params(colors=EVOLVE_TEXT)
        for spine in ax.spines.values():
            spine.set_color(EVOLVE_GRID)
        ax.grid(True, color=EVOLVE_GRID, alpha=0.5)

    # Hide unused subplots
    for idx in range(n_cols, nrows_grid * ncols_grid):
        row, c = divmod(idx, ncols_grid)
        axes[row][c].set_visible(False)

    # Single legend for the entire figure
    handles, legend_labels = axes[0][0].get_legend_handles_labels()
    legend = fig.legend(
        handles,
        legend_labels,
        loc="lower center",
        ncol=min(len(handles), 4),
        bbox_to_anchor=(0.5, -0.02),
        fontsize=9,
        facecolor=EVOLVE_PANEL,
        edgecolor=EVOLVE_GRID,
        labelcolor=EVOLVE_TEXT,
    )

    subtitle = format_system_subtitle(datasets)
    n_inputs = len(datasets)
    fig.suptitle(
        "Evolve Timing Comparison\n" + subtitle,
        fontsize=11,
        linespacing=1.4,
        color=EVOLVE_TEXT,
    )
    # Reserve more top space for subtitle lines
    top_margin = max(0.88, 0.96 - 0.03 * n_inputs)
    fig.tight_layout(rect=[0, 0.05, 1, top_margin])
    plt.show()


def extract_scores(df):
    """Extract per-run scores from the first row (scores are constant per run)."""
    row = df.iloc[0]
    scores = {}
    for col in SCORE_COLS:
        if col in df.columns:
            val = row[col]
            if pd.notna(val):
                scores[col] = float(val)
    return scores


def plot_scores(datasets):
    """Show a grouped bar chart comparing run scores across inputs."""
    # Collect scores per label, find common score columns with data
    all_scores = {}
    for label, df in datasets.items():
        all_scores[label] = extract_scores(df)

    # Only plot scores that have a value in at least one dataset
    common_scores = []
    for col in SCORE_COLS:
        if any(col in scores for scores in all_scores.values()):
            common_scores.append(col)

    if not common_scores:
        print("Warning: No score data found in input files", file=sys.stderr)
        return

    short_names = [col.replace("Run Score: ", "") for col in common_scores]
    n_labels = len(datasets)
    x = np.arange(len(common_scores))
    bar_width = 0.8 / n_labels

    fig, ax = plt.subplots(figsize=(max(10, len(common_scores) * 1.5), 5), facecolor=EVOLVE_BG)
    ax.set_facecolor(EVOLVE_PANEL)

    for i, (label, scores) in enumerate(all_scores.items()):
        color = EVOLVE_COLORS[i % len(EVOLVE_COLORS)]
        values = [scores.get(col, 0) for col in common_scores]
        bars = ax.bar(
            x + i * bar_width - (n_labels - 1) * bar_width / 2,
            values,
            bar_width,
            label=label,
            color=color,
            alpha=0.85,
        )
        # Value labels on bars
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    f"{int(val)}",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=EVOLVE_TEXT,
                )

    ax.set_xticks(x)
    ax.set_xticklabels(short_names, color=EVOLVE_TEXT)
    ax.set_ylabel("Score (higher is better)", color=EVOLVE_TEXT)
    ax.tick_params(colors=EVOLVE_TEXT)
    for spine in ax.spines.values():
        spine.set_color(EVOLVE_GRID)
    ax.grid(True, axis="y", color=EVOLVE_GRID, alpha=0.5)

    legend = ax.legend(
        facecolor=EVOLVE_PANEL,
        edgecolor=EVOLVE_GRID,
        labelcolor=EVOLVE_TEXT,
    )

    subtitle = format_system_subtitle(datasets)
    n_inputs = len(datasets)
    fig.suptitle(
        "Evolve Score Comparison\n" + subtitle,
        fontsize=11,
        linespacing=1.4,
        color=EVOLVE_TEXT,
    )
    top_margin = max(0.82, 0.92 - 0.03 * n_inputs)
    fig.tight_layout(rect=[0, 0, 1, top_margin])
    plt.show()


def main():
    parser = argparse.ArgumentParser(
        prog="Evolve Results Comparison",
        description="Compares per-frame timing data from two or more Evolve evolve_results.csv files",
    )
    parser.add_argument(
        "results_files",
        help="The evolve_results.csv files to compare",
        nargs="+",
    )
    parser.add_argument(
        "--labels",
        help="Comma-separated labels for each input file (default: derived from filenames)",
        type=str,
        default=None,
    )

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as e:
        print(f"Error: {e}\n", file=sys.stderr)
        parser.print_usage()
        sys.exit(2)

    if len(args.results_files) < 2:
        print("Error: At least 2 input files are required\n", file=sys.stderr)
        parser.print_usage()
        sys.exit(1)

    labels = make_labels(args.results_files, args.labels)
    datasets, timing_cols = load_all(args.results_files, labels)
    plot_scores(datasets)
    plot_timings(datasets, timing_cols)


if __name__ == "__main__":
    main()
