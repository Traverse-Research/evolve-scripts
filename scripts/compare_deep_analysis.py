import pandas as pd
import json
from collections import defaultdict
import numpy as np
import argparse
import sys
import pprint

from flatten_json import flatten

"""
Aggregates the gpu render pass data and metrics over all loop iteration to their mean over the loop iterations
"""


def aggregate_loops_passes(json):
    results_per_frame = []
    num_loops = len(json)
    for loop_results in json:
        for frame_index, frame_results in enumerate(loop_results["per_frame_results"]):
            #pprint.pprint(frame_results)
            if frame_index >= len(results_per_frame):
                results_per_frame.append(defaultdict(int))
            for command_buffer_timings in frame_results[
                "command_buffer_timings"
            ].values():
                for scope_name, scope_timings in command_buffer_timings[
                    "scope_timings"
                ].items():
                    for scope_timing in scope_timings:
                        results_per_frame[frame_index][scope_name] += (
                            scope_timing["end"] - scope_timing["start"]
                        ) / num_loops
            for metric_name, metric in frame_results["metrics"].items():
                # TODO: Flatten this in rust to fan_speed_rpm
                if metric_name == "fan_speed":
                    value = metric["Percent"] if "Percent" in metric else metric["Rpm"]
                    results_per_frame[frame_index]["fan_speed_rpm"] += (
                        value / num_loops
                    )
                # Filter out unavailable data and the timestamp
                elif metric is not None and metric_name != "timestamp":
                    results_per_frame[frame_index][metric_name] += metric / num_loops
    # TODO: Aggregate CPU timings
    return pd.DataFrame([flatten(x) for x in results_per_frame])


def metric_names():
    return [
        "edge_temperature_in_c",
        "hotspot_temperature_in_c",
        "usage_percentage",
        "fan_speed_rpm",
        "clock_speed_in_mhz",
        "vram_clock_speed_in_mhz",
        "power_usage_in_w",
        "board_power_usage_in_w",
        "voltage_in_mv",
        "vram_usage_in_mb",
    ]


"""
Outputs the 20 passes with the highest difference in mean between the two
deep analysis inputs
"""


def output_top_passes(input_1, input_2):
    combined_data = pd.concat([input_1.mean(), input_2.mean()], axis=1)
    combined_data.columns = ["Input 1", "Input 2"]
    combined_data.index.names = ["Pass Name"]
    combined_data["pct_diff"] = (
        combined_data["Input 1"] / combined_data["Input 2"]
    ).abs().drop(metric_names(), errors="ignore") * 100
    combined_data = (
        combined_data.sort_values(by="pct_diff", ascending=False)
        #.iloc[:20]
        .round()
        .dropna()
        .astype(int)
    )
    return combined_data


"""
Output the 20 passes with the highest difference in standard deviation
between the two deep deep analysis input DataFrames
"""


def output_top_stdev(input_1, input_2):
    combined_data = pd.concat([input_1.std(), input_2.std()], axis=1)
    combined_data.columns = ["Input 1", "Input 2"]
    combined_data.index.names = ["Pass Name"]
    # In case there's a mismatch in frames etc.
    combined_data.replace(0, np.nan, inplace=True)

    # Convert to percentages, since tools like google sheets won't correctly interpret decimal results
    # depending on the set language
    combined_data["pct_diff"] = (
        combined_data["Input 1"] / combined_data["Input 2"]
    ).abs().drop(metric_names(), errors="ignore") * 100
    combined_data = (
        combined_data.sort_values(by="pct_diff", ascending=False)
        #.iloc[:20]
        .round()
        .dropna()
        .astype(int)
    )
    combined_data = combined_data.drop("pct_diff", axis=1)
    return combined_data


def main():
    parser = argparse.ArgumentParser(
        prog="Evolve Deep Analysis Comparison",
        description="Compares two files produced by Evolve's deep analysis export",
    )
    parser.add_argument(
        "deep_analysis_file",
        help="The deep analysis output files to use for the comparative analysis",
        nargs=2,
    )
    parser.add_argument(
        "--pass_mean_comparison",
        help="Outputs the top 20 passes with the highest difference in mean execution time per pass to the specified path as csv. Useful for comparing the execution time of passes between different input files.",
    )
    parser.add_argument(
        "--pass_stdev_comparison",
        help="Outputs the top 20 passes with the highest difference of the standard deviation over execution time to the specified path as csv. Useful for comparing the variance in execution times of passes between different input files.",
    )
    try:
        args = parser.parse_args()
    except argparse.ArgumentError as e:
        # This works around some inconsistent behaviour with argparse on different Python versions.
        # < 3.11 seems to always throw an exception, regardless of `exit_on_error`
        # 3.11 seems to never throw an exception, regardless of `exit_on_error` (it will exit itself)
        # >= 3.13 (?) seems to respect `exit_on_error`
        # Avoid an exception being thrown when we fail to parse the args, so that we can manually print
        # the usage message as well
        print(f"Error: {e}\n", file=sys.stderr)
        parser.print_usage()
        exit(2)

    if not args.pass_mean_comparison and not args.pass_stdev_comparison:
        print("Error: No analysis option specified, specify at least one\n")
        parser.print_usage()
        exit(1)
    elif args.pass_mean_comparison == args.pass_stdev_comparison:
        print(
            "Error: Identical file outputs specified for analysis. Exiting as one will overwrite the other"
        )
        exit(1)

    output = {}

    for path in args.deep_analysis_file:
        with open(path, "r") as json_file:
            json_data = aggregate_loops_passes(json.load(json_file))
        # TODO: Use something else than input file path as naming scheme?
        output[path] = json_data

    # argparse already asserts that the number of inputs is two
    first, second = output.values()

    if args.pass_mean_comparison is not None:
        output_top_passes(first, second).to_csv(args.pass_mean_comparison)
    if args.pass_stdev_comparison is not None:
        output_top_stdev(first, second).to_csv(args.pass_stdev_comparison)


if __name__ == "__main__":
    main()
