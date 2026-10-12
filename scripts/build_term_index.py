#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_term_index.py — 术语反向索引（Wiki 层）

解决"同一个概念散落在多条视频里，找不到在哪讲"的问题：
扫全部逐字稿，统计每个术语**出现在哪些视频的哪些时间点**，生成可跳转的对照表。

用法:
    python build_term_index.py <逐字稿根目录> [-o 输出.html] [--json 输出.json]
                               [--src-dir 原视频目录] [--min-count N]

输入目录结构：<根目录>/<视频ID或ID_标题>/原始提取.md
输出：
    - HTML 术语索引页（按出现频次排序，每条可跳转到总索引页对应视频）
    - JSON（供程序消费 / 后续生成知识图谱）
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EX_DIR = os.path.join(os.path.dirname(HERE), "examples")


def load_terms():
    """从术语表提取所有【正确词】（作为要检索的概念）。"""
    terms = set()
    cands = []
    for d in (HERE, EX_DIR):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("terms_") and name.endswith(".json"):
                cands.append(os.path.join(d, name))
    for p in cands:
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for group, mapping in data.items():
            if group.startswith("_") or not isinstance(mapping, dict):
                continue
            for _wrong, right in mapping.items():
                if right and len(right) >= 2:
                    terms.add(right)
    # 额外：扫描逐字稿里反复出现的 2-4 字候选（补充术语表没覆盖的高频概念）
    return sorted(terms)


def load_title(vid, src_dir):
    import re as _re
    hits = glob.glob(os.path.join(src_dir, vid + "*.mp4")) if src_dir else []
    if not hits:
        return vid
    name = os.path.basename(hits[0]).replace(".mp4", "")
    name = name[len(vid):] if name.startswith(vid) else name
    name = _re.sub(r"(#\S+)+", " ", name)
    name = _re.sub(r"\s+", " ", name).strip(" -_·、")
    return name[:40] or vid


def scan(vids_root, terms, min_count=1):
    """扫全部逐字稿，返回 {术语: [{vid, title, 出现次数, 位置:[mm:ss,...]}]}"""
    index = defaultdict(list)
    vid_re = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
    # 长词优先，避免"搜索流量"被"搜索"抢先
    terms_sorted = sorted(terms, key=len, reverse=True)

    for d in sorted(os.listdir(vids_root)):
        p = os.path.join(vids_root, d)
        if not os.path.isdir(p):
            continue
        md = os.path.join(p, "原始提取.md")
        if not os.path.isfile(md):
            continue
        vid = d
        # 该视频内的术语命中
        hits = defaultdict(lambda: {"count": 0, "pos": []})
        with open(md, encoding="utf-8") as f:
            for line in f:
                m = vid_re.match(line.rstrip("\n"))
                if not m:
                    continue
                ts, text = m.group(1), m.group(2)
                for t in terms_sorted:
                    if t in text:
                        hits[t]["count"] += text.count(t)
                        if len(hits[t]["pos"]) < 30:  # 每视频最多记 30 个位置
                            hits[t]["pos"].append(ts)
        for t, info in hits.items():
            index[t].append({"vid": vid, "dir": d,
                             "count": info["count"], "pos": info["pos"]})
    # 过滤出现次数过少的
    result = {}
    for t, lst in index.items():
        total = sum(x["count"] for x in lst)
        n_vids = len(lst)
        if total >= min_count and n_vids >= 1:
            lst.sort(key=lambda x: -x["count"])
            result[t] = {"total": total, "videos": n_vids, "hits": lst}
    return result


CSS = """
:root{--bg:#fff;--bg-soft:#fbfbfd;--line:#e5e5e5;--line-soft:#f0f0f0;
--ink:#1f1f1f;--ink-2:#525252;--ink-3:#737373;--accent:#ea580c;--accent-soft:#fff4ee}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:24px 20px 80px}
h1{font-size:24px;margin:0 0 4px;font-weight:500}
.meta{color:var(--ink-3);font-size:13px;margin-bottom:18px}
.search{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:8px;
font-size:14px;background:var(--bg-soft);outline:none;margin-bottom:8px}
.search:focus{border-color:var(--accent)}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:18px}
.filters a{font-size:13px;color:var(--ink-3);text-decoration:none;padding:4px 10px;
border:1px solid var(--line);border-radius:999px}
.filters a:hover,.filters a.on{color:#fff;background:var(--accent);border-color:var(--accent)}
.term{border:1px solid var(--line);border-radius:10px;margin:10px 0;background:var(--bg-soft)}
.term>summary{cursor:pointer;padding:12px 16px;display:flex;justify-content:space-between;
align-items:center;gap:12px;list-style:none}
.term>summary::-webkit-details-marker{display:none}
.term .name{font-size:15px;font-weight:500;color:var(--accent)}
.term .cnt{font-size:12px;color:var(--ink-3);flex-shrink:0}
.hits{padding:0 16px 12px;border-top:1px solid var(--line)}
.hit{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--line-soft);
font-size:13px;align-items:baseline}
.hit:last-child{border-bottom:0}
.hit .vt{flex:1 1 auto;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hit .ps{flex-shrink:0;color:var(--ink-3);font-size:11px;
font-family:ui-monospace,Menlo,Consolas,monospace}
.hit .ps a{color:var(--accent);text-decoration:none;margin:0 3px}
.hint{font-size:13px;color:var(--ink-3);background:var(--accent-soft);
border-left:3px solid var(--accent);padding:10px 12px;border-radius:6px;margin:10px 0}
@media(max-width:560px){.wrap{padding:16px 14px 60px}.hit{flex-wrap:wrap}}
"""


