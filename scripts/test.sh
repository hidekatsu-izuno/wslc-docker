#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m unittest discover -s "$package_dir/tests" -v
if python3 -c 'import pytest' >/dev/null 2>&1; then
    python3 -m pytest -q "$package_dir/vendor/wslc-compose/tests"
else
    echo 'pytest is unavailable; skipping vendored wslc-compose tests (CI installs python3-pytest).'
fi
