#!/usr/bin/env bash
# Ubuntu launcher: stop listeners on the chosen TCP port, then run Flask.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

if (( $# > 1 )); then
    echo "Usage: $0 [port]" >&2
    exit 1
fi
port="${1:-${PORT:-5000}}"
if [[ ! "$port" =~ ^[0-9]{1,5}$ ]]; then
    echo "Port must be an integer from 1 to 65535." >&2
    exit 1
fi
port=$((10#$port))
if (( port < 1 || port > 65535 )); then
    echo "Port must be an integer from 1 to 65535." >&2
    exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
    echo "Missing .venv/bin/python. Follow the Python setup in README.md first." >&2
    exit 1
fi
if ! command -v lsof >/dev/null 2>&1; then
    echo "Install the port lookup utility: sudo apt install lsof" >&2
    exit 1
fi
if ! .venv/bin/python -c 'import dotenv' >/dev/null 2>&1; then
    echo "Missing runner dependency. Install requirements.lock.txt into .venv first." >&2
    exit 1
fi

listeners() {
    lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true
}
mapfile -t pids < <(listeners)
if (( ${#pids[@]} )); then
    echo "Stopping TCP listeners on port $port (PIDs: ${pids[*]})..."
    for pid in "${pids[@]}"; do
        if ! kill -TERM "$pid" 2>/dev/null && kill -0 "$pid" 2>/dev/null; then
            echo "Cannot stop PID $pid. Stop it as its owner, or choose another port." >&2
            exit 1
        fi
    done
    # Allow graceful shutdown before force-stopping original listeners still present.
    for (( attempt=0; attempt<50; attempt++ )); do
        [[ -z "$(listeners)" ]] && break
        sleep 0.1
    done
    mapfile -t remaining < <(listeners)
    for pid in "${remaining[@]}"; do
        for original in "${pids[@]}"; do
            if [[ "$pid" == "$original" ]]; then
                echo "Force-stopping PID $pid..."
                kill -KILL "$pid" 2>/dev/null || true
            fi
        done
    done
    for (( attempt=0; attempt<20; attempt++ )); do
        [[ -z "$(listeners)" ]] && break
        sleep 0.1
    done
    if [[ -n "$(listeners)" ]]; then
        echo "Port $port is still occupied. Stop its service or choose another port." >&2
        exit 1
    fi
fi

export PORT="$port"
echo "Starting Flask: http://127.0.0.1:$port (Ctrl+C to stop)"
exec "$project_dir/.venv/bin/python" -u "$project_dir/run.py"
