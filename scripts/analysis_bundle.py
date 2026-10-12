"""Evidence-bound semantic analysis; no model calls and no inferred edges."""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import sys

RELATIONS = {'前提', '步骤', '因果', '例外', '冲突'}
SECTIONS = ('概念', '论证', '案例与计算', '操作步骤', '适用条件', '例外', '待核对')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def catalog(summary_path):
    summary = read(summary_path)
    run = Path(summary['artifacts_dir'])
    # Frozen raw copies belong to this run, rather than a mutable latest cache.
    raw = run / '原稿快照'
    if not raw.is_dir():
        raise ValueError('本次运行缺少原稿快照；请用新版本 pipeline 重新建立运行记录')
    out = {}
    for source in summary['sources']:
        source_id = source['id']
        path = raw / source_id / '原始提取.json'
        data = read(path)
        segs = data['segments']
        if not segs:
            raise ValueError('空原稿：' + source_id)
        out[source_id] = {**source, 'segments': segs, 'transcript_sha256': sha(path),
                          'duration': data.get('duration', max(s['end'] for s in segs)),
                          'raw_path': str(path)}
    return out


def template(sources):
    return {'version': 1, 'status': 'draft',
            'source_hashes': {k:v['transcript_sha256'] for k,v in sources.items()},
            'analyses': [{'source_id':k, 'read_ranges':[], 'sections':{name:[] for name in SECTIONS}, 'section_notes':{name:'' for name in SECTIONS}}
                         for k in sources],
            'claims': [], 'relations': [],
            'synthesis': {'一致':[], '互补':[], '冲突':[], '未解决':[]},
            'synthesis_notes': {'一致':'', '互补':'', '冲突':'', '未解决':''},
            'acceptance': [], 'guide': None,
            'instructions': 'Agent 阅读全部原稿后填写。证据须引用原稿中的文字，不用校对稿伪装原文。缺少关系或条件就显式留空，不编造。'}


