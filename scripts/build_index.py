#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_index.py — 把一批 MT 产物打包成一个「总索引页」单页 HTML

用法:
    python build_index.py <MT根目录> <输出HTML> [--title "标题"] [--guide 学习指南.html]

输入目录结构（transcribe.py / batch_transcribe.sh 的产物）:
    <根目录>/<视频ID>/原始提取.md
    <根目录>/<视频ID>/原始提取.json

产出：单页 HTML，含
    - 顶部总目录（sticky，可搜索过滤）
    - 学习指南内嵌区（可选，传入 --guide）
    - 每个视频的完整逐字稿（带时间戳、可折叠、可搜索）
"""
import argparse
import html
import json
import os
import re
import sys

# 从原视频文件名还原标题
def clean_title(name):
    """去掉抖音话题标签、压缩多余空格、限长。"""
    # 去掉 # 标签（可能连续出现多个）
    name = re.sub(r"(#\S+)+", " ", name)
    # 压缩空白
    name = re.sub(r"\s+", " ", name).strip(" -_·、")
    return name


def load_title(vid, src_dir):
    """从原视频文件名还原可读标题。src_dir 为空/找不到时回退到目录名。"""
    import glob
    from pathlib import Path
    # Pipeline IDs include path fingerprints; completion records retain original paths.
    if not src_dir or not os.path.isdir(src_dir):
        return vid
    hits = glob.glob(os.path.join(src_dir, vid + "*.mp4"))
    if not hits:
        return vid
    name = os.path.basename(hits[0]).replace(".mp4", "")
    name = name[len(vid):] if name.startswith(vid) else name
    name = clean_title(name)
    if len(name) > 40:
        name = name[:40] + "…"
    return name or vid


def parse_md(path):
    """解析 原始提取.md -> [(mm:ss, text), ...]"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$", line)
            if m:
                out.append((m.group(1), m.group(2)))
    return out


def inline_guide(path):
    """
    读取学习指南 HTML，把它的 <style> 和正文内容抽出来内联到总索引页。
    会剥掉指南自带的编辑器/按钮，避免与总索引页的 ID 冲突。
    返回 (css, body_html) 或 (None, None)。
    """
    import re as _re
    raw = open(path, encoding="utf-8").read()

    # 抽 CSS
    css = ""
    m = _re.search(r"<style>(.*?)</style>", raw, _re.S)
    if m:
        css = m.group(1)

    # 抽 body
    m = _re.search(r"<body[^>]*>(.*)</body>", raw, _re.S)
    if not m:
        return None, None
    body = m.group(1)

    # 剥掉指南自带的编辑器与编辑按钮（避免 ID 冲突：editBtn/editorOverlay/srcArea/preview…）
    body = _re.sub(r'<button id="editBtn".*?</button>', "", body, flags=_re.S)
    body = _re.sub(r'<div id="editorOverlay".*?</div>\s*</div>\s*</div>', "", body, flags=_re.S)
    body = _re.sub(r"<script>.*?</script>", "", body, flags=_re.S)

    # 顶层导航条在总索引页已有，去掉避免重复
    body = _re.sub(r'<nav class="toc">.*?</nav>', "", body, flags=_re.S)

    # 改 id，避免与外层冲突
    body = body.replace('id="content"', 'id="guide-content"')

    # 指南自带 h1 与本页 h1 重复 —— 降级为带样式的 h2，避免标题层级混乱
    body = _re.sub(r"<h1>", '<h1 class="guide-h1">', body)

    return css, body


