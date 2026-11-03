#!/usr/bin/env bash
set -euo pipefail
checkout=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$checkout"
.venv/bin/python scripts/scan_secrets.py --history HEAD^..HEAD
output=${1:-tresata-source.zip}
# Export committed source and the allowlisted public data bundle.
git archive --format=zip --output="$output" HEAD -- . ':!**/.env' ':!.env' ':!.git' ':!**/node_modules' ':!**/__pycache__/**' ':!**/.pytest_cache/**' ':!**/.mypy_cache/**' ':!**/.ruff_cache/**' ':!**/.cache/**' ':!**/*.zip' ':!*.zip' ':!**/test-results' ':!.hypothesis' ':!**/.coverage*'
.venv/bin/python - "$output" <<'PY'
import sys, zipfile
from pathlib import PurePosixPath
from nowcast.offline import PUBLIC_FILES
allowed = {'data/offline/' + name for name in PUBLIC_FILES}
with zipfile.ZipFile(sys.argv[1]) as archive:
    for name in archive.namelist():
        parts=PurePosixPath(name).parts
        assert not {'.env','.git','node_modules','test-results','.hypothesis'} & set(parts), 'forbidden archive entry'
        if parts[0] == 'data':
            assert name in allowed or (name.endswith('/') and any(path.startswith(name) for path in allowed)), 'private data in archive'
        assert not name.endswith('.zip'), 'nested archive'
print('Source and public offline data archive verified')
PY
