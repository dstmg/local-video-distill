#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_theme.py — 给已有的单页 HTML 注入三套主题（light/dark/magazine）

用途：早于多主题功能生成的历史 HTML，或手工写的 HTML，补上主题切换能力。
做法：把主题 CSS 变量 + 切换脚本注入 <head>，并在页面顶部插入切换按钮。

用法:
    python add_theme.py <文件.html> [...]           # 原地修改
    python add_theme.py <文件.html> -o <新文件>     # 输出到别处
    python add_theme.py <文件.html> --dry-run       # 只看会改什么
"""
import argparse
import os
import re
import sys

THEME_CSS = """
/* ===== 三套主题（由 add_theme.py 注入）=====
   右上角按钮切换，选择记忆在 localStorage。 */
:root,[data-theme="light"]{
--bg:#fff;--bg-soft:#fbfbfd;--line:#e5e5e5;--line-soft:#f0f0f0;
--ink:#1f1f1f;--ink-2:#525252;--ink-3:#737373;--accent:#ea580c;--accent-soft:#fff4ee}
[data-theme="dark"]{
--bg:#16161a;--bg-soft:#1c1d22;--line:#2e2f36;--line-soft:#26272d;
--ink:#e8e8ea;--ink-2:#a8a9b0;--ink-3:#7a7b82;--accent:#ff7a45;--accent-soft:#2a1a12}
[data-theme="magazine"]{
--bg:#fff;--bg-soft:#fff;--line:#d8d5cc;--line-soft:#eceae3;
--ink:#111110;--ink-2:#4a4a46;--ink-3:#86847c;--accent:#8a3324;--accent-soft:#f6f2ec}
body{background:var(--bg);color:var(--ink)}
"""

THEME_BTN_CSS = """
.theme-sw{position:fixed;top:12px;right:14px;z-index:60;display:flex;gap:4px;
background:var(--bg);border:1px solid var(--line);border-radius:999px;padding:3px}
.theme-sw button{font-size:12px;color:var(--ink-3);background:transparent;cursor:pointer;
border:1px solid transparent;border-radius:999px;padding:3px 10px}
.theme-sw button.on{color:#fff;background:var(--accent);border-color:var(--accent)}
@media(max-width:560px){.theme-sw{top:auto;bottom:14px;right:14px}}
"""

THEME_JS = """
<script>(function(){
var KEY='lvd-theme';
function apply(t){
  document.documentElement.setAttribute('data-theme',t);
  try{localStorage.setItem(KEY,t);}catch(e){}
  [].forEach.call(document.querySelectorAll('[data-set-theme]'),function(b){
    b.classList.toggle('on',b.getAttribute('data-set-theme')===t);});
}
document.addEventListener('click',function(e){
  var b=e.target.closest&&e.target.closest('[data-set-theme]');
  if(b)apply(b.getAttribute('data-set-theme'));
});
var sv=null;try{sv=localStorage.getItem(KEY);}catch(e){}
apply(sv||'light');
})();</script>
"""

THEME_BTN_HTML = ('<div class="theme-sw">'
                  '<button data-set-theme="light" title="浅色">浅</button>'
                  '<button data-set-theme="dark" title="暗色">暗</button>'
                  '<button data-set-theme="magazine" title="杂志风">杂志</button>'
                  '</div>')


def inject(raw):
    """返回 (新HTML, 改了什么)。"""
    changes = []
    if 'data-set-theme' in raw:
        return raw, ["已含主题切换，跳过"]

    # 1) html 标签加默认主题，避免 JS 前的闪白
    raw2 = re.sub(r"<html(\s[^>]*)?>",
                  lambda m: (m.group(0)[:-1] + ' data-theme="light">')
                  if "data-theme" not in m.group(0) else m.group(0),
                  raw, count=1)
    if raw2 != raw:
        changes.append("html 加 data-theme=\"light\"")
        raw = raw2

    # 2) 注入主题 CSS（放进第一个 <style> 末尾，这样能用变量覆盖原有硬编码色）
    m = re.search(r"</style>", raw)
    if m:
        raw = raw[:m.start()] + THEME_CSS + THEME_BTN_CSS + raw[m.start():]
        changes.append("注入主题 CSS + 切换按钮样式")
    else:
        raw = raw.replace("<head>", "<head><style>" + THEME_CSS + THEME_BTN_CSS + "</style>", 1)
        changes.append("新建 style 注入主题 CSS")

    # 3) 注入按钮 + 脚本
    if "<body" in raw:
        raw = re.sub(r"(<body[^>]*>)", r"\1\n" + THEME_BTN_HTML + "\n" + THEME_JS, raw, count=1)
        changes.append("插入切换按钮 + 主题脚本")
    else:
        raw = raw.replace("</body>", THEME_BTN_HTML + THEME_JS + "</body>", 1)
        changes.append("body 末尾插入按钮 + 脚本")

    return raw, changes


def main():
    ap = argparse.ArgumentParser(description="给已有 HTML 注入三套主题")
    ap.add_argument("files", nargs="+", help="HTML 文件")
    ap.add_argument("-o", "--output", help="输出到新文件（仅单文件时可用）")
    ap.add_argument("--dry-run", action="store_true", help="只看会改什么")
    args = ap.parse_args()

    rc = 0
    for i, path in enumerate(args.files):
        if not os.path.isfile(path):
            print(f"[跳过] 不存在：{path}", file=sys.stderr)
            rc = 1
            continue
        raw = open(path, encoding="utf-8").read()
        new, changes = inject(raw)
        if "已含主题切换" in changes[0]:
            print(f"[跳过] {os.path.basename(path)}（已有主题）")
            continue

        dest = args.output if (args.output and len(args.files) == 1) else path
        if not args.dry_run:
            open(dest, "w", encoding="utf-8").write(new)
        print(f"[{'试运行' if args.dry_run else '已注入'}] {os.path.basename(path)}")
        for c in changes:
            print(f"    · {c}")
        print(f"    → {dest}")
    return rc


if __name__ == "__main__":
    sys.exit(main())