CSS = """
/* ===== 主题：light(默认)/dark/magazine，右上角切换 + localStorage 记忆 ===== */
:root,[data-theme="light"]{
--bg:#fff;--bg-soft:#fbfbfd;--line:#e5e5e5;--line-soft:#f0f0f0;
--ink:#1f1f1f;--ink-2:#525252;--ink-3:#737373;--accent:#ea580c;--accent-soft:#fff4ee;
--radius:12px;--wrap:820px}
[data-theme="dark"]{
--bg:#16161a;--bg-soft:#1c1d22;--line:#2e2f36;--line-soft:#26272d;
--ink:#e8e8ea;--ink-2:#a8a9b0;--ink-3:#7a7b82;--accent:#ff7a45;--accent-soft:#2a1a12}
[data-theme="magazine"]{
--bg:#fff;--bg-soft:#fff;--line:#d8d5cc;--line-soft:#eceae3;
--ink:#111110;--ink-2:#4a4a46;--ink-3:#86847c;--accent:#8a3324;--accent-soft:#f6f2ec;
--radius:0px;--wrap:680px}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
[data-theme="magazine"] body{font-family:Georgia,"Songti SC","Noto Serif CJK SC",serif}
.top{position:sticky;top:0;z-index:20;background:var(--bg);
border-bottom:1px solid var(--line);padding:12px 0}
.top-in{max-width:var(--wrap);margin:0 auto;padding:0 20px;display:flex;
align-items:center;gap:10px;flex-wrap:wrap}
.top .brand{flex:1 1 auto;min-width:0}
.theme-sw{display:flex;gap:4px;flex-shrink:0}
.theme-sw button{font-size:12px;color:var(--ink-3);background:transparent;cursor:pointer;
border:1px solid var(--line);border-radius:999px;padding:3px 10px}
.theme-sw button.on{color:#fff;background:var(--accent);border-color:var(--accent)}
.top h1{font-size:18px;margin:0 0 4px;font-weight:500}
.top .meta{font-size:12px;color:var(--ink-3);margin-bottom:0}
.top-in2{max-width:var(--wrap);margin:0 auto;padding:10px 20px 0}
.top .meta{font-size:12px;color:var(--ink-3);margin-bottom:8px}
.search{width:100%;padding:8px 12px;border:1px solid var(--line);border-radius:8px;
font-size:14px;background:var(--bg-soft);outline:none}
.search:focus{border-color:var(--accent)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.chip{font-size:13px;color:var(--ink-3);text-decoration:none;padding:4px 10px;
border:1px solid var(--line);border-radius:999px;white-space:nowrap;background:var(--bg)}
.chip:hover{color:var(--accent);border-color:var(--accent)}
.chip.on{color:#fff;background:var(--accent);border-color:var(--accent)}
/* 视频目录面板（按主题分组，默认折叠）——视频再多也不挤爆顶栏 */
.tocpanel{border:1px solid var(--line);border-radius:12px;margin:14px 0;background:var(--bg-soft);}
.tocpanel>summary{cursor:pointer;padding:12px 16px;font-size:14px;font-weight:500;color:var(--ink);
list-style:none;user-select:none;}
.tocpanel>summary::-webkit-details-marker{display:none;}
.tocpanel>summary::before{content:"▸ ";color:var(--accent);}
.tocpanel[open]>summary::before{content:"▾ ";}
.tocpanel>summary:hover{color:var(--accent);}
.tocbody{padding:4px 16px 14px;border-top:1px solid var(--line);}
.tocgrp{margin:12px 0 0;}
.grp-h{font-size:13px;color:var(--accent);margin-bottom:6px;font-weight:500;}
.grp-n{display:inline-block;background:var(--bg);border:1px solid var(--line);
border-radius:999px;padding:0 7px;font-size:11px;color:var(--ink-3);margin-left:6px;}
.tocgrp ul{list-style:none;margin:0;padding:0;}
.tocgrp li{display:flex;justify-content:space-between;gap:10px;padding:5px 0;
border-bottom:1px solid var(--line-soft);}
.tocgrp li a{font-size:13px;color:var(--ink-2);text-decoration:none;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap;}
.tocgrp li a:hover{color:var(--accent);}
.tocgrp li .m{font-size:11px;color:var(--ink-3);flex-shrink:0;}
.wrap{max-width:var(--wrap);margin:0 auto;padding:20px 20px 120px}
h2{font-size:19px;margin:36px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--accent)}
.vid{border:1px solid var(--line);border-radius:12px;margin:14px 0;background:var(--bg-soft);overflow:hidden}
.vid>summary{cursor:pointer;padding:14px 16px;list-style:none;display:flex;
justify-content:space-between;align-items:flex-start;gap:12px}
.vid>summary::-webkit-details-marker{display:none}
.vid .t{font-size:15px;font-weight:500;color:var(--ink);margin-bottom:4px}
.vid .m{font-size:12px;color:var(--ink-3)}
.vid .badge{font-size:11px;color:var(--accent);border:1px solid var(--accent);
border-radius:999px;padding:2px 8px;white-space:nowrap;flex-shrink:0;margin-top:2px}
.vid[open]>summary{border-bottom:1px solid var(--line);background:var(--bg)}
.vid .body{padding:12px 16px}
.seg{display:flex;gap:10px;padding:3px 0;border-bottom:1px solid var(--line-soft)}
.seg:last-child{border-bottom:0}
.seg .t{font-size:12px;color:var(--accent);flex-shrink:0;width:52px;
font-variant-numeric:tabular-nums;font-family:ui-monospace,Menlo,Consolas,monospace;padding-top:2px}
.seg .x{font-size:14px;color:var(--ink-2)}
.guidewrap{border:1px solid var(--line);border-radius:12px;padding:4px 22px 18px;margin:14px 0;background:#fff}
.guidewrap>div{max-width:none}
.guidewrap h1.guide-h1{font-size:21px;margin:20px 0 4px;padding-bottom:8px;
border-bottom:1px solid var(--line);font-weight:500}
.guidewrap .sub{color:var(--ink-3);font-size:13px;margin:0 0 10px}
.hint{font-size:13px;color:var(--ink-3);background:var(--accent-soft);
border-left:3px solid var(--accent);padding:10px 12px;border-radius:6px;margin:10px 0}
.empty{text-align:center;color:var(--ink-3);padding:40px 0;font-size:14px}
.edit-fab{position:fixed;right:18px;bottom:18px;z-index:30;display:inline-flex;align-items:center;gap:6px;
background:var(--accent);color:#fff;border:none;border-radius:999px;padding:11px 18px;font-size:15px;
box-shadow:0 6px 20px rgba(234,88,12,.35);cursor:pointer}
.editor-overlay{position:fixed;inset:0;z-index:50;background:#0b0b0c;display:flex;flex-direction:column}
.editor-overlay[hidden]{display:none}
.editor-head{display:flex;align-items:center;justify-content:space-between;color:#e5e5e5;
padding:10px 14px;font-size:14px;border-bottom:1px solid #222}
.editor-head button{background:#262626;color:#e5e5e5;border:1px solid #333;border-radius:8px;
padding:6px 12px;margin-left:8px;cursor:pointer;font-size:13px}
.editor-body{flex:1;display:flex;min-height:0}
#srcArea{flex:1;border:0;resize:none;background:#16161a;color:#d4d4d4;padding:14px;
font:13px/1.6 ui-monospace,Menlo,Consolas,monospace;outline:none}
#preview{flex:1;border:0;background:#fff}
@media(max-width:560px){.wrap{padding:14px 14px 110px}.top-in{padding:0 14px}.top-in2{padding:10px 14px 0}
.seg{flex-direction:column;gap:0}.seg .t{width:auto;padding-top:4px}
.guidewrap{padding:2px 14px 14px}}
"""


