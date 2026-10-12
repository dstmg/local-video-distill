#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_skill.py — 技能包完整性校验器

用法:
    python validate_skill.py <技能目录> [<技能目录> ...]
    python validate_skill.py <技能目录> --require-anchors 5   # 强制每张能力卡至少 N 个时间锚点

检查项：
  1. frontmatter 存在且 name == 目录名（否则宿主加载不到）
  2. frontmatter 的 capability-count 与实际能力卡数一致
  3. 路由表引用的文件全部存在（无断链）
  4. 名称合法（只含小写字母/数字/连字符）
  5. 存在 references/ 目录与术语表
  6. 可选：能力卡内时间锚点数量

退出码：0 = 全部通过；1 = 有错误
"""
import argparse
import os
import re
import sys

OK = "\033[32m✓\033[0m"
BAD = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"


def parse_frontmatter(path):
    """返回 (dict, raw_fm_text) 或 (None, None)"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None, None
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return None, None
    fm = "\n".join(lines[1:end])
    d = {}
    for l in fm.splitlines():
        if ":" in l and not l.startswith((" ", "\t")):
            k, v = l.split(":", 1)
            d[k.strip()] = v.strip()
    return d, fm


def count_anchors(path):
    """统计文本里的时间锚点数（mm:ss / 视频ID+时间 等）"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return 0
    n = len(re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", raw))
    n += len(re.findall(r"\b\d{10,20}\b", raw))   # 视频ID式锚点
    return n


def validate(skill_dir, require_anchors=0):
    errs, warns, oks = [], [], []

    def ok(m): oks.append(m)
    def bad(m): errs.append(m)
    def warn(m): warns.append(m)

    skill_md = os.path.join(skill_dir, "SKILL.md")
    dirname = os.path.basename(os.path.normpath(skill_dir))

    # 1. SKILL.md 存在
    if not os.path.isfile(skill_md):
        bad(f"缺少 SKILL.md：{skill_md}")
        return oks, errs, warns
    ok("SKILL.md 存在")

    # 2. frontmatter
    fm, fmraw = parse_frontmatter(skill_md)
    if fm is None:
        bad("frontmatter 缺失或格式错误（首行必须是 ---）")
        return oks, errs, warns
    ok("frontmatter 格式正确")

    name = fm.get("name", "")
    if not name:
        bad("frontmatter 缺少 name 字段")
    elif name != dirname:
        bad(f"name 与目录名不一致：name={name!r} 目录={dirname!r}"
            f"（宿主按目录名加载，不一致会导致技能无法触发）")
    else:
        ok(f"name == 目录名（{name}）")

    # 4. 名称合法性
    if name and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        bad(f"name 含非法字符（只允许小写字母/数字/连字符）：{name!r}")

    if not fm.get("description", "").strip():
        bad("frontmatter 缺少 description")
    else:
        ok("description 非空")

    # 3. capability-count 与实际张数
    caps_dir = os.path.join(skill_dir, "references", "capabilities")
    actual_caps = 0
    if os.path.isdir(caps_dir):
        actual_caps = len([f for f in os.listdir(caps_dir) if f.endswith(".md")])

    declared = None
    m = re.search(r"capability-count:\s*(\d+)", fmraw or "")
    if m:
        declared = int(m.group(1))
        if actual_caps == 0:
            warn(f"声明了 {declared} 张能力卡，但 references/capabilities/ 不存在或为空")
        elif declared != actual_caps:
            bad(f"capability-count 声明 {declared}，实际 {actual_caps} 张能力卡")
        else:
            ok(f"capability-count 一致（{declared}）")
    else:
        if actual_caps:
            warn("有能力卡但未声明 capability-count")

    # 4. 断链检查
    with open(skill_md, encoding="utf-8") as f:
        raw = f.read()
    refs = set(re.findall(r"references/[A-Za-z0-9_\-/]+\.(?:md|html|py|json)", raw))
    broken = [r for r in sorted(refs) if not os.path.isfile(os.path.join(skill_dir, r))]
    if broken:
        for b in broken:
            bad(f"路由表断链：{b}")
    elif refs:
        ok(f"路由表引用 {len(refs)} 个文件，全部存在")
    else:
        warn("SKILL.md 里没有引用任何 references 文件")

    # 5. references 目录
    if os.path.isdir(os.path.join(skill_dir, "references")):
        ok("references/ 目录存在")
    else:
        warn("没有 references/ 目录")

    # 6. 术语表
    gloss = os.path.join(skill_dir, "references", "glossary.md")
    if os.path.isfile(gloss):
        n = len(re.findall(r"^##\s", open(gloss, encoding="utf-8").read(), re.M))
        ok(f"术语表存在（{n} 条）")
    else:
        warn("没有 glossary.md 术语表")

    # 7. 时间锚点
    if require_anchors > 0 and os.path.isdir(caps_dir):
        for f in sorted(os.listdir(caps_dir)):
            if not f.endswith(".md"):
                continue
            n = count_anchors(os.path.join(caps_dir, f))
            if n < require_anchors:
                bad(f"能力卡 {f} 只有 {n} 个时间锚点（要求 ≥{require_anchors}）")
            else:
                ok(f"能力卡 {f}：{n} 个时间锚点")

    return oks, errs, warns


def main():
    ap = argparse.ArgumentParser(description="技能包完整性校验")
    ap.add_argument("dirs", nargs="+", help="技能目录（含 SKILL.md 的那一层）")
    ap.add_argument("--require-anchors", type=int, default=0,
                    help="每张能力卡至少应有 N 个时间锚点")
    args = ap.parse_args()

    total_err = 0
    for d in args.dirs:
        print(f"\n{'='*62}")
        print(f" 校验：{d}")
        print("=" * 62)
        oks, errs, warns = validate(d, args.require_anchors)
        for m in oks:
            print(f"  {OK} {m}")
        for m in warns:
            print(f"  {WARN} {m}")
        for m in errs:
            print(f"  {BAD} {m}")
        print(f"\n  通过 {len(oks)} | 警告 {len(warns)} | 错误 {len(errs)}")
        total_err += len(errs)

    print()
    if total_err:
        print(f"{BAD} 共 {total_err} 个错误，请修复后再发布。")
        return 1
    print(f"{OK} 全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())