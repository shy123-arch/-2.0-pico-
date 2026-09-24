#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -n "${PYTHON:-}" ]]; then
    python_bin="${PYTHON}"
elif [[ -x ".venv/bin/python" ]]; then
    python_bin=".venv/bin/python"
else
    python_bin="python3"
fi

# Keep this app isolated even if the caller's shell has another venv or
# Conda environment active.
unset PYTHONHOME
unset PYTHONPATH
unset QT_PLUGIN_PATH
unset QML2_IMPORT_PATH
export PYTHONNOUSERSITE=1
if [[ "${python_bin}" == ".venv/bin/python" ]]; then
    export VIRTUAL_ENV="$PWD/.venv"
    export PATH="$VIRTUAL_ENV/bin:${PATH}"
fi
export QT_IM_MODULE=xim

if ! "${python_bin}" - <<'PY' >/dev/null 2>&1
try:
    import PySide6  # noqa: F401
except ModuleNotFoundError:
    import PyQt6  # noqa: F401
PY
then
    echo "Missing Qt Python binding."
    echo "Install one of:"
    echo "  ${python_bin} -m pip install PySide6"
    echo "  ${python_bin} -m pip install PyQt6"
    exit 1
fi

exec "${python_bin}" -m holoteleop_app.main