def build_html(index, total_vids, total_terms, out_title):
    import html as H
    o = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>术语反向索引</title><style>{CSS}</style></head><body>',
         '<div class="wrap">',
         f'<h1>{H.escape(out_title)}</h1>',
         f'<div class="meta">{total_terms} 个术语 · 跨 {total_vids} 个视频聚合 · '
         '点任一术语展开，可跳转到总索引页对应视频</div>',
         '<input id="q" class="search" placeholder="搜索术语…（如：打标 / 测款 / 搜索流量）">',
         '<div class="filters">',
         '<a class="on" href="#top" data-filter="all">全部</a>',
         '<a href="#top" data-filter="multi">跨多视频</a>',
         '<a href="#top" data-filter="one">单视频</a>',
         '</div>',
         '<div class="hint">💡 这就是「wiki 层」：同一个概念散落在多条视频里，'
         '这里能一次看全它在哪讲、什么时间点。不必逐条视频翻。</div>']

    # 按总频次降序
    for term in sorted(index, key=lambda t: -index[t]["total"]):
        info = index[term]
        scope = "multi" if info["videos"] >= 2 else "one"
        o.append(f'<details class="term" data-scope="{scope}">')
        o.append(f'<summary><span class="name">{H.escape(term)}</span>'
                 f'<span class="cnt">{info["total"]} 次 · {info["videos"]} 个视频</span></summary>')
        o.append('<div class="hits">')
        for hv in info["hits"]:
            vid = hv["vid"]
            ps = " ".join(f'<a href="总索引.html#s{H.escape(vid, quote=True)}-{t.replace(chr(58), chr(45))}">{t}</a>'
                          for t in hv["pos"][:12])
            if len(hv["pos"]) > 12:
                ps += f' <span>+{len(hv["pos"])-12}</span>'
            o.append(f'<div class="hit"><span class="vt">{H.escape(hv["dir"])}</span>'
                     f'<span class="ps">{ps}</span></div>')
        o.append('</div></details>')
    o.append('</div>')

    # JS: 搜索 + 筛选
    o.append("<script>(function(){")
    o.append("var q=document.getElementById('q'),terms=[].slice.call(document.querySelectorAll('.term'));")
    o.append("function apply(){var k=q.value.trim().toLowerCase();")
    o.append("terms.forEach(function(t){var hit=!k||t.textContent.toLowerCase().indexOf(k)>=0;")
    o.append("t.style.display=hit?'':'none';});}")
    o.append("q.addEventListener('input',apply);")
    o.append("[].forEach.call(document.querySelectorAll('[data-filter]'),function(a){")
    o.append("a.addEventListener('click',function(e){e.preventDefault();")
    o.append("var f=a.getAttribute('data-filter');")
    o.append("[].forEach.call(document.querySelectorAll('[data-filter]'),function(b){b.classList.remove('on');});")
    o.append("a.classList.add('on');")
    o.append("terms.forEach(function(t){var s=t.getAttribute('data-scope');")
    o.append("var ok=(f==='all')||(f==='multi'&&s==='multi')||(f==='one'&&s==='one');")
    o.append("t.style.display=ok?'':'none';});});")
    o.append("})();</script>")
    o.append("</body></html>")
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(description="术语反向索引（Wiki 层）")
    ap.add_argument("root", help="逐字稿根目录")
    ap.add_argument("-o", "--output", help="输出 HTML 路径")
    ap.add_argument("--json", help="同时输出 JSON 路径")
    ap.add_argument("--src-dir", help="原视频目录（用于还原标题）")
    ap.add_argument("--min-count", type=int, default=2,
                    help="术语至少出现几次才收录（默认 2，过滤噪声）")
    ap.add_argument("--title", default="术语反向索引", help="页面标题")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"[错误] 目录不存在：{args.root}", file=sys.stderr)
        return 1

    terms = load_terms()
    if not terms:
        print("[错误] 未加载到任何术语（terms_*.json）", file=sys.stderr)
        return 1

    # 统计视频数
    vids_root = args.root
    n_vids = len([d for d in os.listdir(vids_root)
                  if os.path.isdir(os.path.join(vids_root, d))])

    print(f"术语库 {len(terms)} 个 · 扫描 {n_vids} 个视频…")
    index = scan(vids_root, terms, args.min_count)

    total_hits = sum(v["total"] for v in index.values())
    cross = sum(1 for v in index.values() if v["videos"] >= 2)
    print(f"  收录术语 {len(index)} 个（≥{args.min_count} 次）")
    print(f"  总命中 {total_hits} 处 · 其中跨视频术语 {cross} 个（wiki 关联点）")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"  JSON → {args.json}")

    if args.output:
        html_page = build_html(index, n_vids, len(index), args.title)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html_page)
        print(f"  HTML → {args.output} ({len(html_page)/1024:.0f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())