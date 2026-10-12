#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_terms.py — 对已有 MT 产物做术语纠错（无需重新转写）

用法:
    python fix_terms.py <文件或目录> [...]        # 原地修正 md/json
    python fix_terms.py <目录> --dry-run          # 只看会改什么，不落盘
    python fix_terms.py <目录> --out <新目录>     # 输出到别处（保留原文件）

术语表：同目录 terms_ecommerce.json（也支持 terms_custom.json）
        自己加词就新建 terms_custom.json，格式见 terms_ecommerce.json。

典型场景：转写时忘了开术语纠错，或想事后调整术语表再重跑一遍。
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EX_DIR = os.path.join(os.path.dirname(HERE), "examples")


def load_fixes():
    """terms_custom.json 优先 → scripts/terms_*.json → examples/terms_*.example.json"""
    fixes = []
    seen = set()
    cands = []
    custom = os.path.join(HERE, "terms_custom.json")
    if os.path.isfile(custom):
        cands.append(custom)
    for d in (HERE, EX_DIR):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if (name.startswith("terms_") and name.endswith(".json")
                    and name != "terms_custom.json"
                    and os.path.join(d, name) not in cands):
                cands.append(os.path.join(d, name))

    for p in cands:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # noqa: BLE001
            print(f"[警告] 读取 {os.path.basename(p)} 失败：{e}", file=sys.stderr)
            continue
        for group, mapping in data.items():
            if group.startswith("_") or not isinstance(mapping, dict):
                continue
            for wrong, right in mapping.items():
                if wrong and right and wrong != right and wrong not in seen:
                    seen.add(wrong)
                    fixes.append((wrong, right))
    # 长词优先，避免短词先替换破坏长词
    fixes.sort(key=lambda x: -len(x[0]))
    return fixes


def apply(text, fixes):
    total = 0
    hits = {}
    for wrong, right in fixes:
        if wrong in text:
            n = text.count(wrong)
            text = text.replace(wrong, right)
            total += n
            hits[wrong] = hits.get(wrong, 0) + n
    return text, total, hits


# ============ 拼音模糊纠错（可选，需 pypinyin）============
try:
    from pypinyin import lazy_pinyin, Style
    _HAVE_PINYIN = True
except ImportError:
    _HAVE_PINYIN = False

_PY_CACHE = {}
_CJK_WORD_RE = re.compile(r"[一-龥]{2,5}")
_win_lens = []   # 术语长度集合（降序），初始化时填充


def _is_cjk(ch):
    return "一" <= ch <= "龥"

# 常见日常词白名单：即使拼音与术语撞上也不替换（防误伤）
_COMMON_CN = {
    "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "为了", "因为", "所以",
    "可以", "需要", "应该", "现在", "开始", "结束", "问题", "方法", "方式", "情况",
    "时间", "地方", "东西", "结果", "过程", "内容", "部分", "进行", "实现", "操作",
    "第一", "第二", "第三", "一个", "一些", "这些", "那些", "自己", "其他", "很多",
    "重点", "主要", "关键", "核心", "重要", "直接", "简单", "复杂", "方便", "灵活",
}


def _pinyin(word):
    if word not in _PY_CACHE:
        _PY_CACHE[word] = "".join(lazy_pinyin(word, style=Style.NORMAL))
    return _PY_CACHE[word]


def _pinyin_hits(text, correct_words, max_scan=200000):
    """扫文本里的中文词，若拼音**唯一**匹配某个正确术语且该词本身不是术语，则替换。

    保守策略（避免误伤日常词）：
      1. 拼音必须**唯一**对应一个术语——若多个术语同音则跳过（无法判断该用哪个）
      2. 命中词本身已在正确术语表中 → 跳过（本来就是对的）
      3. 命中词在常见词白名单 → 跳过
    所有替换都会记录下来供人工复核。
    """
    if not _HAVE_PINYIN or not correct_words:
        return text, 0, {}

    # 拼音 → 正确术语（**去重**：多个错词可能映射到同一正确词，如 期款/企款 → 起款）
    right_py = {}
    term_set = set()
    for w in set(correct_words):          # 去重是关键
        try:
            py = _pinyin(w)
        except Exception:  # noqa: BLE001
            continue
        right_py.setdefault(py, set()).add(w)
        term_set.add(w)
    # 只保留拼音唯一对应一个术语的（同音歧义无法判断该用哪个 → 跳过）
    unique_py = {}
    for py, ws in right_py.items():
        if len(ws) == 1:
            unique_py[py] = next(iter(ws))
    if not unique_py:
        return text, 0, {}

    # 窗口长度降序（长词优先），最多 6 字
    global _win_lens
    _win_lens = sorted({len(w) for w in term_set}, reverse=True)
    _win_lens = [x for x in _win_lens if 2 <= x <= 6] or [2, 3, 4]

    replaced = 0
    hits = {}
    out = []
    pos = 0
    scanned = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # 只在汉字处尝试滑动窗口；非汉字直接输出
        if not _is_cjk(ch):
            out.append(text[pos:i + 1])
            pos = i + 1
            i += 1
            continue
        matched = None
        # 窗口长度 = 术语长度倒序（长词优先，避免短词先截断）
        for wl in _win_lens:
            word = text[i:i + wl]
            if len(word) < wl or not all(_is_cjk(c) for c in word):
                continue
            scanned += 1
            if scanned > max_scan:
                break
            if word in term_set or word in _COMMON_CN:
                continue
            try:
                py = _pinyin(word)
            except Exception:  # noqa: BLE001
                continue
            cand = unique_py.get(py)
            if cand and cand != word:
                matched = (word, cand)
                break
        if matched:
            word, cand = matched
            out.append(text[pos:i])
            out.append(cand)
            replaced += 1
            key = f"{word}→{cand}"
            hits[key] = hits.get(key, 0) + 1
            pos = i + len(word)
            i = pos
        else:
            i += 1
    out.append(text[pos:])
    return "".join(out), replaced, hits


