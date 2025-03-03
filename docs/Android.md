## Automating `evolve` benchmark run on Android

1. Make sure the app is installed.
2. Use relative paths in `--export*` parameters, so that `evolve` has access to write them relative to `/sdcard/Android/data/nl.traverse_research.evolve/files/`.  Subfolders are supported, these will automatically created.
   - It is recommended to use subfolders with the current date and time, as `evolve` will refuse to start and overwrite any export files that aleady exist.
3. Use the `python ./scripts/run_on_android.py` script in this folder to start Evolve, like a desktop run. Common parameters to export all data from a `run-custom` are:
   ```sh
   ts=$(date '+%F-%T')
   python ./scripts/run_on_android.py run-custom --export-scores $ts/scores.csv --export-per-frame $ts/frames.csv --export-deep-analysis $ts/deep-analysis.json
   ```
4. When the benchmark finishes, run the following commands to pull the resulting files to your desktop:
  ```sh
   adb pull /sdcard/Android/data/nl.traverse_research.evolve/files/$ts/deep-analysis.json
   adb pull /sdcard/Android/data/nl.traverse_research.evolve/files/$ts/scores.csv
   adb pull /sdcard/Android/data/nl.traverse_research.evolve/files/$ts/frames.csv
   ```
   Alternatively, pull the entire timestamped folder:
  ```sh
   adb pull /sdcard/Android/data/nl.traverse_research.evolve/files/$ts
   ```
   These paths can also be found directly on the phone by navigating its internal storage using MTP (when `USB for file transfer` is enabled via the notification on the phone).
