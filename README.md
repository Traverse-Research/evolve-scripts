<div align="center">

# 📜 Evolve scripts

**Evolutionary benchmarking software**

[![Banner](./docs/images/banner.png)](https://traverseresearch.nl)

</div>

## 👷‍♀️ Requirements

Please ensure the following dependencies are installed before running scripts from this repository:

- Python 3.7
- ADB (Android Debug Bridge)


## 📊 Comparing deep analysis output

Using the `compare_deep_analysis.py` script located in the `scripts` directory, you can compare the results of two separate deep analysis output files in multiple ways. For the analysis methods, the scripts will first do an attempt to average over all loop iterations of the output. If you ran Evolve with `--looping 5`, each frame in the output will use the mean from each frame from each of the Evolve benchmark iterations.

## Additional Requirements
In addition to the requirements listed in [Requirements](#👷‍♀️-requirements), this script also requires the use of several python packages. These can be installed as follows:

```sh
python -m pip install -r requirements.txt
```

## Usage
```sh
usage: Evolve Deep Analysis Comparison [-h] [--pass_mean_comparison PASS_MEAN_COMPARISON] [--pass_stdev_comparison PASS_STDEV_COMPARISON] deep_analysis_file deep_analysis_file
```

### Parameters:

- `deep_analysis_file` - The path(s) to the input files to compare, produced by Evolve's deep analysis.
- `--pass_mean_comparison [filename]` - The csv file to which to output a comparison of the mean execution times of the render passes with the highest difference in mean execution times between the two. Example: `--pass_mean_comparison mean_difference.csv`.
- `--pass_stdev_comparison [filename]` - The csv file to which to output a comparison of the standard deviation over execution times of the render passes with the highest difference in standard deviation over the execution time, between the two. Example: `--pass_stdev_comparison stdev_difference.csv`.

At least one of `--pass_mean_comparison` or `--pass_stdev_comparison` arguments is required, as the script doesn't output any information by default.

### Example usage
```sh
python compare_deep_analysis.py --pass_mean_comparison mean_comparison.csv --pass_stdev_comparison stdev_comparison.csv deep_analysis_gpu_1.json deep_analysis_gpu_2.json
```