def validate(bundle, sources):
    errors=[]
    def issue(message): errors.append(message)
    if not isinstance(bundle, dict):
        return ['分析包必须是 JSON 对象']
    if bundle.get('version') != 1: issue('分析包 version 必须为 1')
    if bundle.get('status') != 'ready': issue('分析包尚未 ready')
    hashes=bundle.get('source_hashes')
    expected={k:v['transcript_sha256'] for k,v in sources.items()}
    if hashes != expected: issue('来源集合或原稿哈希与本次运行不一致')
    claims=bundle.get('claims'); relations=bundle.get('relations'); analyses=bundle.get('analyses')
    if not isinstance(claims,list) or not claims: issue('claims 必须为非空数组'); claims=[]
    if not isinstance(relations,list): issue('relations 必须为数组'); relations=[]
    if not isinstance(analyses,list): issue('analyses 必须为数组'); analyses=[]
    ids={}

    def evidence(items, label):
        if not isinstance(items,list) or not items:
            issue(label+' 缺少证据'); return
        for e in items:
            if not isinstance(e,dict): issue(label+' 证据格式错误'); continue
            source=sources.get(e.get('source_id'))
            if not source: issue(label+' 引用了未知来源'); continue
            start,end=e.get('start'),e.get('end')
            if not number(start) or not number(end) or not 0 <= start < end <= source['duration'] + 0.01:
                issue(label+' 时间范围无效'); continue
            quote=e.get('quote')
            text=' '.join(s['text'] for s in source['segments'] if s['start'] < end and s['end'] > start)
            if not isinstance(quote,str) or not quote.strip() or ''.join(quote.split()) not in ''.join(text.split()):
                issue(label+' 引文不在指定时间范围的原稿中')
            if e.get('verification') not in {'machine', 'video_checked'}:
                issue(label+' 必须标记 machine 或 video_checked 核对状态')

    for c in claims:
        if not isinstance(c,dict): issue('claim 必须为对象'); continue
        cid=c.get('id')
        if not isinstance(cid,str) or not cid or cid in ids: issue('claim ID 缺失或重复'); continue
        ids[cid]=c
        if not isinstance(c.get('text'),str) or not c['text'].strip(): issue(cid+' 缺少结论')
        if c.get('origin') not in {'讲师观点','整理者推断'}: issue(cid+' 缺少观点来源分类')
        if not isinstance(c.get('conditions'),str): issue(cid+' 必须说明适用条件（可明确未说明）')
        evidence(c.get('evidence'),cid)
    relation_ids=set()
    for r in relations:
        if not isinstance(r,dict): issue('关系必须为对象'); continue
        rid=r.get('id')
        if not isinstance(rid,str) or not rid or rid in relation_ids: issue('关系 ID 缺失或重复')
        relation_ids.add(rid if isinstance(rid,str) else '')
        if r.get('type') not in RELATIONS: issue(str(rid)+' 关系类型无效')
        if r.get('from') not in ids or r.get('to') not in ids or r.get('from')==r.get('to'): issue(str(rid)+' 关系端点无效')
        if not isinstance(r.get('explanation'),str) or not r['explanation'].strip(): issue(str(rid)+' 缺少关系解释')
        if not isinstance(r.get('conditions'),str): issue(str(rid)+' 缺少关系条件')
        if r.get('origin') not in {'讲师观点','整理者推断'}: issue(str(rid)+' 缺少观点来源分类')
        evidence(r.get('evidence'),str(rid))
        if r.get('type') == '冲突':
            referenced={e.get('source_id') for e in r.get('evidence',[]) if isinstance(e,dict)}
            endpoints={e.get('source_id') for cid in (r.get('from'),r.get('to'))
                       for e in ids.get(cid,{}).get('evidence',[]) if isinstance(e,dict)}
            if not endpoints <= referenced: issue(str(rid)+' 冲突证据须覆盖两端观点的来源')
    def refs(value,label):
        if not isinstance(value,list) or any(not isinstance(x,str) or x not in ids for x in value):
            issue(label+' 必须使用已定义 claim ID 数组')
    visited=set()
    for a in analyses:
        if not isinstance(a,dict): issue('analysis 必须为对象'); continue
        sid=a.get('source_id'); source=sources.get(sid)
        if not source or sid in visited: issue('analysis 来源未知或重复'); continue
        visited.add(sid)
        ranges=a.get('read_ranges'); valid=[]
        if not isinstance(ranges,list): issue(sid+' 阅读区间必须为数组'); ranges=[]
        for rng in ranges:
            if not isinstance(rng,list) or len(rng)!=2 or not all(number(t) for t in rng) or not 0<=rng[0]<rng[1]<=source['duration']+0.01:
                issue(sid+' 阅读区间无效')
            else: valid.append(rng)
        cursor=0
        for start,end in sorted(valid):
            if start>cursor+0.01: issue(sid+' 阅读覆盖有缺口')
            cursor=max(cursor,end)
        if cursor<source['duration']-0.01: issue(sid+' 未覆盖到视频结尾')
        sections=a.get('sections')
        if not isinstance(sections,dict): issue(sid+' 缺少详细分析章节'); continue
        for name in SECTIONS:
            refs(sections.get(name),sid+':'+name)
            if not sections.get(name) and not (isinstance(a.get('section_notes'),dict) and isinstance(a['section_notes'].get(name),str) and a['section_notes'][name].strip()):
                issue(sid+':'+name+' 为空时须说明原文未提供或仍待核对')
            for cid in sections.get(name,[]) if isinstance(sections.get(name),list) else []:
                if cid in ids and sid not in {e.get('source_id') for e in ids[cid].get('evidence',[]) if isinstance(e,dict)}:
                    issue(sid+' 的分析引用了没有该视频证据的结论')
        if not any(sections.get(name) for name in SECTIONS): issue(sid+' 分析全部为空')
    if visited != set(sources): issue('未逐条分析全部来源')
    synthesis=bundle.get('synthesis')
    if not isinstance(synthesis,dict): issue('缺少跨视频综合')
    else:
        for name in ('一致','互补','冲突','未解决'):
            refs(synthesis.get(name),'综合:'+name)
            if not synthesis.get(name) and not (isinstance(bundle.get('synthesis_notes'),dict) and isinstance(bundle['synthesis_notes'].get(name),str) and bundle['synthesis_notes'][name].strip()):
                issue('综合:'+name+' 为空时须说明原因')
    acceptance=bundle.get('acceptance')
    if not isinstance(acceptance,list) or len(acceptance)<3: issue('至少需要三个真实学习问题验收'); acceptance=[]
    for q in acceptance:
        if not isinstance(q,dict) or not isinstance(q.get('question'),str) or not isinstance(q.get('answer'),str) or not q['question'].strip() or not q['answer'].strip():
            issue('验收问题须有问题与答案'); continue
        refs(q.get('claim_ids'),'验收问题')
        if not q.get('claim_ids'): issue('验收答案缺少结论证据')
    guide=bundle.get('guide')
    if not isinstance(guide,dict): issue('缺少 guide 内容 JSON')
    else:
        import guide_builder
        e,w,_=guide_builder.validate(guide)
        errors.extend('指南:'+x for x in e+w)
        bindings=guide.get('claim_bindings')
        # All substantive guide content must have JSON-pointer -> claim bindings.
        required=['/overview/lead']
        required += ['/overview/body/'+str(i) for i,_ in enumerate(guide.get('overview',{}).get('body',[]))] if isinstance(guide.get('overview'),dict) else []
        for name, fields in [('concepts',('what','why','how')),('pit',('wrong','right','why')),('quiz',('q','a'))]:
            for i,item in enumerate(guide.get(name,[]) if isinstance(guide.get(name),list) else []):
                if isinstance(item,dict): required += [f'/{name}/{i}/{f}' for f in fields if item.get(f)]
        for i,section in enumerate(guide.get('steps',[]) if isinstance(guide.get('steps'),list) else []):
            if isinstance(section,dict):
                for j,item in enumerate(section.get('items',[]) if isinstance(section.get('items'),list) else []):
                    required += [f'/steps/{i}/items/{j}/'+f for f in ('text','ok') if isinstance(item,dict) and item.get(f)]
        for name in ('prereq','example','next'):
            required += [f'/{name}/{i}' for i,_ in enumerate(guide.get(name,[]) if isinstance(guide.get(name),list) else [])]
        if not isinstance(bindings,dict): issue('指南缺少 claim_bindings'); bindings={}
        for pointer in required:
            refs(bindings.get(pointer),'指南绑定:'+pointer)
            if not bindings.get(pointer): issue('指南内容缺少证据绑定:'+pointer)
    return errors


