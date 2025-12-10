import pandas as pd
import json
from collections import defaultdict
# import numpy as np
import argparse
import sys

"""
Aggregates the gpu render pass data and metrics over all loop iteration to their mean over the loop iterations
"""
def aggregate_loops_passes(json):
    results_per_frame = []
    frames_affected = defaultdict(lambda: [0, 0, 0, 0])
    for loop_results in json:
        for frame_index, frame_results in enumerate(loop_results["per_frame_results"]):
            if frame_index >= len(results_per_frame):
                results_per_frame.append(defaultdict(int))
            for command_buffer_timings in frame_results[
                "command_buffer_timings"
            ].values():
                for scope_name, scope_timings in command_buffer_timings[
                    "scope_timings"
                ].items():
                    for scope_timing in scope_timings:
                        frames_affected[scope_name][2] += 1
                        frames_affected[scope_name][3] += scope_timing["end"] - scope_timing["start"]
                        if scope_timing["end"] == scope_timing["start"]:
                            frames_affected[scope_name][1] += 1
                            if scope_name not in results_per_frame[frame_index]:
                                frames_affected[scope_name][0] += 1
                            results_per_frame[frame_index][scope_name] += 1

    print(len(results_per_frame))
    df = pd.DataFrame.from_dict(frames_affected, orient='index', columns=["Zero frames", "Zero scopes", "Total scopes", "Total times"])
    df = df[df["Zero frames"] != 0]
    df["Avg time"] = (df["Total times"] / (df["Total scopes"] - df["Zero scopes"])).dropna().astype(int)
    df = df.sort_values(by="Zero frames", ascending=False)
    print(df)

    return results_per_frame


def metric_names():
    # TODO: Just derive from frame_results["metrics"], also handling cases where that object is null?
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
        help="The file to write the top 20 passes with the highest difference in mean execution time per pass to the specified path as csv. Useful for comparing the execution time of passes between different input files.",
        metavar="csv_output_filename"
    )
    parser.add_argument(
        "--pass_stdev_comparison",
        help="The file to write the top 20 passes with the highest difference of the standard deviation over execution time to the specified path as csv. Useful for comparing the variance in execution times of passes between different input files.",
        metavar="csv_output_filename"
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

    # if args.pass_mean_comparison is None and args.pass_stdev_comparison is None:
    #     print("Error: No analysis option specified, specify at least one\n")
    #     parser.print_usage()
    #     exit(1)
    # elif args.pass_mean_comparison == args.pass_stdev_comparison:
    #     print(
    #         "Error: Identical file outputs specified for analysis. Exiting as one will overwrite the other"
    #     )
    #     exit(1)

    output = {}

    for path in args.deep_analysis_file:
        with open(path, "r") as json_file:
            json_data = aggregate_loops_passes(json.load(json_file))
        # TODO: Use something else than input file path as naming scheme?
        output[path] = json_data



if __name__ == "__main__":
    main()
