#!/usr/bin/env bash
# Sets up PyGitDatBack's environment with uv and launches the app.
# Any arguments are passed on to the app, e.g. `./launch.sh --debug` or `./launch.sh --no-ui`.

set -eo pipefail

THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# Must match VENV_PATH in src/systemd/systemd_cmds.py: the background service runs this venv's python
export UV_PROJECT_ENVIRONMENT="$HOME/.local/share/r0fld4nc3/PyGitDatBack/PyGitDatBack.venv"

if ! command -v uv &> /dev/null; then
    echo "Error: uv is required but was not found on PATH."
    echo "Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Create venv and sync project.
uv sync --project "$THIS_DIR" --quiet

exec uv run --project "$THIS_DIR" --no-sync python "$THIS_DIR/src/main.py" "$@"
