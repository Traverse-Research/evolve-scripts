#!/bin/sh
# Double-click this file on macOS to start Evolve Charts. A page opens in your browser.
cd "$(dirname "$0")"
if ! sh ./start-evolve-charts.sh; then
    echo
    echo "Something went wrong. Please send a screenshot of this window to Traverse Research."
    read -r _
fi
