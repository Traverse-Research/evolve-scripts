#!/bin/sh
# Starts Evolve Charts on macOS or Linux. A page opens in your browser.
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
    echo "Evolve Charts needs \"uv\" to download Python and the libraries it uses."
    echo "It will now be installed for your user account from https://astral.sh/uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "Starting Evolve Charts. The first start downloads Python and the libraries it uses"
echo "(about 150 MB) and can take a few minutes; later starts are quick."
echo "Keep this window open while you use the tool; press Ctrl+C to stop."
exec uv run evolve-charts.py
