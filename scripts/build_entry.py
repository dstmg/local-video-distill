"""Offline result entry, linking only existing artifacts and showing honest completion states."""
import argparse
import html
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

VALID_ANALYSIS = {'evidence_structure_validated', 'auto_generated_evidence_validated', 'supplied_and_format_validated'}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def href(path, parent):
    path=Path(path).resolve()
    try:
        return quote(Path(os.path.relpath(path, parent)).as_posix(), safe='/')
    except ValueError:
        return path.as_uri()


def build(summary_path, output=None, analysis_dir=None, analysis_complete=False):
    summary_path=Path(summary_path).resolve()
    summary=read(summary_path)
    if not isinstance(summary,dict):raise ValueError('运行摘要不存在或不是 JSON 对象')
    run=Path(summary.get('artifacts_dir',summary_path.parent)).resolve()
    output=Path(output).resolve() if output else run/'结果入口.html'
    output.parent.mkdir(parents=True,exist_ok=True)
    if analysis_dir:
        result=Path(analysis_dir).resolve()
    else:
        options=[run/'自动蒸馏'/'产物',run/'内容分析']
        result=next((p for p in options if (p/'验收记录.json').is_file()),options[0])
    record=read(result/'验收记录.json',{})
    ready=analysis_complete or summary.get('analysis_status') in VALID_ANALYSIS or (
        record.get('status')=='evidence_structure_validated' and (result/'学习指南.html').is_file())
    guide=next((p for p in (result/'学习指南.html',run/'学习指南.html') if p.is_file()),None) if ready else None
    bundle=read(result/'analysis.json',{}) if ready else {}
    state_path=next((p for p in (run/'自动蒸馏'/'自动蒸馏状态.json',result.parent/'自动蒸馏状态.json') if p.is_file()),run/'自动蒸馏'/'自动蒸馏状态.json')
    model_state=read(state_path,{})
    usage=summary.get('llm_usage',model_state.get('usage',{}))
    if not isinstance(usage,dict):usage={}
    provider=summary.get('llm_provider',model_state.get('provider'))
    cloud=summary.get('privacy',model_state.get('privacy'))=='text_to_bailian_cloud'
    mode='百炼云端文字分析' if cloud else '本地模型分析' if provider else '提取 / Agent 分析'
    if analysis_complete:
        status='分析产物已生成';scope_note='本页展示已校验的分析产物，其他流水线阶段请查看原运行记录。'
    elif summary.get('status')=='failed':
        status='流程有失败阶段';scope_note='已完成的文件仍可查看，失败阶段与恢复入口见下方运行记录。'
    elif ready:
        status='产物已生成';scope_note='结构检查通过不等于内容已人工核对。'
    else:
        status='提取完成，内容分析待完成';scope_note='可以交给 Agent 接续，或配置本地模型 / 百炼后继续分析。'
    esc=lambda x:html.escape(str(x),quote=True)
    def link(label,path):
        path=Path(path)
        return f'<a href="{esc(href(path,output.parent))}">{esc(label)}</a>' if path.is_file() else ''
    def card(title,description,path=None):
        action=link('打开',path) if path else ''
        return f'<article class="card"><h3>{esc(title)}</h3><p>{esc(description)}</p>'+(
            action if action else '<span class="muted">本次尚未生成</span>')+'</article>'
    parts=['''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视频蒸馏 · 结果入口</title><style>
:root{color-scheme:light;--ink:#253447;--muted:#687586;--line:#dce5ec;--accent:#126b65}*{box-sizing:border-box}body{margin:0;background:#f4f7fa;color:var(--ink);font:16px/1.7 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1080px;margin:auto;padding:32px 24px 70px}h1{font-size:30px;margin:8px 0}h2{margin-top:32px;font-size:21px}h3{font-size:18px;margin:0}p{margin:8px 0 14px}a{color:var(--accent);overflow-wrap:anywhere}.hero,.card,details{background:#fff;border:1px solid var(--line);border-radius:14px;padding:20px}.hero{border-top:4px solid var(--accent)}.badge{display:inline-block;padding:4px 10px;background:#e4f2ef;color:#155e57;border-radius:8px;font-size:14px}.muted{color:var(--muted);font-size:14px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{display:flex;flex-direction:column}.card p{flex:1}.stats{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0}.stat strong{display:block;font-size:23px}.stat span{font-size:13px;color:var(--muted)}details{margin:12px 0}summary{cursor:pointer;font-weight:600}.links{display:flex;gap:14px;flex-wrap:wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#f6f8fa;padding:12px;border-radius:8px}li{overflow-wrap:anywhere}input{width:100%;max-width:460px;border:1px solid var(--line);border-radius:8px;padding:11px;font:inherit}footer{margin-top:28px;color:var(--muted);font-size:13px}@media(max-width:760px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:500px){main{padding:18px 14px}.grid{grid-template-columns:1fr}h1{font-size:25px}}
</style></head><body><main>''']
    parts.append(f'<section class="hero"><span class="badge">{esc(status)}</span><h1>视频蒸馏结果</h1><p>{esc(scope_note)}</p><p class="muted">处理方式：{esc(mode)}'+(' · 原稿文字/可选 OCR 已按所选模式发送给百炼' if cloud else '')+'</p>')
    sources=summary.get('sources',[])
    parts.append('<div class="stats">')
    for value,label in ((len(sources),'本次有产物的视频'),(len(bundle.get('claims',[])),'有证据的判断'),(len(bundle.get('relations',[])),'知识关系')):
        parts.append(f'<div class="stat"><strong>{value}</strong><span>{label}</span></div>')
    parts.append('</div><p class="muted">机器提取与模型分析可能有误；重要数字、术语、因果及画面操作请回原视频核对。</p></section>')
    parts.append('<h2>学习与查证</h2><section class="grid">')
    parts.append(card('学习指南','先读概念、步骤、实例与自测。',guide))
    parts.append(card('知识关系图','查看前提、步骤、因果、例外、冲突及原文证据。',result/'知识关系图.html' if ready else None))
    parts.append(card('全部提取稿','搜索本次视频文字，查看时间点。',run/'总索引.html'))
    parts.append(card('术语出处','查术语出现在哪个视频、哪个时间点。',run/'术语反向索引.html'))
    parts.append(card('术语共现图','用于查找一起出现的概念；连线不表示因果。',run/'术语共现图.html'))
    parts.append(card('跨视频综合','查看共同结论、互补、冲突与未解决问题。',result/'跨视频综合.md' if ready else None))
    parts.append('</section><h2>视频原稿与详细分析</h2><label for="filter">查找视频或待核对内容</label><p><input id="filter" type="search" placeholder="输入标题或关键词"></p>')
    analyses={a['source_id']:a for a in bundle.get('analyses',[]) if isinstance(a,dict)}
    for i,source in enumerate(sources):
        sid=source['id'];a=analyses.get(sid)
        title=source.get('title',sid)
        raw=run/'原稿快照'/sid
        if not raw.is_dir():raw=summary_path.parent/'逐字稿'/sid
        links=[link('原始机器稿',raw/'原始提取.md'),link('原始片段 JSON',raw/'原始提取.json'),
               link('校对副本',run/'校对稿'/sid/'原始提取.md')]
        if a:
            pos=next(j for j,row in enumerate(bundle['analyses']) if row['source_id']==sid)
            links.append(link('内容分析',result/f'{pos+1:03d}_内容分析.md'))
        links.append(link('画面采样',run/'视觉资料'/sid/'视觉核对.html'))
        if source.get('path'):links.append(link('原视频',source['path']))
        parts.append(f'<details data-search-item><summary>{i+1}. {esc(title)}</summary><p class="muted">提取方式：{esc(source.get("method","机器提取"))} · 未人工逐字核对</p><div class="links">'+''.join(x for x in links if x)+'</div></details>')
    if not sources:parts.append('<p>本次没有成功提取的来源，请检查失败阶段。</p>')
    parts.append('<h2>待核对项</h2>')
    ids={c['id']:c for c in bundle.get('claims',[]) if isinstance(c,dict)}
    pending=[]
    for a in bundle.get('analyses',[]):
        pending += [cid for cid in a.get('sections',{}).get('待核对',[]) if cid in ids]
    if pending:
        parts.append('<ul>')
        for cid in dict.fromkeys(pending):
            c=ids[cid]
            evidence='；'.join(f"{e['source_id']} {e['start']}–{e['end']} 秒" for e in c.get('evidence',[]))
            parts.append(f'<li data-search-item><strong>{esc(c["text"])}</strong><br><span class="muted">{esc(c.get("conditions",""))} · {esc(evidence)}</span></li>')
        parts.append('</ul>')
    else:parts.append('<p class="muted">尚未登记待核对项，不表示所有内容已核验。优先抽查数字、专有名词和知识关系。</p>')
    parts.append('<h2>运行与恢复</h2><details><summary>查看阶段记录、用量与生成文件</summary>')
    if usage:
        parts.append(f'<p>本次请求 {esc(usage.get("request_count",0))} 次 · 输入 {esc(usage.get("prompt_tokens",0))} Token · 输出 {esc(usage.get("completion_tokens",0))} Token · 未返回用量 {esc(usage.get("requests_without_usage",0))} 次。</p><p class="muted">用量不是金额；缓存复用不再次请求 API，实际费用以服务账单为准。</p>')
    parts.append('<ul>')
    stage_names={'environment':'环境检查','term-correction':'校对副本','auto-distill':'模型蒸馏','evidence-analysis':'证据分析','guide':'指南渲染','index':'提取稿索引','term-index':'术语索引','cooccurrence-graph':'术语共现图'}
    stage_status={'success':'完成','failed':'失败','warning':'提醒','blocked':'前置失败，未执行'}
    for stage in summary.get('stages',[]):
        name=stage_names.get(stage['name'],stage['name'])
        parts.append(f'<li>{esc(name)}：{esc(stage_status.get(stage["status"],stage["status"]))}')
        if stage['status'] in ('failed','blocked'):
            parts.append('<pre>'+esc(stage.get('log',''))+'</pre>')
        parts.append('</li>')
    parts.append('</ul><div class="links">'+link('本次摘要',summary_path)+link('修订记录',run/'修订记录.json')+
                 link('分析包',result/'analysis.json')+link('验收问题',result/'验收记录.json')+
                 link('模型运行记录',state_path)+
                 link('知识技能包入口',state_path.parent/'技能包'/'video-distilled-knowledge'/'SKILL.md')+'</div>')
    parts.append('<p class="muted">恢复方法：使用相同输入、输出目录和模型配置重新运行 pipeline；已核验的原稿及分析缓存会复用。独立分析时用新的分析输出目录并共享原 cache。</p></details>')
    parts.append('<footer>本页是本地结果入口，不代表内容已发布。每次运行保留自己的入口页；输出目录根入口指向最新一轮。</footer>')
    parts.append('''<script>document.getElementById('filter').addEventListener('input',function(){const key=this.value.trim().toLowerCase();document.querySelectorAll('[data-search-item]').forEach(item=>{item.hidden=key&&!item.textContent.toLowerCase().includes(key);});});</script></main></body></html>''')
    temp=output.with_suffix('.html.tmp')
    temp.write_text('\n'.join(parts),encoding='utf-8');temp.replace(output)
    return output


def main(argv=None):
    ap=argparse.ArgumentParser(description='为已有运行生成离线结果入口')
    ap.add_argument('--summary',required=True);ap.add_argument('--out')
    args=ap.parse_args(argv)
    try:print(build(args.summary,args.out));return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:print(str(exc),file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
