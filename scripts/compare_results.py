import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import argparse
import sys
import os

METADATA_COLS = (
    "Evolve Version",
    "System Name",
    "CPU",
    "GPU",
    "OS Name",
    "OS Version",
    "GPU Driver Version",
)
FRAME_ID_COLS = ("Loop Index", "Frame")

TIMING_COLS = (
    "Elapsed Time (ns)",
    "Ray Tracing (ns)",
    "Acceleration Structure Build (ns)",
    "Rasterization (ns)",
    "Compute (ns)",
    "Workgraphs (ns)",
    "Driver (ns)",
)

METRIC_COLS = (
    "Energy (W)",
    "Gpu Usage (%)",
    "Clock Speed (Mhz)",
    "Vram Clock Speed (Mhz)",
    "Gpu Voltage (mV)",
    "Fan Speed (rpm or %)",
    "Edge Temperature (C)",
    "Hot Spot Temperature (C)",
)

SCORE_COLS = (
    "Raytracing",
    "Acceleration Structure Builds",
    "Rasterization",
    "Compute",
    "Workgraphs",
    "Driver",
    "Energy",
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
EVOLVE_BG = "#07190b"  # Green darkest
EVOLVE_PANEL = "#0d3618"  # Green darker
EVOLVE_TEXT = "#F7F4E7"  # Brown light
EVOLVE_GRID = "#0F3F1D"  # Green dark


# Load and validate a single evolve_results.csv file.
def load_csv(path):
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except pd.errors.ParserError as e:
        print(f"Error: Failed to parse {path}: {e}", file=sys.stderr)
        sys.exit(1)

    df["Loop Index"] = df["Loop Index"].astype(int)
    df["Frame"] = df["Frame"].astype(int)

    # Convert known data columns from strings to numbers, empty values become NaN
    for group in (TIMING_COLS, METRIC_COLS, SCORE_COLS):
        for col in group:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# Load all CSV files and compute the intersection of available timing columns.
def load_all(paths, labels):
    datasets = {}
    for path, label in zip(paths, labels):
        datasets[label] = load_csv(path)

    available_per_file = [
        set(col for col in TIMING_COLS if col in df.columns) for df in datasets.values()
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


# Derive display labels from file paths or explicit --labels argument.
def make_labels(paths, explicit_labels):
    if explicit_labels is not None:
        labels = [part.strip() for part in explicit_labels.split(",")]
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
    return [
        os.path.join(os.path.basename(os.path.dirname(p)), os.path.basename(p))
        for p in paths
    ]


# Extract system metadata from the first row of a dataset.
def extract_system_info(df):
    row = df.iloc[0]
    info = {}
    for col in METADATA_COLS:
        if col in df.columns:
            val = row[col]
            info[col] = str(val).strip() if pd.notna(val) else "N/A"
    return info


# Build a subtitle string with system info for each input, one line per input.
def format_system_subtitle(datasets):
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


# Show a subplot grid of timing comparisons plotted against elapsed time.
def plot_timings(datasets, timing_cols):
    # Elapsed Time is the X-axis, not a plotted column
    plot_cols = [col for col in timing_cols if col != "Elapsed Time (ns)"]
    if "Elapsed Time (ns)" not in timing_cols:
        print(
            "Error: 'Elapsed Time (ns)' column is required for the X-axis",
            file=sys.stderr,
        )
        sys.exit(1)

    n_cols = len(plot_cols)
    ncols_grid = min(n_cols, 4)
    nrows_grid = (n_cols + ncols_grid - 1) // ncols_grid

    fig, axes = plt.subplots(
        nrows_grid,
        ncols_grid,
        figsize=(5 * ncols_grid, 4 * nrows_grid),
        squeeze=False,
        facecolor=EVOLVE_BG,
    )

    # Collect all unique loop indices across all datasets
    all_loops = sorted(
        set(loop for df in datasets.values() for loop in df["Loop Index"].unique())
    )

    for idx, col in enumerate(plot_cols):
        row, c = divmod(idx, ncols_grid)
        ax = axes[row][c]

        ax.set_facecolor(EVOLVE_PANEL)
        for label_idx, (label, df) in enumerate(datasets.items()):
            color = EVOLVE_COLORS[label_idx % len(EVOLVE_COLORS)]
            for loop_idx_pos, loop_val in enumerate(all_loops):
                loop_data = df[df["Loop Index"] == loop_val].sort_values(
                    "Elapsed Time (ns)"
                )
                if loop_data.empty:
                    continue

                style = LINE_STYLES[loop_idx_pos % len(LINE_STYLES)]
                line_label = (
                    f"{label}" if len(all_loops) == 1 else f"{label} (loop {loop_val})"
                )

                x_vals = loop_data["Elapsed Time (ns)"].values / 1e9

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
        ax.set_xlabel("Elapsed Time (s)", color=EVOLVE_TEXT)
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
    fig.legend(
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


# Extract scores for each loop index. Returns {loop_index: {col: value}}.
def extract_scores(df):
    scores_per_loop = {}
    for loop_val in df["Loop Index"].unique():
        row = df[df["Loop Index"] == loop_val].iloc[0]
        scores = {}
        for col in SCORE_COLS:
            if col in df.columns:
                val = row[col]
                if pd.notna(val):
                    scores[col] = float(val)
        scores_per_loop[loop_val] = scores
    return scores_per_loop


# Show a grouped bar chart comparing run scores across inputs and loops.
def plot_scores(datasets):
    # Collect scores per label per loop
    all_scores = {}
    for label, df in datasets.items():
        all_scores[label] = extract_scores(df)

    # Build list of (label, loop_index, scores) for each bar group
    bar_groups = []
    for label, loops in all_scores.items():
        for loop_val, scores in sorted(loops.items()):
            if len(loops) == 1:
                bar_label = label
            else:
                bar_label = f"{label} (loop {loop_val})"
            bar_groups.append((bar_label, scores))

    # Only plot scores that have a value in at least one group
    common_scores = []
    for col in SCORE_COLS:
        if any(col in scores for _, scores in bar_groups):
            common_scores.append(col)

    if not common_scores:
        print("Warning: No score data found in input files", file=sys.stderr)
        return

    short_names = list(common_scores)
    n_bars = len(bar_groups)
    x = np.arange(len(common_scores))
    bar_width = 0.8 / n_bars

    fig, ax = plt.subplots(
        figsize=(max(10, len(common_scores) * 1.5), 5), facecolor=EVOLVE_BG
    )
    ax.set_facecolor(EVOLVE_PANEL)

    for i, (bar_label, scores) in enumerate(bar_groups):
        color = EVOLVE_COLORS[i % len(EVOLVE_COLORS)]
        values = [scores.get(col, 0) for col in common_scores]
        bars = ax.bar(
            x + i * bar_width - (n_bars - 1) * bar_width / 2,
            values,
            bar_width,
            label=bar_label,
            color=color,
            alpha=0.85,
        )
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

    ax.legend(
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


def parse_args():
    parser = argparse.ArgumentParser(
        prog="Evolve Results Comparison",
        description="Visualizes and compares per-frame timing data from one or more Evolve evolve_results.csv files",
    )
    parser.add_argument(
        "results_files",
        help="The evolve_results.csv files to compare",
        nargs="+",
    )
    parser.add_argument(
        "--labels",
        help=(
            "Comma-separated labels for each input file"
            " (default: derived from filenames)"
        ),
        type=str,
        default=None,
    )

    try:
        args = parser.parse_args()
    except argparse.ArgumentError as e:
        print(f"Error: {e}\n", file=sys.stderr)
        parser.print_usage()
        sys.exit(2)

    if len(args.results_files) < 1:
        print("Error: At least 1 input file is required\n", file=sys.stderr)
        parser.print_usage()
        sys.exit(1)

    return args


def main():
    args = parse_args()
    labels = make_labels(args.results_files, args.labels)
    datasets, timing_cols = load_all(args.results_files, labels)
    plot_scores(datasets)
    plot_timings(datasets, timing_cols)


if __name__ == "__main__":
    main()