def group_key(title):
    """按标题关键词粗分组，让长列表可折叠。"""
    for kw, key in TOPIC_RULES:
        if kw in title:
            return key
    return "其他"


def _build_toc_panel(vids):
    """视频目录面板：按主题分组、组内可折叠、默认收起。"""
    groups = {}
    for v in vids:
        groups.setdefault(group_key(v["title"]), []).append(v)

    o = ['<details class="tocpanel" id="toc-panel"><summary>☰ 视频目录（按主题分组）</summary>',
         '<div class="tocbody">']
    for key in sorted(groups, key=lambda k: (k == "其他", k)):
        items = groups[key]
        o.append(f'<div class="tocgrp"><div class="grp-h">{html.escape(key)} '
                 f'<span class="grp-n">{len(items)}</span></div><ul>')
        for v in items:
            o.append(f'<li><a href="#v{v["id"]}">{html.escape(v["title"][:46])}</a>'
                     f'<span class="m">{len(v["segs"])} 段</span></li>')
        o.append("</ul></div>")
    o.append("</div></details>")
    return "\n".join(o)


TOPIC_RULES = [
    ("起款", "新品起款"), ("起量", "新品起款"), ("从零起款", "新品起款"),
    ("关键词推广", "关键词推广"), ("直通车", "关键词推广"),
    ("人群推广", "人群推广"), ("引力魔方", "人群推广"),
    ("测款", "测款测图"), ("测图", "测款测图"),
    ("搜索", "搜索流量"), ("入池", "搜索流量"),
    ("人群标签", "人群标签"), ("精准打标", "人群标签"), ("打标", "人群标签"),
    ("双11", "大促活动"), ("双12", "大促活动"), ("活动", "大促活动"), ("抢先购", "大促活动"),
    ("定价", "定价"), ("价格", "定价"),
    ("数据", "数据分析"), ("参谋", "数据分析"), ("诊断", "数据分析"), ("分析", "数据分析"),
]


