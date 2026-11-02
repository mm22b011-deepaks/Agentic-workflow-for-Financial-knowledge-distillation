#!/usr/bin/env bash
set -euo pipefail
checkout=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$checkout"
action=${1:-bootstrap}
if (($#)); then shift; fi
mise_bin=$(command -v mise || true)
if [[ -z "$mise_bin" ]]; then mise_bin="$checkout/.tools/bin/mise"; fi
if [[ "$action" == bootstrap ]]; then
  for required in curl tar make git; do
    command -v "$required" >/dev/null || { echo "Missing system prerequisite: $required" >&2; exit 2; }
  done
  [[ $(uname -s) == Linux ]] || { echo 'This launcher currently supports native Linux.' >&2; exit 2; }
  if [[ ! -x "$mise_bin" ]]; then
    mkdir -p "$checkout/.tools/bin"
    installer=$(mktemp)
    trap 'rm -f "$installer"' EXIT
    curl --fail --silent --show-error --location https://mise.run --output "$installer"
    MISE_INSTALL_PATH="$mise_bin" MISE_VERSION=v2026.10.25 sh "$installer"
  fi
  "$mise_bin" trust "$checkout/mise.toml"
  "$mise_bin" install
  "$mise_bin" exec -- uv sync --locked --python 3.12.12 --extra dev
  "$mise_bin" exec -- npm --prefix web ci
  "$mise_bin" exec -- make references web-build
  exit
fi
[[ -x "$mise_bin" ]] || { echo 'Run setup.sh bootstrap first.' >&2; exit 2; }
case "$action" in
  cli) exec "$mise_bin" exec -- .venv/bin/python -m nowcast.app "$@" ;;
  website) exec "$mise_bin" exec -- .venv/bin/python -m nowcast.app serve "$@" ;;
  demo) exec "$mise_bin" exec -- make demo ;;
  check) exec "$mise_bin" exec -- make check ;;
  *) echo 'Usage: setup.sh {bootstrap|cli|website|demo|check}' >&2; exit 2 ;;
esac
