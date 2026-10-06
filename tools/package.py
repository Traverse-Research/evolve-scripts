"""Build the Evolve Charts download: a zip with only what's needed to run the tool.

Usage (from the repository root):

    python tools/package.py [version]

Writes dist/Evolve-Charts.zip with one "Evolve Charts" folder inside. The GitHub release workflow runs
this and attaches the zip to the release.
"""

import stat
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FOLDER = "Evolve Charts"
OUTPUT = REPO_ROOT / "dist/Evolve-Charts.zip"

FILES = [
    "Start Evolve Charts.bat",
    "Start Evolve Charts.command",
    "start-evolve-charts.sh",
    "evolve-charts.py",
    "evolve-charts.py.lock",
    ".streamlit/config.toml",
    "exports/README.txt",
]
FOLDERS = ["evolve_charts", "static"]
EXECUTABLE = {"Start Evolve Charts.command", "start-evolve-charts.sh"}

HOW_TO_START = """Evolve Charts {version}
https://github.com/Traverse-Research/evolve-scripts

Compare Evolve benchmark results in your web browser. Nothing is uploaded anywhere.

Windows: double-click "Start Evolve Charts".
         If Windows asks whether to run it, choose "More info" and then "Run anyway".
macOS:   right-click "Start Evolve Charts.command" and choose "Open" (only needed the first time).
Linux:   run ./start-evolve-charts.sh in a terminal.

The first start downloads Python and the libraries the tool uses (about 150 MB) and needs an
internet connection. Keep the window that opens running while you use the tool.

To load results automatically, put Evolve export files in the "exports" folder.
"""


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "development version"
    paths = [REPO_ROOT / name for name in FILES]
    for folder in FOLDERS:
        paths += sorted(
            path for path in (REPO_ROOT / folder).rglob("*") if path.is_file() and "__pycache__" not in path.parts
        )

    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            relative = path.relative_to(REPO_ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, f"{FOLDER}/{relative}")
            mode = 0o755 if relative in EXECUTABLE else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
        for name, text in [
            ("HOW TO START.txt", HOW_TO_START.format(version=version).replace("\n", "\r\n")),
            ("VERSION", version),
        ]:
            info = zipfile.ZipInfo(f"{FOLDER}/{name}")
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, text)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(paths) + 2} files, version {version})")


if __name__ == "__main__":
    main()