def main():
    ap = argparse.ArgumentParser(description="MT 产物打包成总索引页")
    ap.add_argument("root", help="MT 根目录（含 <视频ID>/原始提取.md）")
    ap.add_argument("out", help="输出 HTML 路径")
    ap.add_argument("--title", default="视频转写总索引")
    ap.add_argument("--guide", help="学习指南 HTML 路径（内嵌显示）")
    ap.add_argument("--src-dir", help="原视频目录（用于还原标题）")
    ap.add_argument("--open-all", action="store_true", help="默认展开全部逐字稿")
    args = ap.parse_args()

    vids = []
    for d in sorted(os.listdir(args.root)):
        p = os.path.join(args.root, d)
        if not os.path.isdir(p):
            continue
        md = os.path.join(p, "原始提取.md")
        js = os.path.join(p, "原始提取.json")
        if not os.path.isfile(md):
            continue
        segs = parse_md(md)
        meta = {}
        if os.path.isfile(js):
            try:
                meta = json.load(open(js, encoding="utf-8"))
            except Exception:
                pass
        title = load_title(d, args.src_dir) if args.src_dir else d
        try:
            from pathlib import Path
            state = json.loads(Path(args.root, d, "完成记录.json").read_text(encoding="utf-8"))
            title = clean_title(Path(state["identity"]["path"]).stem)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        vids.append({"id": d, "title": title, "segs": segs, "meta": meta})

    if not vids:
        print(f"[错误] {args.root} 下没找到任何 原始提取.md", file=sys.stderr)
        return 1

    total_segs = sum(len(v["segs"]) for v in vids)
    total_chars = sum(len(t) for v in vids for _, t in v["segs"])

    # ---- 构建 HTML ----
    buf = []
    # 学习指南内联（真正融入同一页，不是 iframe）
    guide_css = ""
    guide_body = ""
    if args.guide and os.path.isfile(args.guide):
        guide_css, guide_body = inline_guide(args.guide)

    buf.append("<!doctype html><html lang=\"zh-CN\" data-theme=\"light\"><head><meta charset=\"utf-8\">")
    buf.append("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">")
    buf.append(f"<title>{html.escape(args.title)}</title>")
    buf.append(f"<style>{CSS}\n/* ---- 学习指南样式（内联） ---- */\n{guide_css}</style></head><body>")

    # sticky 顶栏
    buf.append('<div class="top"><div class="top-in">')
    buf.append('<div class="brand">')
    buf.append(f"<h1>{html.escape(args.title)}</h1>")
    buf.append(f'<div class="meta">{len(vids)} 条视频 · {total_segs} 段 · {total_chars:,} 字 · '
               f'由 local-video-distill 转写</div>')
    buf.append('</div>')
    # 主题切换（常驻顶栏右侧，任何页面都能切）
    buf.append('<div class="theme-sw">'
               '<button data-set-theme="light" title="浅色">浅</button>'
               '<button data-set-theme="dark" title="暗色">暗</button>'
               '<button data-set-theme="magazine" title="杂志风">杂志</button>'
               '</div>')
    buf.append('</div>')
    buf.append('<div class="top-in2">')
    buf.append('<input id="q" class="search" placeholder="搜索标题或正文…（如：打标 / 测款 / 点击率 / 300-500）">')
    # 导航只放固定入口 + 展开式目录；不做「每视频一个药丸」（视频多了会炸）
    buf.append('<div class="chips">')
    buf.append('<a class="chip on" href="#top">全部</a>')
    if args.guide:
        buf.append('<a class="chip" href="#guide">📖 学习指南</a>')
    buf.append('<a class="chip" href="#vids">📝 逐字稿</a>')
    buf.append('<a class="chip" href="#toc-panel">☰ 目录</a>')
    buf.append('</div></div></div>')

    buf.append('<div class="wrap" id="top">')

    # 视频目录面板（默认折叠，按需展开；100 个视频也不会挤爆顶栏）
    buf.append(_build_toc_panel(vids))

    # 学习指南（内联到本页，不是 iframe）
    if guide_body:
        buf.append("<h2 id=\"guide\">📖 学习指南</h2>")
        buf.append('<div class="hint">下面是提炼版学习指南（方法论 · 步骤 · 误区 · 自测），'
                   '与下方「📝 完整逐字稿」<b>在同一页内</b>，可无缝上下滚动。'
                   '两者互补：指南讲"怎么做"，逐字稿是"原话怎么说"。</div>')
        buf.append('<div class="guidewrap">' + guide_body + "</div>")

    # 逐字稿
    buf.append('<h2 id="vids">📝 完整逐字稿</h2>')
    buf.append('<div class="hint">按 <code>[mm:ss]</code> 时间戳呈现全部原文，'
               '展示当前机器提取稿；可能存在漏识别或错字。用上方搜索框可按关键词过滤。</div>')

    for v in vids:
        o = " open" if args.open_all else ""
        dur = v["meta"].get("duration", 0)
        dur_s = f"{int(dur//60)}分{int(dur%60)}秒" if dur else "—"
        buf.append(f'<details class="vid" id="v{v["id"]}"{o}>')
        buf.append(f'<summary><div><div class="t">{html.escape(v["title"])}</div>'
                   f'<div class="m">ID {v["id"]} · {len(v["segs"])} 段 · {dur_s}</div></div>'
                   f'<span class="badge">{v["id"][:8]}</span></summary>')
        buf.append('<div class="body">')
        for ts, tx in v["segs"]:
            buf.append(f'<div class="seg" id="s{html.escape(v["id"], quote=True)}-{ts.replace(chr(58), chr(45))}" data-t="{html.escape(ts)} {html.escape(tx)}">'
                       f'<span class="t">{html.escape(ts)}</span>'
                       f'<span class="x">{html.escape(tx)}</span></div>')
        buf.append("</div></details>")

    if not vids:
        buf.append('<div class="empty">没有匹配的逐字稿</div>')
    buf.append("</div>")

    # 编辑器
    buf.append('<button id="editBtn" class="edit-fab">✏️ 修改</button>')
    buf.append('<div id="editorOverlay" class="editor-overlay" hidden>')
    buf.append('<div class="editor-head"><span>编辑源码（实时预览 · 可下载）</span><div>'
               '<button id="downloadBtn">下载 HTML</button><button id="closeBtn">关闭</button></div></div>')
    buf.append('<div class="editor-body"><textarea id="srcArea" spellcheck="false"></textarea>'
               '<iframe id="preview"></iframe></div></div>')

    buf.append("<script>(function(){")
    # 主题切换（light/dark/magazine，localStorage 记忆）
    buf.append("var KEY='lvd-theme';")
    buf.append("function apply(t){document.documentElement.setAttribute('data-theme',t);")
    buf.append("try{localStorage.setItem(KEY,t);}catch(e){}")
    buf.append("[].forEach.call(document.querySelectorAll('[data-set-theme]'),function(b){")
    buf.append("b.classList.toggle('on',b.getAttribute('data-set-theme')===t);});}")
    buf.append("document.addEventListener('click',function(e){")
    buf.append("var b=e.target.closest&&e.target.closest('[data-set-theme]');")
    buf.append("if(b)apply(b.getAttribute('data-set-theme'));});")
    buf.append("var sv=null;try{sv=localStorage.getItem(KEY);}catch(e){}")
    buf.append("apply(sv||'light');")
    buf.append("var q=document.getElementById('q'),vids=[].slice.call(document.querySelectorAll('.vid')),")
    buf.append("empty=document.querySelector('.empty');")
    buf.append("q.addEventListener('input',function(){var k=q.value.trim().toLowerCase(),n=0;")
    buf.append("vids.forEach(function(v){var hit=!k||v.textContent.toLowerCase().indexOf(k)>=0;")
    buf.append("v.style.display=hit?'':'none';if(hit)n++;});")
    buf.append("if(empty)empty.style.display=n?'none':'block';});")
    buf.append("var b=document.getElementById('editBtn'),ov=document.getElementById('editorOverlay'),")
    buf.append("ar=document.getElementById('srcArea'),pv=document.getElementById('preview'),")
    buf.append("dl=document.getElementById('downloadBtn'),cl=document.getElementById('closeBtn'),")
    buf.append("css=document.querySelector('style').textContent;")
    buf.append("function build(h){return '<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
               "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>'+css+"
               "'</style></head><body>'+h+'</body></html>';}")
    buf.append("b.onclick=function(){ar.value=document.body.innerHTML;pv.srcdoc=build(ar.value);ov.hidden=false;};")
    buf.append("ar.oninput=function(){clearTimeout(window._t);window._t=setTimeout(function(){pv.srcdoc=build(ar.value);},250);};")
    buf.append("cl.onclick=function(){ov.hidden=true;};")
    buf.append("dl.onclick=function(){var bl=new Blob([build(ar.value)],{type:'text/html;charset=utf-8'});")
    filename = json.dumps(os.path.basename(args.out), ensure_ascii=False).replace("<", "\\u003c")
    buf.append("var a=document.createElement('a');a.href=URL.createObjectURL(bl);a.download=" + filename + ";a.click();URL.revokeObjectURL(a.href);};})();</script>")
    buf.append("<script>function revealSource(){var el=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(el){var d=el.closest('details');if(d)d.open=true;el.scrollIntoView();}}addEventListener('hashchange',revealSource);revealSource();</script>")
    buf.append("</body></html>")

    out_html = "\n".join(buf)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_html)

    size = os.path.getsize(args.out)
    print(f"[完成] {args.out}")
    print(f"  {len(vids)} 条视频 · {total_segs} 段 · {total_chars:,} 字 · {size/1024:.0f} KB")
    if args.guide:
        print(f"  已内嵌学习指南：{os.path.basename(args.guide)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())