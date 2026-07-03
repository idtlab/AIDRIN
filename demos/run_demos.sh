#!/bin/bash
# Run all AIDRIN metric demos.
#
# Usage:
#   cd /home/w1b/drai/apps/aidrin
#   source /opt/venvs/drai/bin/activate
#   bash demos/run_demos.sh
#
# Prerequisites:
#   python demos/generate_datasets.py   # creates the synthetic CSVs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generate datasets if missing
if [ ! -f "$SCRIPT_DIR/messy_sensor_data.csv" ]; then
    echo "=== Generating synthetic datasets ==="
    python "$SCRIPT_DIR/generate_datasets.py"
    echo
fi

for config in "$SCRIPT_DIR"/0*.yaml; do
    name=$(basename "$config")
    echo "=== Running $name ==="
    aidrin batch "$config" --no-viz -v
    echo
done

echo "All demos complete."
