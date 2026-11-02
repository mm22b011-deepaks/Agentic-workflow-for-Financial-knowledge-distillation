#!/usr/bin/env bash
set -euo pipefail
checkout=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$checkout"
.venv/bin/python scripts/scan_secrets.py --history HEAD^..HEAD
output=${1:-tresata-source.zip}
# Export committed source only; ignored local credentials and artifacts cannot enter.
git archive --format=zip --output="$output" HEAD -- . ':!**/.env' ':!.env' ':!.git' ':!data' ':!**/node_modules' ':!**/__pycache__/**' ':!**/.pytest_cache/**' ':!**/.mypy_cache/**' ':!**/.ruff_cache/**' ':!**/.cache/**' ':!**/*.zip' ':!*.zip' ':!**/test-results' ':!.hypothesis' ':!**/.coverage*'
.venv/bin/python - "$output" <<'PY'
import sys, zipfile
from pathlib import PurePosixPath
with zipfile.ZipFile(sys.argv[1]) as archive:
    for name in archive.namelist():
        parts=PurePosixPath(name).parts
        assert not {'.env','.git','data','node_modules','test-results','.hypothesis'} & set(parts), 'forbidden archive entry'
        assert not name.endswith('.zip'), 'nested archive'
print('Source archive verified')
PY
