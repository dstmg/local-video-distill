#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guide_builder.py — 学习指南生成器（Stage 3）

从结构化 JSON 生成单页 HTML 学习指南，并**内置规范校验**（对照 teaching-note-spec.md）。

设计意图：让 AI 只负责「填内容」，格式与合规由脚本保证。

用法:
    # 1) 看模板 JSON 的完整结构（照着填）
    python guide_builder.py --print-schema

    # 2) 从 JSON 生成 HTML（生成前自动校验）
    python guide_builder.py content.json -o 学习指南.html

    # 3) 只校验已有 JSON（不生成）
    python guide_builder.py content.json --check-only

    # 4) 校验已生成的 HTML 是否合规
    python guide_builder.py --validate-html 学习指南.html

输入 JSON 结构见 --print-schema 输出，或 references/guide-content-schema.json。
"""
import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(os.path.dirname(HERE), "references",
                        "learning-guide-template.html")

# teaching-note-spec.md 要求的 9 个章节（顺序固定）
REQUIRED_SECTIONS = [
    ("overview", "总览"),
    ("prereq", "前置知识"),
    ("concepts", "核心概念"),
    ("steps", "步骤清单"),
    ("pit", "常见误区"),
    ("example", "实例演算"),
    ("quiz", "自测题"),
    ("next", "下一步"),
    ("src", "原文索引"),
]

SCHEMA = {
    "title": "学习指南标题",
    "subtitle": "副标题（来源说明）",
    "overview": {"lead": "一句话主旨（不超过3句）", "body": ["段落…"]},
    "prereq": ["前置知识条目（没有就给空数组）"],
    "concepts": [
        {"title": "概念名", "what": "是什么", "why": "为什么重要", "how": "怎么用"}
    ],
    "glossary": [{"term": "术语", "desc": "大白话解释"}],
    "steps": [
        {"title": "步骤标题", "items": [
            {"text": "做什么", "ok": "做到什么算对（可选）", "ts": "来源时间戳（强烈建议）"}
        ]}
    ],
    "pit": [
        {"wrong": "误区", "right": "正确做法", "why": "为什么（可选）"}
    ],
    "example": ["实例演算内容（HTML 允许）"],
    "quiz": [
        {"q": "题目", "a": "答案与解析"}
    ],
    "next": ["最小行动 / 相关延伸"],
    "src": {"index": ["关键结论 → 原视频时间戳"], "note": "补充说明（可选）"},
    "disclaimer": "免责声明（可选）",
}


def print_schema():
    print(json.dumps(SCHEMA, ensure_ascii=False, indent=2))
    print("\n--- 说明 ---")
    print("必填章节（缺任一会在生成前报错）：")
    for k, label in REQUIRED_SECTIONS:
        print(f"  {k:<10} {label}")
    print("\n时间戳：每条 steps.items 建议带 ts（mm:ss 或 videoXX mm:ss），")
    print("校验器会统计锚点数量，低于 --min-anchors 会警告。")


def load_template():
    """读取版式基线模板，提取 <style>、「主题切换脚本」与「✏️修改」脚本。"""
    if not os.path.isfile(TEMPLATE):
        return None, None, None
    with open(TEMPLATE, encoding="utf-8") as f:
        raw = f.read()
    m = re.search(r"<style>(.*?)</style>", raw, re.S)
    css = m.group(1) if m else ""
    # 主题切换脚本（第一个 script 是主题）
    scripts = re.findall(r"<script>(.*?)</script>", raw, re.S)
    theme_js = scripts[0] if scripts else ""
    edit_js = scripts[-1] if len(scripts) > 1 else (scripts[0] if scripts else "")
    return css, theme_js, edit_js


def theme_switcher_html():
    """主题切换按钮（放在目录条末尾）。"""
    return ('<span class="theme-sw">'
            '<button data-set-theme="light" title="浅色">浅</button>'
            '<button data-set-theme="dark" title="暗色">暗</button>'
            '<button data-set-theme="magazine" title="杂志风">杂志</button>'
            '</span>')


def count_anchors(content):
    """统计内容里的时间戳锚点数（容忍格式错误）。"""
    n = 0
    steps = content.get("steps", [])
    if isinstance(steps, list):
        for sec in steps:
            if not isinstance(sec, dict):
                continue
            items = sec.get("items", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("ts"):
                    n += 1
    pit = content.get("pit", [])
    if isinstance(pit, list):
        for p in pit:
            if isinstance(p, dict) and p.get("ts"):
                n += 1
    # src.index 里的时间戳也算
    src = content.get("src", {})
    if isinstance(src, dict):
        idx = src.get("index", [])
        if isinstance(idx, list):
            for line in idx:
                if isinstance(line, str):
                    n += len(re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", line))
    return n


def validate(content, min_anchors=3, quiz_need_answers=True):
    """规范校验，返回 (errors, warnings, infos)。"""
    errors, warnings, infos = [], [], []
    if not isinstance(content, dict):
        return ["内容顶层必须是 JSON 对象"], [], []

    # Reject malformed nested values before renderers can dereference them.
    def strings(values, label):
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            errors.append(label + " 必须是字符串数组")
    if "overview" in content:
        overview = content["overview"]
        if not isinstance(overview, dict): errors.append("overview 必须是对象")
        else:
            if not isinstance(overview.get("lead"), str): errors.append("overview.lead 必须是字符串")
            strings(overview.get("body", []), "overview.body")
    for name in ("prereq", "example", "next"):
        if name in content: strings(content[name], name)
    for name in ("concepts", "steps", "pit", "quiz", "glossary"):
        if name in content:
            if not isinstance(content[name], list): errors.append(name + " 必须是数组"); continue
            for item in content[name]:
                if not isinstance(item, dict): errors.append(name + " 项必须是对象"); continue
                if name == "quiz" and not item.get("a"):
                    errors.append("自测题缺答案")
                for key, value in item.items():
                    if key == "items" and name == "steps":
                        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
                            errors.append("steps.items 必须是对象数组")
                        else:
                            for row in value:
                                if any(not isinstance(v, str) for v in row.values()): errors.append("步骤字段必须是字符串")
                    elif not isinstance(value, str): errors.append(name + "." + key + " 必须是字符串")
    if "src" in content:
        if not isinstance(content["src"], dict): errors.append("src 必须是对象")
        else: strings(content["src"].get("index", []), "src.index")
    if errors:
        return errors, warnings, infos

    # 必填章节
    for key, label in REQUIRED_SECTIONS:
        if key not in content:
            errors.append(f"缺少必填章节：{label}（{key}）")
        elif not content[key] and not (isinstance(content.get("section_notes"),dict) and isinstance(content["section_notes"].get(key),str) and content["section_notes"][key].strip()):
            warnings.append(f"章节为空：{label}（{key}）")

    # 总览必须有 lead
    ov = content.get("overview", {})
    if isinstance(ov, str) and not ov.strip():
        warnings.append("总览是空字符串，建议用 {lead, body} 结构")
    elif isinstance(ov, dict) and not ov.get("lead"):
        warnings.append("总览缺少 lead（一句话主旨）——学习指南的灵魂段落")

    # 核心概念三段式（容忍格式错误：概念可能是字符串或缺字段）
    concepts = content.get("concepts", [])
    if isinstance(concepts, list):
        for c in concepts:
            if not isinstance(c, dict):
                warnings.append(f"概念项不是对象（应含 title/what/why/how）：{str(c)[:30]}")
                continue
            for f in ("title", "what", "why", "how"):
                if not c.get(f):
                    warnings.append(f"概念缺字段 {f}：{c.get('title', '?')}")

    # 步骤必须有内容（容忍格式错误）
    steps = content.get("steps", [])
    if isinstance(steps, list) and steps:
        valid_items = False
        for s in steps:
            if not isinstance(s, dict):
                warnings.append(f"步骤节不是对象：{str(s)[:30]}")
                continue
            if s.get("items"):
                valid_items = True
        if not valid_items:
            errors.append("步骤清单为空或格式错误（每节应有 items 数组）")

    # 自测题答案折叠（容忍格式错误：题目可能是字符串）
    quiz = content.get("quiz", [])
    if quiz_need_answers and isinstance(quiz, list):
        for q in quiz:
            if not isinstance(q, dict):
                errors.append(f"自测题格式错误（应含 q/a）：{str(q)[:30]}")
                continue
            if not q.get("a"):
                errors.append(f"自测题缺答案：{(q.get('q') or '?')[:30]}")

    # 时间戳锚点
    anchors = count_anchors(content)
    infos.append(f"时间戳锚点：{anchors} 个")
    if anchors < min_anchors:
        warnings.append(f"时间戳锚点仅 {anchors} 个（建议 ≥{min_anchors}）——"
                       "违反「每条结论可回溯」铁律")

    # 课内数值提醒
    raw = json.dumps(content, ensure_ascii=False)
    if re.search(r"\d+\s*(元|块|%|％)", raw) and "示例" not in raw and "红线" not in raw:
        warnings.append("含具体数值但未见「课内示例 / 非通用红线」字样——"
                       "数值可能被误当通用标准")

    return errors, warnings, infos


def esc(s):
    return html.escape(str(s))


def build_body(content):
    """按模板的类名生成正文 HTML。"""
    o = []
    o.append(f"<h1>{esc(content.get('title', '学习指南'))}</h1>")
    if content.get("subtitle"):
        o.append(f'<p class="sub">{esc(content["subtitle"])}</p>')

    # 总览
    ov = content.get("overview", {})
    if ov:
        o.append('<h2 id="overview">总览</h2>')
        if ov.get("lead"):
            o.append(f'<div class="lead">{esc(ov["lead"])}</div>')
        for p in ov.get("body", []):
            o.append(f"<p>{esc(p)}</p>")

    # 前置
    if content.get("prereq"):
        o.append('<h2 id="prereq">前置知识</h2><ul>')
        for p in content["prereq"]:
            o.append(f"<li>{esc(p)}</li>")
        o.append("</ul>")

    # 核心概念
    if content.get("concepts"):
        o.append('<h2 id="concepts">核心概念</h2>')
        for c in content["concepts"]:
            o.append('<div class="concept">')
            o.append(f'<div class="t">{esc(c.get("title", ""))}</div><p>')
            o.append(f'<b>是什么：</b>{esc(c.get("what", ""))}<br>')
            o.append(f'<b>为什么重要：</b>{esc(c.get("why", ""))}<br>')
            o.append(f'<b>怎么用：</b>{esc(c.get("how", ""))}</p></div>')
        if content.get("glossary"):
            o.append("<h3>术语表</h3>")
            o.append('<div class="gloss">')
            for g in content["glossary"]:
                o.append(f'<div><b>{esc(g.get("term", ""))}</b>：{esc(g.get("desc", ""))}</div>')
            o.append("</div>")

    # 步骤
    if content.get("steps"):
        o.append('<h2 id="steps">步骤清单</h2>')
        for sec in content["steps"]:
            if sec.get("title"):
                o.append(f"<h3>{esc(sec['title'])}</h3>")
            o.append('<ol class="steps">')
            for it in sec.get("items", []):
                ts = f'<span class="ts">{esc(it["ts"])}</span>' if it.get("ts") else ""
                ok = f'<span class="ok">{esc(it["ok"])}</span>' if it.get("ok") else ""
                o.append(f'<li>{esc(it.get("text", ""))}{ts}{ok}</li>')
            o.append("</ol>")

    # 误区
    if content.get("pit"):
        o.append('<h2 id="pit">常见误区</h2>')
        for p in content["pit"]:
            ts = f' <span class="ts">{esc(p["ts"])}</span>' if p.get("ts") else ""
            o.append(f'<div class="pit"><b>误区：</b>{esc(p.get("wrong", ""))}{ts}<br>'
                     f'<b>正确做法：</b>{esc(p.get("right", ""))}')
            if p.get("why"):
                o.append(f'<br><b>为什么：</b>{esc(p["why"])}')
            o.append("</div>")

    # 实例
    if content.get("example"):
        o.append('<h2 id="example">实例演算</h2>')
        for e in content["example"]:
            o.append(f'<div class="example">{e}</div>')  # example 允许 HTML

    # 自测
    if content.get("quiz"):
        o.append('<h2 id="quiz">自测题</h2>')
        for q in content["quiz"]:
            o.append('<details class="qa">')
            o.append(f'<summary>{esc(q.get("q", ""))}</summary>')
            o.append(f'<div class="ans">{esc(q.get("a", ""))}</div>')
            o.append("</details>")

    # 下一步
    if content.get("next"):
        o.append('<h2 id="next">下一步</h2><ul>')
        for n in content["next"]:
            o.append(f"<li>{esc(n)}</li>")
        o.append("</ul>")

    # 原文索引
    src = content.get("src", {})
    if isinstance(src, dict) and src.get("index"):
        o.append('<h2 id="src">原文索引</h2>')
        idx = "<br>".join(esc(x) for x in src["index"])
        o.append(f'<div class="srcidx">{idx}')
        if src.get("note"):
            o.append(f'<br>{esc(src["note"])}')
        o.append("</div>")

    if content.get("disclaimer"):
        o.append(f'<p style="color:var(--ink-3);font-size:13px">{esc(content["disclaimer"])}</p>')

    for key,label in REQUIRED_SECTIONS:
        if not content.get(key) and isinstance(content.get("section_notes"),dict) and content["section_notes"].get(key):
            o.append(f'<h2 id="{key}">{esc(label)}</h2><p>{esc(content["section_notes"][key])}</p>')
    return "\n".join(o)


def build_page(content, css, theme_js, edit_js):
    body = build_body(content)
    return (
        "<!doctype html>\n<html lang=\"zh-CN\" data-theme=\"light\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{esc(content.get('title', '学习指南'))}</title>\n"
        f"<style>{css}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n<nav class="toc"><div class="toc-inner">'
        + "".join(f'<a href="#{k}">{esc(label)}</a>'
                  for k, label in REQUIRED_SECTIONS if k in content)
        + theme_switcher_html()
        + '</div></nav>\n'
        + (f"<script>{theme_js}</script>\n" if theme_js else "")
        + f'<div id="content">\n{body}\n</div>\n</div>\n'
        '<button id="editBtn" class="edit-fab">✏️ 修改</button>\n'
        '<div id="editorOverlay" class="editor-overlay" hidden>\n'
        '  <div class="editor-head"><span>编辑源码（实时预览 · 可下载）</span><div>'
        '<button id="downloadBtn">下载 HTML</button><button id="closeBtn">关闭</button>'
        '</div></div>\n'
        '  <div class="editor-body"><textarea id="srcArea" spellcheck="false"></textarea>'
        '<iframe id="preview"></iframe></div>\n</div>\n'
        f"<script>{edit_js}</script>\n</body>\n</html>\n"
    )


def validate_html(path, min_anchors=3):
    """校验已生成的 HTML 是否合规。"""
    if not os.path.isfile(path):
        print(f"[错误] 文件不存在：{path}", file=sys.stderr)
        return 1
    raw = open(path, encoding="utf-8").read()
    errors, warnings = [], []

    for key, label in REQUIRED_SECTIONS:
        if f'id="{key}"' not in raw:
            errors.append(f"HTML 缺少章节锚点：{label}（#{key}）")

    anchors = len(re.findall(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', raw))
    if anchors < min_anchors:
        warnings.append(f"HTML 内时间戳仅 {anchors} 处（建议 ≥{min_anchors}）")

    # 自测题折叠：details.qa 数量 应 >= summary 数量
    n_details = len(re.findall(r'<details class="qa">', raw))
    n_answers = len(re.findall(r'<div class="ans">', raw))
    if n_details or n_answers:
        if n_details == 0:
            errors.append("有自测题但没有 <details> 折叠块（答案应默认隐藏）")
        elif n_details != n_answers:
            warnings.append(f"自测题折叠块 {n_details} 个 / 答案块 {n_answers} 个，"
                           "数量不匹配（可能漏了某题的答案）")
    elif "自测题" in raw:
        warnings.append("有自测题章节但没有折叠块")

    if "✏️" not in raw and "edit-fab" not in raw:
        warnings.append("缺少「✏️ 修改」按钮")

    if 'id="editorOverlay"' not in raw:
        errors.append("缺少编辑器 overlay（无法实时预览/下载）")

    print(f"\n校验：{path}")
    print(f"  章节齐全    : {'✓' if not errors else '✗'}")
    print(f"  时间戳锚点  : {anchors} 处")
    for e in errors:
        print(f"  [错误] {e}")
    for w in warnings:
        print(f"  [警告] {w}")
    if not errors and not warnings:
        print("  ✓ 全部通过")
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description="学习指南生成器（含规范校验）")
    ap.add_argument("content", nargs="?", help="内容 JSON 路径")
    ap.add_argument("-o", "--output", help="输出 HTML 路径")
    ap.add_argument("--check-only", action="store_true", help="只校验 JSON 不生成")
    ap.add_argument("--validate-html", help="校验已生成的 HTML")
    ap.add_argument("--print-schema", action="store_true", help="打印 JSON 结构说明")
    ap.add_argument("--min-anchors", type=int, default=3, help="最少时间戳锚点数")
    ap.add_argument("--strict", action="store_true", help="有警告也视为失败")
    args = ap.parse_args()

    if args.print_schema:
        print_schema()
        return 0

    if args.validate_html:
        return validate_html(args.validate_html, args.min_anchors)

    if not args.content:
        ap.print_help()
        print("\n提示：先跑  python guide_builder.py --print-schema  看 JSON 结构")
        return 1

    try:
        content = json.load(open(args.content, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[错误] 读取 JSON 失败：{e}", file=sys.stderr)
        return 1

    # 校验
    errors, warnings, infos = validate(content, args.min_anchors)
    print("=" * 56)
    print(" 规范校验")
    print("=" * 56)
    for i in infos:
        print(f"  · {i}")
    for w in warnings:
        print(f"  [警告] {w}")
    for e in errors:
        print(f"  [错误] {e}")

    if errors:
        print(f"\n✗ 校验未通过（{len(errors)} 个错误），已中止生成。")
        return 1
    if warnings and args.strict:
        print(f"\n✗ --strict 模式下警告视为失败，已中止。")
        return 1

    if args.check_only:
        print("\n✓ 校验通过（未生成 HTML）")
        return 0

    # 生成
    css, theme_js, edit_js = load_template()
    if css is None:
        print(f"[错误] 找不到版式模板：{TEMPLATE}", file=sys.stderr)
        return 1

    out = args.output or (os.path.splitext(args.content)[0] + ".html")
    page = build_page(content, css, theme_js, edit_js)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"\n✓ 已生成：{out}  ({len(page)/1024:.1f} KB)")
    if warnings:
        print(f"  （{len(warnings)} 条警告，建议修一下）")
    return 0


if __name__ == "__main__":
    sys.exit(main())