## Automating `evolve` benchmark runs on Android

1. Make sure the app is installed.
2. Use the `python ./scripts/run_on_android.py` script in this folder to start Evolve with command-line
   arguments, like a desktop run:
   ```sh
   python ./scripts/run_on_android.py run-custom --benchmark ray-tracing-inline
   ```
3. Evolve saves every run as a `.evolve` file in
   `/sdcard/Android/data/nl.traverse_research.evolve/files/Documents/results/`. When the benchmark finishes,
   pull them to your desktop:
   ```sh
   adb pull /sdcard/Android/data/nl.traverse_research.evolve/files/Documents/results evolve-results
   ```
   The folder can also be found on the phone by browsing its internal storage over MTP (when
   `USB for file transfer` is enabled via the notification on the phone).
4. Load the `.evolve` files into Evolve Charts.
