#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_graph.py — 术语共现图（可视化关联层）

从术语反向索引的 JSON 出发，按「同一视频内共现」建边，生成可交互的知识图谱 HTML。

用法:
    python build_graph.py <术语索引.json> -o 输出.html [--min-edge N] [--top-nodes N]

节点 = 术语（大小 = 出现频次）
边   = 共现（粗细 = 共现视频数）
交互：悬停高亮邻接、点击聚焦、拖拽平移、滚轮缩放、搜索定位
"""
import argparse
import html
import itertools
import json
import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

TPL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#fff;--bg-soft:#fbfbfd;--line:#e5e5e5;--ink:#1f1f1f;--ink-2:#525252;
--ink-3:#737373;--accent:#ea580c;--accent-soft:#fff4ee;--node:#ea580c;--edge:#c9c9c9}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);overflow:hidden;
font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.hud{position:fixed;top:14px;left:16px;z-index:10;background:var(--bg);
border:1px solid var(--line);border-radius:10px;padding:12px 14px;max-width:270px}
.hud h1{font-size:16px;margin:0 0 4px;font-weight:500}
.hud .meta{font-size:12px;color:var(--ink-3);margin-bottom:8px}
.hud .search{width:100%;padding:6px 9px;border:1px solid var(--line);border-radius:7px;
font-size:13px;background:var(--bg-soft);outline:none;margin-bottom:8px}
.hud .search:focus{border-color:var(--accent)}
.legend{font-size:12px;color:var(--ink-3);line-height:1.9}
.legend .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
background:var(--node);margin-right:5px;vertical-align:middle}
.legend .ln{display:inline-block;width:16px;height:2px;background:var(--edge);
margin-right:5px;vertical-align:middle}
#tip{position:fixed;padding:5px 9px;background:#1f1f1f;color:#fff;border-radius:6px;
font-size:12px;pointer-events:none;display:none;z-index:20;max-width:260px}
#tip b{color:#ffb98a}
#toast{position:fixed;left:50%;top:20px;transform:translateX(-50%);z-index:30;
background:#1f1f1f;color:#fff;padding:8px 16px;border-radius:8px;font-size:13px;display:none}
svg{width:100vw;height:100vh;display:block;cursor:grab}
svg.drag{cursor:grabbing}
text{font-family:inherit;pointer-events:none}
.tipbox{position:fixed;right:16px;bottom:14px;z-index:10;font-size:12px;
color:var(--ink-3);background:var(--bg);border:1px solid var(--line);
border-radius:8px;padding:8px 12px;max-width:300px}
@media(max-width:560px){.hud{max-width:calc(100vw - 32px)}.tipbox{display:none}}
</style></head><body>
<div class="hud">
  <h1>__TITLE__</h1>
  <div class="meta">__NODES__ 个术语 · __EDGES__ 条关联 · 拖拽平移 / 滚轮缩放 / 点击聚焦</div>
  <input id="q" class="search" placeholder="搜索术语定位…">
  <div class="legend">
    <span class="dot"></span>节点大小 = 出现频次<br>
    <span class="ln"></span>连线粗细 = 共现视频数
  </div>
</div>
<div id="tip"></div><aside id="sources" style="position:fixed;right:16px;top:16px;max-width:310px;max-height:70vh;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;z-index:12"><b>术语出处</b><p>点击术语查看出现的视频和时间点。</p></aside>
<div class="tipbox">这是共现检索图，连线不代表因果、前提或操作顺序。<br>💡 节点越大 = 出现越多；连线越粗 = 两个概念越常在同一节课里一起讲。<br>悬停看详情，点击聚焦其关联。</div>
<svg id="svg"></svg>
<script>
const DATA=__DATA__;
// —— 力导向布局（自实现，无外部依赖）——
const W=innerWidth,H=innerHeight;
const svg=document.getElementById('svg');
const tip=document.getElementById('tip');
const nodes=DATA.nodes.map((n,i)=>({...n,i,x:W/2+Math.cos(i)*200,y:H/2+Math.sin(i)*200,vx:0,vy:0}));
const byId={};nodes.forEach(n=>byId[n.id]=n);
const edges=DATA.edges.map(e=>({...e,s:byId[e.source],t:byId[e.target]}));
const maxW=Math.max(...edges.map(e=>e.w),1);
const maxC=Math.max(...nodes.map(n=>n.c),1);
const rOf=n=>8+22*Math.sqrt(n.c/maxC);
nodes.forEach(n=>n.r=rOf(n));
// 度数用于斥力
const deg={};nodes.forEach(n=>deg[n.id]=0);
edges.forEach(e=>{deg[e.source.id]++;deg[e.target.id]++;});
const LINK=[];
function tick(){
  // 斥力（按节点半径平方缩放，避免大节点粘连）
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i],b=nodes[j];
    let dx=b.x-a.x,dy=b.y-a.y;let d2=dx*dx+dy*dy||1;
    const want=(a.r+b.r+26)*(a.r+b.r+26);
    if(d2<want*9){ // 只在近距离强排斥，省算力
      const f=Math.min(3.2,9000/d2)/Math.sqrt(deg[a.id]+deg[b.id]+2);
      const d=Math.sqrt(d2);
      a.vx-=dx/d*f*14; a.vy-=dy/d*f*14;
      b.vx+=dx/d*f*14; b.vy+=dy/d*f*14;
    }
  }
  // 弹簧
  edges.forEach(e=>{
    const a=e.s,b=e.t;
    let dx=b.x-a.x,dy=b.y-a.y;const d=Math.sqrt(dx*dx+dy*dy)||1;
    const target=110+rOf(a)+rOf(b);
    const f=(d-target)*0.02*(0.4+e.w/maxW);
    a.vx+=dx/d*f*30; a.vy+=dy/d*f*30;
    b.vx-=dx/d*f*30; b.vy-=dy/d*f*30;
    LINK.push([a,b]);
  });
  // 向心 + 阻尼（向心力弱化，让图铺开）
  nodes.forEach(n=>{
    n.vx+=(W/2-n.x)*0.0016; n.vy+=(H/2-n.y)*0.0016;
    n.vx*=0.85;n.vy*=0.85;
    n.x+=Math.max(-16,Math.min(16,n.vx));
    n.y+=Math.max(-16,Math.min(16,n.vy));
  });
}
for(let i=0;i<400;i++)tick();
// —— 渲染 ——
const gEdge=document.createElementNS('http://www.w3.org/2000/svg','g');
const gNode=document.createElementNS('http://www.w3.org/2000/svg','g');
svg.appendChild(gEdge);svg.appendChild(gNode);
function draw(){
  gEdge.innerHTML='';gNode.innerHTML='';
  edges.forEach(e=>{
    const ln=document.createElementNS('http://www.w3.org/2000/svg','line');
    ln.setAttribute('x1',e.s.x);ln.setAttribute('y1',e.s.y);
    ln.setAttribute('x2',e.t.x);ln.setAttribute('y2',e.t.y);
    ln.setAttribute('stroke',focus&&focus!==e.s.id&&focus!==e.t.id?'#eee':'var(--edge)');
    ln.setAttribute('stroke-width',0.5+2.2*e.w/maxW);
    gEdge.appendChild(ln);
  });
  nodes.forEach(n=>{
    const c=document.createElementNS('http://www.w3.org/2000/svg','circle');
    c.setAttribute('cx',n.x);c.setAttribute('cy',n.y);c.setAttribute('r',n.r);
    const dim=focus&&focus!==n.id;
    c.setAttribute('fill',dim?'#ddd':'var(--node)');
    c.setAttribute('data-id',n.id);
    gNode.appendChild(c);
    if(n.r>11){
      const t=document.createElementNS('http://www.w3.org/2000/svg','text');
      t.setAttribute('x',n.x);t.setAttribute('y',n.y-n.r-4);
      t.setAttribute('text-anchor','middle');t.setAttribute('font-size',11);
      t.setAttribute('fill',dim?'#bbb':'var(--ink-2)');
      t.textContent=n.id;
      gNode.appendChild(t);
    }
  });
}
let focus=null;
function escapeText(x){return String(x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c]));}
function showSources(n){
  const panel=document.getElementById("sources");panel.replaceChildren();
  const title=document.createElement("b");title.textContent=n.id+" · 出处";panel.append(title);
  (n.hits||[]).forEach(h=>{const p=document.createElement("p");p.textContent=h.dir+"： ";(h.pos||[]).forEach(t=>{const a=document.createElement("a");a.textContent=t+" ";a.href="总索引.html#"+encodeURIComponent("s"+h.dir+"-"+t.replaceAll(":","-"));p.append(a);});panel.append(p);});
}
function info(n){
  const nb=edges.filter(e=>e.s.id===n.id||e.t.id===n.id)
    .map(e=>(e.s.id===n.id?e.t.id:e.s.id));
  return `<b>${escapeText(n.id)}</b><br>出现 ${n.c} 次 · ${n.v} 个视频<br>关联：${escapeText(nb.slice(0,8).join('、'))}`;
}
let toastT=null;
function toast(msg){
  let el=document.getElementById('toast');
  if(!el){el=document.createElement('div');el.id='toast';document.body.appendChild(el);}
  el.textContent=msg;el.style.display='block';
  clearTimeout(toastT);toastT=setTimeout(()=>{el.style.display='none';},2200);
}
gNode.addEventListener('mousemove',ev=>{
  const t=ev.target.getAttribute('data-id');
  if(t&&t!==focus){focus=t;draw();}
  const n=byId[t];
  if(n){tip.innerHTML=info(n);tip.style.display='block';
    tip.style.left=(ev.clientX+14)+'px';tip.style.top=(ev.clientY+14)+'px';}
  else tip.style.display='none';
});
gNode.addEventListener('mouseleave',()=>{tip.style.display='none';});
gNode.addEventListener('click',ev=>{
  const t=ev.target.getAttribute('data-id');
  focus=(focus===t)?null:t;draw();
  if(focus){showSources(byId[focus]);toast('已聚焦：'+focus+'（点击空白处取消）');}
});
document.getElementById('q').addEventListener('input',function(){
  const k=this.value.trim();
  if(!k){focus=null;draw();return;}
  const hit=nodes.find(n=>n.id===k)||nodes.find(n=>n.id.includes(k));
  if(hit){focus=hit.id;draw();showSources(hit);toast('已定位：'+hit.id);}
  else toast('未找到术语：'+k);
});
// 点击空白取消聚焦
svg.addEventListener('click',e=>{if(e.target===svg&&focus){focus=null;draw();}});
// 拖拽 + 缩放
let vb={x:0,y:0,k:1},dragging=false,px=0,py=0;
svg.addEventListener('mousedown',e=>{dragging=true;px=e.clientX;py=e.clientY;svg.classList.add('drag');});
addEventListener('mousemove',e=>{
  if(!dragging)return;
  vb.x+=e.clientX-px;vb.y+=e.clientY-py;px=e.clientX;py=e.clientY;
  svg.style.transform=`translate(${vb.x}px,${vb.y}px) scale(${vb.k})`;
});
addEventListener('mouseup',()=>{dragging=false;svg.classList.remove('drag');});
svg.addEventListener('wheel',e=>{
  e.preventDefault();
  vb.k=Math.max(0.4,Math.min(3,vb.k*(e.deltaY<0?1.1:0.9)));
  svg.style.transform=`translate(${vb.x}px,${vb.y}px) scale(${vb.k})`;
},{passive:false});
draw();
setInterval(()=>{ // 缓慢自转微调
  if(!dragging){nodes.forEach(n=>{n.x+=(Math.random()-0.5)*0.2;n.y+=(Math.random()-0.5)*0.2;});draw();}
},3000);
</script></body></html>"""


