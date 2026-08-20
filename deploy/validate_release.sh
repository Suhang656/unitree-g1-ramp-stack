#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

find "$ROOT/deploy" "$ROOT/bin" "$ROOT/runtime/scripts" \
  -maxdepth 1 -type f \
  \( -name '*.sh' -o -path "$ROOT/bin/*" \) \
  -print0 | xargs -0 -n1 bash -n

/usr/bin/python3 -m compileall -q \
  "$ROOT/runtime/app" \
  "$ROOT/runtime/ros2" \
  "$ROOT/runtime/scripts" \
  "$ROOT/tests"

(
  cd "$ROOT"
  /usr/bin/python3 -m unittest discover -s tests -v
)

if [[ "${1:-}" == "--check-g1" ]]; then
  bash "$ROOT/deploy/check_prerequisites.sh"
fi

echo "G1_RELEASE_VALIDATION_OK"
