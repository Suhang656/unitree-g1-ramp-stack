#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="$ROOT/g1_embodied_lab_panorama_v2_nx_reference.pcd"
EXPECTED="ca085ee9796feb252521228b1e3fb375985cee87c1a2a2fc46116cecfa8c05c3"

cat \
  "$ROOT/g1_embodied_lab_panorama_v2_nx_reference.pcd.part-000" \
  "$ROOT/g1_embodied_lab_panorama_v2_nx_reference.pcd.part-001" \
  "$ROOT/g1_embodied_lab_panorama_v2_nx_reference.pcd.part-002" \
  "$ROOT/g1_embodied_lab_panorama_v2_nx_reference.pcd.part-003" \
  >"$OUTPUT.tmp"

ACTUAL="$(sha256sum "$OUTPUT.tmp" | awk '{print $1}')"

if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  rm -f "$OUTPUT.tmp"
  echo "参考点云校验失败：$ACTUAL" >&2
  exit 1
fi

mv "$OUTPUT.tmp" "$OUTPUT"
echo "参考点云重组完成：$OUTPUT"
echo "SHA256：$ACTUAL"
