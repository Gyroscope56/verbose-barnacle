#!/usr/bin/env bash
# Copy the shared backend into an App Lab app directory before transferring it.
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app_dir="${1:-$(dirname "$here")}"
destination="$app_dir/python/lakebase_backend"
if [[ ! -f "$app_dir/app.yaml" || ! -d "$app_dir/python" ]]; then
    echo "Expected the path to a ParkSight App Lab directory." >&2
    exit 1
fi
mkdir -p "$destination"
for module in garage lakebase spot_updater; do
    install -m 0644 "$here/../../$module.py" "$destination/$module.py"
done
touch "$destination/__init__.py"
