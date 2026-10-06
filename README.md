<div align="center">

# 📊 Evolve Charts

**Turn Evolve deep analysis exports into publication-ready charts**

[![Banner](./docs/images/banner.png)](https://traverseresearch.nl)

</div>

Evolve Charts compares Evolve benchmark results: scores, GPU time per workload category and per pass,
and GPU sensors, across GPUs and settings. You don't need to know Python or git. It opens as a page in
your web browser, and **everything stays on your computer**. Nothing is uploaded.

## ⬇️ Download

**[Download Evolve Charts (Evolve-Charts.zip)](https://github.com/Traverse-Research/evolve-scripts/releases/latest/download/Evolve-Charts.zip)**

1. **Extract the zip.** Right-click it and choose **Extract All…** (Windows) or double-click it (macOS),
   for example to your Desktop. Don't start the tool from inside the zip.
2. **Start the tool** from the extracted *Evolve Charts* folder:
   - **Windows:** double-click **Start Evolve Charts**. If Windows warns about the file, click
     **More info › Run anyway**.
   - **macOS:** right-click **Start Evolve Charts.command** and choose **Open** (the first time only;
     after that a double-click works).
   - **Linux:** run `./start-evolve-charts.sh` in a terminal.

   The first start installs [uv](https://docs.astral.sh/uv/), a small helper that downloads Python and
   the libraries the tool uses (about 150 MB). This needs an internet connection, takes a few minutes and
   only happens once. Keep the window that opens running while you use the tool; close it when you're
   done.
3. **Export your results from Evolve.** After a benchmark run, click **Export** on the score screen. Do
   this on every GPU or setting you want to compare, using the same benchmark on each. Scores and
   per-frame data are always included; deep analysis (per-pass timings) needs an Evolve Professional
   licence.
4. **Add your results.** Your browser opens Evolve Charts. Drag the export files onto *Add Evolve
   exports*, or put them in the `exports` folder so they load automatically every time.
5. **Name your results** on their cards (for example "RTX 4070 Ti" or "Gen 1"). These names appear in
   every chart.

To update, download the zip again and replace the old folder (keep your `exports` folder if you use it).

## 🗺️ What's in the tool

The tool reads every Evolve export: the **Export** zip from the score screen, and the files Evolve's
command line writes (`evolve_results.csv`, `scores.csv`, the per-frame CSV and `deep_analysis.json`).
It has a page per question, in the bar at the top:

| Page | What it shows | Needs |
|---|---|---|
| **Results** | Load and name exports; GPU, driver, OS, Evolve version and what each file contains | |
| **Scores** | Evolve's scores side by side, with the workload category each one scores, and the differences | scores |
| **GPU time** | Where the GPU spends its time each frame, per workload category; then one workload category over the run and the passes it's made of | per-frame data; the passes need deep analysis |
| **Passes** | Every render pass in one searchable table; tick passes to plot them over the run | deep analysis |
| **GPU sensors** | Clocks, power, temperature and more during the run, to spot throttling | per-frame data |
| **Export** | CSV files for Excel, Google Sheets, Datawrapper and Flourish | |

On every page except Results, a bar at the top shows the loaded results and lets you pick the one to
**compare against**.

**How Evolve measures a GPU.** Evolve times **passes**: single blocks of GPU work. A **workload
category** is GPU work that logically belongs together, and what Evolve scores. All ray tracing work,
such as the *shadow-raytrace-inline* pass, is the *Raytracing* workload: the *Ray Tracing* score. There is
one score per workload category and no total score.

**Downloading a chart:** hover over it and click the 📷 camera icon in its top-right corner. Use
**Charts** at the top right to choose PNG or SVG and whether charts get a source line with the GPUs,
drivers and Evolve version. **Help** explains how the numbers are made.

## 📏 How to read the numbers

- **GPU time per frame** is how long the GPU spent on that work, averaged over every frame of the
  run. The first second is skipped because it includes one-off setup work. Lines over time are
  smoothed over one second.
- Passes Evolve doesn't assign to a workload category (such as drawing the user interface) are left
  out; the *GPU time* page says how much that is.
- Workload categories add up to the GPU work shown. That can differ a little from the time between frames,
  because a GPU can idle between passes or run passes at the same time.
- **Whiskers** on bar charts show the range covering 90% of frames (5th to 95th percentile).
- Only compare results from the **same Evolve version and benchmark settings**. The tool warns you
  when the Evolve versions or graphics APIs differ.

## ❓ Troubleshooting

- **A result is missing from *Passes***: its export has no deep analysis, which
  needs an Evolve Professional licence. Its card shows ✗ Deep analysis; scores and workload
  categories still work.
- **The browser doesn't open**: open <http://localhost:8501> yourself while the black window is open.
- **Anything else**: send a screenshot of the black window to Traverse Research.

## 🛠️ For developers

- Run without the launcher: `uv run evolve-charts.py`. Dependencies are declared inline
  ([PEP 723](https://peps.python.org/pep-0723/)), so no virtual environment is needed.
- Code lives in `evolve_charts/`:
  - `loader.py` reads export zips into tidy tables.
  - `categories.py` describes Evolve's workload categories and which pass belongs to which.
  - `stats.py` computes the summaries.
  - `charts.py` builds the Plotly figures.
  - `ui.py` is the Streamlit page.
- The look follows Evolve's `crates/evolve/src/ui/styling.rs`: theme colours and the Spartan font are set in
  `.streamlit/config.toml`, and the fonts, logo and icon live in `static/`. Chart colours are in `charts.py`.
- Which pass belongs to which workload category comes from Evolve's Rust source. After pass names
  change in Evolve, regenerate the list with `python tools/sync_categories.py` (it reads
  `../evolve/crates/evolve-frame-bucketing/src/lib.rs` by default).
- Dependencies are locked in `evolve-charts.py.lock`; refresh it with `uv lock --script evolve-charts.py --upgrade`.
- Tests: `uv export --script evolve-charts.py --no-hashes > requirements.txt`, then
  `uv venv && uv pip install -r requirements.txt pytest && uv run --no-project pytest`. CI runs the same.
- Releases: push a tag like `v1.0.0`. The release workflow tests, runs `tools/package.py` and attaches
  `Evolve-Charts.zip` to a GitHub release; the download link above always points to the newest one.

## 📱 Other scripts

- `scripts/run_on_android.py` starts Evolve on an Android device with command-line arguments. See
  [docs/Android.md](docs/Android.md).
