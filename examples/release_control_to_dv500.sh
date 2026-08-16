#!/usr/bin/env bash
set -u

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
deadline=$(( $(date +%s) + 60 ))
attempt=0
last_status=1

while (( $(date +%s) < deadline )); do
    attempt=$((attempt + 1))
    remaining=$(( deadline - $(date +%s) ))
    echo "[release] attempt ${attempt}; ${remaining}s budget remaining"

    timeout --foreground --signal=INT "${remaining}s" \
        python3 "${script_dir}/release_control_to_dv500.py" "$@"
    last_status=$?
    if (( last_status == 0 )); then
        exit 0
    fi

    remaining=$(( deadline - $(date +%s) ))
    if (( remaining <= 10 )); then
        break
    fi
    echo "[release] retrying in 10 seconds"
    sleep 10
done

echo "[FAIL] release control did not succeed within 60 seconds" >&2
exit "${last_status}"
