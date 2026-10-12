#!/usr/bin/env bash
# 下载 faster-whisper 模型到本地目录（绕过国内镜像的 307 重定向 bug + 大文件被代理拦截）
#
# 用法:
#   bash download_model.sh tiny|base|small|medium|large-v3
#
# 为什么需要这个脚本？
#   1) hf-mirror.com 返回 307 重定向到 /api/resolve-cache/...，
#      huggingface_hub 某些版本处理这个新路径有 bug，会下载中断留下 0 字节文件，
#      之后 ctranslate2 报 "json parse error: unexpected end of input"（极具误导性）。
#   2) 大文件（model.bin 几百MB）容易被代理拦截返回 502，
#      所以这里用分段 Range 请求逐块下，每块失败自动重试。
#
# 特性:
#   - 分段下载（每块 4MB），单块失败不影响整体
#   - 断点续传：已完成的部分跳过
#   - 0 字节残骸自动清理
#   - 下载后校验 4 个必需文件齐全
set -u
MODEL="${1:-small}"
DEST="${VIDEO_MODEL_DIR:-$HOME/faster-whisper-models}/$MODEL"
HOST="${HF_MIRROR:-https://hf-mirror.com}"
BASE="$HOST/Systran/faster-whisper-$MODEL/resolve/main"
CHUNK=$((4 * 1024 * 1024))   # 4MB/块

# 用于 JSON 完整性校验的解释器
PYTHON_BIN="${VIDEO_PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"

case "$MODEL" in
  tiny|base|small|medium|large-v3) ;;
  *) echo "未知模型: $MODEL（可选 tiny/base/small/medium/large-v3）"; exit 1 ;;
esac

FILES="config.json tokenizer.json vocabulary.txt model.bin"

echo "==========================================="
echo " 下载 $MODEL  ->  $DEST"
echo "==========================================="
mkdir -p "$DEST"

# ---------- 小文件：直接下 ----------
# 注意：这里刻意不用 curl -C -（续传）。若上次中断留下残片，续传会把残片当完整文件保留，
# 导致 tokenizer.json 变成"开头正常、结尾截断"的坏文件，模型加载时报 tokenizers 错误。
# 小文件直接整份重下更稳妥。
for f in config.json tokenizer.json vocabulary.txt; do
  out="$DEST/$f"
  if [ -s "$out" ] && head -c 1 "$out" 2>/dev/null | grep -q '{'; then
    echo "  [跳过] $f  ($(stat -c%s "$out") 字节)"
    continue
  fi
  [ -f "$out" ] && rm -f "$out"
  printf "  [下载] %-16s " "$f"
  code=$(curl -sL --retry 3 --retry-delay 2 --connect-timeout 20 --max-time 600 \
         -w "%{http_code}" -o "$out" "$BASE/$f" 2>/dev/null)
  sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
  if [ "$sz" -gt 0 ]; then echo "OK ($sz 字节)"; else echo "失败 http=$code"; rm -f "$out"; fi
done

# ---------- 大文件：分段下载 ----------
MODEL_BIN="$DEST/model.bin"
if [ -s "$MODEL_BIN" ]; then
  echo "  [跳过] model.bin  ($(stat -c%s "$MODEL_BIN") 字节)"
else
  echo "  [下载] model.bin（分段，每块 $((CHUNK/1024/1024))MB，受网络影响可能需几分钟）"

  # 先探总量
  TOTAL=$(curl -sIL --connect-timeout 20 --max-time 60 "$BASE/model.bin" 2>/dev/null \
          | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v+0}')
  if [ "$TOTAL" -le 0 ]; then
    echo "    无法获取文件大小，尝试整文件下载…"
    curl -L --retry 3 --connect-timeout 20 --max-time 3600 \
         -C - -o "$MODEL_BIN" "$BASE/model.bin" 2>/dev/null
  else
    echo "    总大小: $TOTAL 字节 ($((TOTAL/1024/1024)) MB)"
    chunks=$(( (TOTAL + CHUNK - 1) / CHUNK ))
    for i in $(seq 0 $((chunks - 1))); do
      start=$(( i * CHUNK ))
      end=$(( start + CHUNK - 1 ))
      [ "$end" -ge "$TOTAL" ] && end=$(( TOTAL - 1 ))
      # 已下载的块跳过（简单判断：目标文件已够大）
      cur=$(stat -c%s "$MODEL_BIN" 2>/dev/null || echo 0)
      [ "$cur" -ge "$((end + 1))" ] && continue

      printf "\r    块 %d/%d  (%d%%)   " "$((i+1))" "$chunks" "$(( (end+1)*100/TOTAL ))"
      curl -sL --retry 5 --retry-delay 3 --connect-timeout 20 --max-time 900 \
           -r "$start-$end" "$BASE/model.bin" >> "$MODEL_BIN" 2>/dev/null
    done
    echo ""
  fi

  got=$(stat -c%s "$MODEL_BIN" 2>/dev/null || echo 0)
  if [ "$got" -le 0 ]; then
    echo "    model.bin 下载失败（可能被代理拦截 502）"
    echo "    试试：关掉 Clash/代理后重跑本脚本，或换用离线下载后手动放入该目录"
    rm -f "$MODEL_BIN"
  else
    echo "    model.bin 完成: $got 字节"
  fi
fi

# ---------- 校验 ----------
echo
echo "校验结果："
ok=1
for f in $FILES; do
  if [ -s "$DEST/$f" ]; then
    echo "  OK      $f  $(stat -c%s "$DEST/$f") 字节"
  else
    echo "  缺失    $f"; ok=0
  fi
done

# JSON 完整性校验：防止续传残片导致"开头正常结尾截断"的坏文件
for f in config.json tokenizer.json; do
  if [ -s "$DEST/$f" ]; then
    if ! "$PYTHON_BIN" -c "import json,sys;json.load(open(sys.argv[1],encoding='utf-8'))" "$DEST/$f" 2>/dev/null; then
      echo "  损坏    $f  不是完整 JSON（可能是续传残片），已删除请重跑"
      rm -f "$DEST/$f"; ok=0
    fi
  fi
done

# model.bin 至少要有合理大小（tiny 75MB / small 483MB / medium 1.5GB）
if [ -s "$DEST/model.bin" ]; then
  BIN=$(stat -c%s "$DEST/model.bin")
  case "$MODEL" in
    tiny)   MIN=50000000  ;;
    base)   MIN=100000000 ;;
    small)  MIN=400000000 ;;
    medium) MIN=1200000000 ;;
    *)      MIN=10000000;;
  esac
  if [ "$BIN" -lt "$MIN" ]; then
    echo "  可疑    model.bin 仅 $BIN 字节（$MODEL 应≥$MIN），可能未下完，已删除请重跑"
    rm -f "$DEST/model.bin"; ok=0
  fi
fi

if [ "$ok" -eq 0 ]; then
  echo
  echo "校验未通过。可重新运行本脚本（分段下载会续传 model.bin）。"
  echo "若 model.bin 反复失败，多半是代理拦截大文件——请关掉 Clash 等代理后重试。"
  exit 1
fi

echo
echo "全部完成。transcribe.py 会自动使用该模型。也可手动指定："
echo "  MODEL=\"$DEST\" python transcribe.py 你的视频.mp4 输出目录"