def render(bundle,sources,out):
    esc=lambda value: html.escape(str(value),quote=True)
    ids={c['id']:c for c in bundle['claims']}
    def evidence(items):
        rows=[]
        for e in items:
            source=sources[e['source_id']]
            url=Path(source['path']).resolve().as_uri()+'#t='+str(e['start'])
            rows.append(f'<p><a href="{esc(url)}">{esc(e["source_id"])} · {e["start"]}–{e["end"]} 秒</a> · {esc(e["verification"])}<br>原稿：{esc(e["quote"])}</p>')
        return ''.join(rows)
    cards=[]
    for r in bundle['relations']:
        cards.append(f'<article data-type="{esc(r["type"])}"><h3>{esc(r["type"])}：<a href="#claim-{esc(r["from"])}">{esc(ids[r["from"]]["text"])}</a> {"↔" if r["type"]=="冲突" else "→"} <a href="#claim-{esc(r["to"])}">{esc(ids[r["to"]]["text"])}</a></h3><p>{esc(r["explanation"])}</p><p>条件：{esc(r["conditions"])} · {esc(r["origin"])}</p><details><summary>查看关系证据</summary>{evidence(r["evidence"])}</details></article>')
    claim_html=''.join(f'<article id="claim-{esc(c["id"])}"><h3>{esc(c["id"])}：{esc(c["text"])}</h3><p>{esc(c["origin"])} · 条件：{esc(c["conditions"])}</p>{evidence(c["evidence"])}</article>' for c in bundle['claims'])
    # Directed SVG diagram, generated without injecting untrusted data into scripts.
    diagram=[]
    height=max(160, len(bundle['relations'])*120+40)
    for i,r in enumerate(bundle['relations']):
        y=30+i*120
        diagram.append(f'<g data-type="{esc(r["type"])}"><line x1="335" y1="{y+25}" x2="565" y2="{y+25}" stroke="#627d98" marker-end="url(#arrow)"/><text x="430" y="{y+12}">{esc(r["type"])}</text>')
        for cid,x in ((r['from'],20),(r['to'],580)):
            label=ids[cid]['text'];short=label[:17]+('…' if len(label)>17 else '')
            diagram.append(f'<a href="#claim-{esc(cid)}"><rect x="{x}" y="{y}" width="300" height="60" rx="8" fill="#eef5ff" stroke="#7794b5"/><text x="{x+12}" y="{y+22}">{esc(cid)}</text><text x="{x+12}" y="{y+46}"><title>{esc(label)}</title>{esc(short)}</text></a>')
        diagram.append('</g>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>有证据的知识关系</title><style>body{font:16px/1.7 system-ui,'Microsoft YaHei';max-width:1100px;margin:30px auto;padding:0 20px;color:#23364a}article{border:1px solid #d8e0ea;border-radius:10px;padding:16px;margin:16px 0;overflow-wrap:anywhere}a{color:#245c91}button{padding:8px;margin:4px;border:1px solid #ccd6e0;background:#f5f8fc;border-radius:6px;cursor:pointer}.chart{overflow:auto}svg text{font:14px system-ui}summary{cursor:pointer}</style><h1>知识关系与原始证据</h1><p>关系由整理者填写；本工具校验来源、时间范围和引文，不能自动证明因果成立。video_checked 是填写者报告的核对状态。视频链接可能需要本地播放器手动定位。</p><nav>'''
    page+=''.join(f'<button data-filter="{esc(t)}">{esc(t)}</button>' for t in ['全部',*sorted(RELATIONS)])+'</nav>'
    page+=f'<div class="chart"><svg width="900" height="{height}" role="img" aria-label="有向知识关系图"><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#627d98"/></marker></defs>'+''.join(diagram)+'</svg></div>'
    page+='<h2>关系与证据</h2>'+(''.join(cards) or '<p>当前没有有证据的关系，未自动补边。</p>')+'<h2>结论及来源</h2>'+claim_html
    page+='<script>document.querySelectorAll("[data-filter]").forEach(b=>b.onclick=()=>{document.querySelectorAll("[data-type]").forEach(x=>{x.style.display=b.dataset.filter==="全部"||x.dataset.type===b.dataset.filter?"":"none";});});</script></html>'
    Path(out).write_text(page,encoding='utf-8')


def build(bundle_path,summary_path,out):
    sources=catalog(summary_path); bundle=read(bundle_path)
    errors=validate(bundle,sources)
    if errors: raise ValueError('\n'.join(errors))
    root=Path(out)
    if root.exists() and any(root.iterdir()): raise ValueError('分析输出目录非空，拒绝覆盖旧产物')
    root.mkdir(parents=True,exist_ok=True)
    (root/'analysis.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
    render(bundle,sources,root/'知识关系图.html')
    claims={c['id']:c for c in bundle['claims']}
    for i,a in enumerate(bundle['analyses']):
        lines=['# '+a['source_id'], '状态：结构和引文校验通过；内容仍需人工判断。']
        for section,refs in a['sections'].items():
            lines+=['\n## '+section]
            if not refs: lines.append(a.get('section_notes',{}).get(section,'原文未明确提供'))
            for cid in refs:
                c=claims[cid];lines+=['- '+c['text']+'（'+c['origin']+'；'+c['conditions']+'）']
                lines += ['  - '+e['source_id']+f" {e['start']}–{e['end']} 秒："+e['quote'] for e in c['evidence']]
        (root/f'{i+1:03d}_内容分析.md').write_text('\n'.join(lines),encoding='utf-8')
    (root/'跨视频综合.md').write_text('\n'.join('# '+name+'\n'+'\n'.join('- '+claims[cid]['text'] for cid in refs) for name,refs in bundle['synthesis'].items()),encoding='utf-8')
    guide_path=root/'guide-content.json'
    guide_path.write_text(json.dumps(bundle['guide'],ensure_ascii=False,indent=2),encoding='utf-8')
    import guide_builder
    # Use validated render functions directly; avoids changing process argv.
    css,theme,edit=guide_builder.load_template()
    if css is None: raise ValueError('学习指南模板不存在')
    page=guide_builder.build_page(bundle['guide'],css,theme,edit)
    (root/'学习指南.html').write_text(page,encoding='utf-8')
    (root/'验收记录.json').write_text(json.dumps({'status':'evidence_structure_validated',
        'semantic_verification':'requires_human_review','questions':bundle['acceptance']},ensure_ascii=False,indent=2),encoding='utf-8')
    from build_entry import build as build_entry
    build_entry(summary_path, root/"结果入口.html", analysis_dir=root, analysis_complete=True)
    return root


def reading_chunks(sources, out, max_chars=9000):
    """Export every segment once; intervals partition source duration for reported reading."""
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    plan=[]
    for sid,source in sources.items():
        chunks=[]; current=[]; count=0
        for i,seg in enumerate(source['segments']):
            if current and count+len(seg['text'])>max_chars:
                chunks.append(current);current=[];count=0
            current.append((i,seg));count+=len(seg['text'])
        if current: chunks.append(current)
        start=0
        for i,chunk in enumerate(chunks):
            end=chunks[i+1][0][1]['start'] if i+1<len(chunks) else source['duration']
            name=f'{len(plan)+1:04d}_阅读原稿.md'
            text='\n'.join(f"[{seg['start']}–{seg['end']} 秒] {seg['text']}" for _,seg in chunk)
            (root/name).write_text('# '+sid+f' · 范围 {start}–{end} 秒\n\n'+text,encoding='utf-8')
            plan.append({'source_id':sid,'start':start,'end':end,'file':name,
                         'segment_indexes':[index for index,_ in chunk],'status':'unread'})
            start=end
    (root/'阅读计划.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    return plan


def main(argv=None):
    ap=argparse.ArgumentParser(description='校验详细分析与有证据的知识关系，生成离线学习产物')
    ap.add_argument('--summary',required=True);ap.add_argument('--analysis');ap.add_argument('--out',required=True)
    ap.add_argument('--init',action='store_true')
    args=ap.parse_args(argv)
    try:
        if args.init:
            target=Path(args.out)
            if target.exists(): raise ValueError('模板目标已存在，拒绝覆盖')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(template(catalog(args.summary)),ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            if not args.analysis: raise ValueError('缺少 --analysis')
            build(args.analysis,args.summary,args.out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1

if __name__=='__main__': sys.exit(main())
