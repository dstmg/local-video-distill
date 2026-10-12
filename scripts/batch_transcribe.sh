#!/usr/bin/env bash
# 批量转写一个目录下的所有视频
#
# 用法:
#   bash batch_transcribe.sh <视频目录> <输出目录> [数量上限]
#
# 例:
#   bash batch_transcribe.sh "G:/课程视频" ./out/batch 20
set -u
SRC="${1:?用法: bash batch_transcribe.sh <视频目录> <输出目录> [数量]}"
DST="${2:?用法: bash batch_transcribe.sh <视频目录> <输出目录> [数量]}"
LIMIT="${3:-0}"

HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${VIDEO_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY="python"

mkdir -p "$DST"
[ "$LIMIT" -gt 0 ] && mkdir -p "$DST/_selected"

echo "==========================================="
echo "批量转写：$SRC"
echo "输出到  ：$DST"
[ "$LIMIT" -gt 0 ] && echo "数量上限：$LIMIT"
echo "==========================================="
echo

total=0; ok=0; fail=0; skip=0
failed_list=""

for f in "$SRC"/*.mp4; do
  [ -f "$f" ] || continue
  total=$((total + 1))

  [ "$LIMIT" -gt 0 ] && [ "$total" -gt "$LIMIT" ] && break

  name=$(basename "$f" .mp4)
  # 用抖音ID或前30字符做子目录名，避免文件名过长
  id=$(echo "$name" | grep -oE '^[0-9]+' | head -1)
  [ -z "$id" ] && id=$(echo "$name" | cut -c1-30)
  out="$DST/$id"

  # 已转写过则跳过（幂等）
  if [ -s "$out/原始提取.md" ]; then
    printf "  [跳过] %s\n" "$id"
    skip=$((skip + 1))
    continue
  fi

  printf "  [%d] %s ... " "$total" "$id"
  if "$PY" "$HERE/transcribe.py" "$f" "$out" >"$out.log" 2>&1 || [ -s "$out/原始提取.md" ]; then
    segs=$(grep -c '^\[' "$out/原始提取.md" 2>/dev/null || echo 0)
    echo "OK (${segs}段)"
    ok=$((ok + 1))
    [ "$LIMIT" -gt 0 ] && cp "$f" "$DST/_selected/$id.mp4" 2>/dev/null
  else
    echo "失败"
    fail=$((fail + 1))
    failed_list="$failed_list $id"
  fi
  rm -f "$out.log"
done

echo
echo "==========================================="
echo "完成：共 $total 个 | 成功 $ok | 失败 $fail | 跳过 $skip"
[ -n "$failed_list" ] && echo "失败：$failed_list"
echo "输出目录：$DST"
echo "==========================================="