def collect_correct_words(fixes):
    return [r for _w, r in fixes]


def process_md(path, fixes, dry_run, out_path=None, use_pinyin=False):
    with open(path, encoding="utf-8") as f:
        orig = f.read()
    new, total, hits = apply(orig, fixes)
    if use_pinyin and _HAVE_PINYIN:
        new, n2, h2 = _pinyin_hits(new, collect_correct_words(fixes))
        if n2:
            total += n2
            for k, v in h2.items():
                hits[k] = hits.get(k, 0) + v
    if total == 0 and (not out_path or os.path.abspath(out_path) == os.path.abspath(path)):
        return 0, {}
    if not dry_run:
        dest = out_path or path
        with open(dest, "w", encoding="utf-8") as f:
            f.write(new)
    return total, hits


def process_json(path, fixes, dry_run, out_path=None):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    total = 0
    hits = {}
    segs = data.get("segments")
    if isinstance(segs, list):
        for s in segs:
            if isinstance(s, dict) and isinstance(s.get("text"), str):
                nt, n, h = apply(s["text"], fixes)
                if n:
                    s["text"] = nt
                    total += n
                    for k, v in h.items():
                        hits[k] = hits.get(k, 0) + v
    if not dry_run and (total or (out_path and os.path.abspath(out_path) != os.path.abspath(path))):
        dest = out_path or path
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return total, hits


def collect(target):
    """展开目标：文件或目录（递归找 原始提取.md / 原始提取.json）"""
    files = []
    if os.path.isfile(target):
        files.append(target)
        return files
    for root, _dirs, names in os.walk(target):
        for n in names:
            if n in ("原始提取.md", "原始提取.json"):
                files.append(os.path.join(root, n))
    return files


def main():
    ap = argparse.ArgumentParser(description="MT 术语纠错")
    ap.add_argument("targets", nargs="+", help="文件或目录")
    ap.add_argument("--dry-run", action="store_true", help="只看统计，不改文件")
    ap.add_argument("--out", help="输出目录（原文件保留）")
    ap.add_argument("--pinyin", action="store_true",
                    help="启用拼音模糊纠错（需 pip install pypinyin）")
    args = ap.parse_args()

    fixes = load_fixes()
    if not fixes:
        print("[错误] 未找到术语表（terms_*.json）", file=sys.stderr)
        return 1

    print(f"术语表已加载：{len(fixes)} 条规则")
    if args.pinyin:
        print("拼音模糊纠错：" + ("已启用" if _HAVE_PINYIN
              else "不可用（请 pip install pypinyin）"))
    print(f"模式：{'试运行（不改文件）' if args.dry_run else '原地修正'}")
    print()

    grand_total = 0
    grand_hits = {}
    n_files = 0

    for target in args.targets:
        files = collect(target)
        if not files:
            print(f"[跳过] {target}（未找到 MT 产物）")
            continue
        for p in files:
            n_files += 1
            if args.out:
                import hashlib
                base = target if os.path.isdir(target) else os.path.dirname(os.path.abspath(target))
                rel = os.path.relpath(p, base)
                if len(args.targets) > 1:
                    prefix = os.path.basename(os.path.abspath(target)) + "-" + hashlib.sha256(os.path.abspath(target).encode()).hexdigest()[:8]
                    rel = os.path.join(prefix, rel)
                out_path = os.path.abspath(os.path.join(args.out, rel))
                if os.path.commonpath([os.path.abspath(args.out), out_path]) != os.path.abspath(args.out):
                    raise ValueError("校对输出路径越出目标目录")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
            else:
                out_path = p

            if p.endswith(".md"):
                total, hits = process_md(p, fixes, args.dry_run, out_path, args.pinyin)
            else:
                total, hits = process_json(p, fixes, args.dry_run, out_path)

            grand_total += total
            for k, v in hits.items():
                grand_hits[k] = grand_hits.get(k, 0) + v

    print(f"处理 {n_files} 个文件，共替换 {grand_total} 处")
    if grand_hits:
        print("\n命中明细（错词 → 替换次数）：")
        for w, n in sorted(grand_hits.items(), key=lambda x: -x[1]):
            right = dict(fixes).get(w, "?")
            print(f"  {w} → {right:<8} {n:>4} 次")
    else:
        print("\n没有命中任何错词（可能已经修正过，或术语表需按你的领域扩充）")
    return 0


if __name__ == "__main__":
    sys.exit(main())