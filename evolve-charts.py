# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "streamlit>=1.65",
#     "plotly>=6",
#     "pandas>=2.2",
# ]
# ///
"""Evolve Charts: turn Evolve deep analysis exports into charts.

Start it by double-clicking `Start Evolve Charts.bat` (Windows) or `start-evolve-charts.sh`
(macOS/Linux), or run `uv run evolve-charts.py`. A page opens in your browser; nothing leaves
your computer.
"""

import os
import sys
from pathlib import Path

from streamlit.runtime.scriptrunner import get_script_run_ctx

HERE = Path(__file__).resolve().parent

# Under `streamlit run` this file is executed inside a script run; started directly, it relaunches itself that way.
if get_script_run_ctx(suppress_warning=True) is not None:
    sys.path.insert(0, str(HERE))
    from evolve_charts.ui import main

    main()
else:
    from streamlit.web import cli

    # Streamlit reads `.streamlit/config.toml` (theme, privacy and upload settings) from the working directory.
    os.chdir(HERE)
    sys.argv = ["streamlit", "run", str(HERE / "evolve-charts.py"), *sys.argv[1:]]
    sys.exit(cli.main())