def build(index_path, out_path, min_edge=2, top_nodes=40):
    with open(index_path, encoding="utf-8") as f:
        idx = json.load(f)
    # 节点：出现频次 + 视频数
    all_terms = {t: (v["total"], v["videos"]) for t, v in idx.items()}

    # 每个视频包含的术语 → 共现边
    vid_terms = {}
    for term, info in idx.items():
        for h in info["hits"]:
            vid_terms.setdefault(h["vid"], set()).add(term)
    edges = Counter()
    for ts in vid_terms.values():
        if len(ts) < 2:
            continue
        for a, b in itertools.combinations(sorted(ts), 2):
            edges[(a, b)] += 1

    # 只保留够强的边
    edges = {k: v for k, v in edges.items() if v >= min_edge}
    # 参与的节点
    used = set()
    for (a, b) in edges:
        used.add(a); used.add(b)
    # 限制节点数：按总频次取 top
    used = sorted(all_terms, key=lambda t: -all_terms[t][0])[:top_nodes]

    nodes = [{"id": t, "c": all_terms[t][0], "v": all_terms[t][1], "hits": idx[t]["hits"]}
             for t in used if t in all_terms]
    node_set = {n["id"] for n in nodes}
    edges_out = [{"source": a, "target": b, "w": w}
                 for (a, b), w in edges.items()
                 if a in node_set and b in node_set]

    title = "术语共现图"
    html_page = (TPL
                 .replace("__TITLE__", html.escape(title))
                 .replace("__NODES__", str(len(nodes)))
                 .replace("__EDGES__", str(len(edges_out)))
                 .replace("__DATA__", json.dumps({"nodes": nodes, "edges": edges_out},
                                               ensure_ascii=False).replace("<", "\\u003c")))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_page)
    return len(nodes), len(edges_out)


def main():
    ap = argparse.ArgumentParser(description="术语共现图")
    ap.add_argument("index", help="术语索引 JSON（build_term_index.py 生成）")
    ap.add_argument("-o", "--output", required=True, help="输出 HTML")
    ap.add_argument("--min-edge", type=int, default=2, help="共现至少几个视频才连边")
    ap.add_argument("--top-nodes", type=int, default=40, help="最多画多少节点")
    args = ap.parse_args()

    if not os.path.isfile(args.index):
        print(f"[错误] 索引文件不存在：{args.index}", file=sys.stderr)
        return 1
    n, e = build(args.index, args.output, args.min_edge, args.top_nodes)
    print(f"[完成] {args.output}")
    print(f"  {n} 个节点 · {e} 条边")
    return 0


if __name__ == "__main__":
    sys.exit(main())