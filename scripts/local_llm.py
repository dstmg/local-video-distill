"""JSON client for local models and explicitly configured Alibaba Cloud Bailian."""
import ipaddress
import json
import os
from pathlib import Path
import re
import time
from decimal import Decimal
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('模型服务重定向被拒绝，不向其他地址转发原稿或 Key')


def bailian_url(base_url):
    """Only official HTTPS compatible endpoints may receive a Bailian credential."""
    if not isinstance(base_url, str):
        raise ValueError('百炼 base_url 必须是字符串')
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or ''
    legacy = {'dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com', 'dashscope-us.aliyuncs.com'}
    workspace = re.fullmatch(r'[a-zA-Z0-9_-]+\.(cn-beijing|ap-southeast-1|cn-hongkong|ap-northeast-1)\.maas\.aliyuncs\.com', host)
    if (parsed.scheme != 'https' or (host not in legacy and not workspace)
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') != '/compatible-mode/v1'):
        raise ValueError('百炼必须使用官方 HTTPS 地址及 /compatible-mode/v1 路径')
    if '{' in base_url or '}' in base_url:
        raise ValueError('请将业务空间地址占位符替换为实际 Workspace ID')
    return base_url.rstrip('/')


def load_config(path):
    config=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(config,dict): raise ValueError('模型配置必须是对象')
    config.setdefault('provider','ollama')
    if config['provider'] not in {'ollama','local-compatible','bailian'}:
        raise ValueError('provider 只能是 ollama、local-compatible 或 bailian')
    if any(name in config for name in ('api_key', 'token', 'secret', 'authorization')):
        raise ValueError('不要把 Key 写进配置文件；使用 api_key_env 指定环境变量名')
    cloud = config['provider'] == 'bailian'
    config.setdefault('base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1' if cloud else 'http://127.0.0.1:11434/v1')
    config.setdefault('timeout',300)
    config.setdefault('repair_attempts',2)
    config.setdefault('request_retries',2)
    config.setdefault('chunk_chars',2500)
    config.setdefault('max_input_chars',10000)
    config.setdefault('max_output_tokens',4096)
    config.setdefault('context_length',16384)
    if cloud:
        config['base_url'] = bailian_url(config['base_url'])
        config.setdefault('api_key_env', 'DASHSCOPE_API_KEY')
        if not isinstance(config['api_key_env'], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', config['api_key_env']):
            raise ValueError('api_key_env 必须是合法的环境变量名')
    else:
        parsed=urllib.parse.urlsplit(config['base_url'])
        host=parsed.hostname
        try: local=host=='localhost' or ipaddress.ip_address(host).is_loopback
        except (ValueError,TypeError): local=False
        if parsed.scheme not in {'http','https'} or not local or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('本地模式只接受无凭证的本机 loopback 模型地址')
    model=config.get('model')
    if not isinstance(model,str) or not model.strip():
        raise ValueError('请指定实际可用的模型名')
    if not cloud and 'cloud' in model.lower():
        raise ValueError('请指定已安装的本地模型，不能使用 cloud 模型')
    if cloud and not re.fullmatch(r'qwen[A-Za-z0-9_.:-]*', model):
        raise ValueError('百炼模式请选择通义千问文本模型（示例 qwen-plus）')
    for name in ('timeout','chunk_chars','max_input_chars','max_output_tokens','context_length'):
        if not isinstance(config[name],int) or isinstance(config[name],bool) or config[name]<=0: raise ValueError(name+' 必须是正整数')
    for name in ('repair_attempts','request_retries'):
        if not isinstance(config[name],int) or isinstance(config[name],bool) or not 0<=config[name]<=5: raise ValueError(name+' 必须在0–5之间')
    return config


def parse_json(content):
    if not isinstance(content,str): raise ValueError('模型没有返回文字 JSON')
    text=content.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if len(lines)<3 or lines[-1].strip()!='```': raise ValueError('JSON 代码围栏不完整')
        text='\n'.join(lines[1:-1])
    data=json.loads(text)
    if not isinstance(data,dict): raise ValueError('模型输出顶层必须是对象')
    return data


class Client:
    def __init__(self,config):
        self.config=config
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.usage = {'request_count': 0, 'responses_with_usage': 0,
                      'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        self.last_usage = {}

    def api_key(self):
        name = self.config['api_key_env']
        secret = os.environ.get(name, '').strip()
        if not secret:
            raise ValueError('缺少百炼 API Key：请设置环境变量 ' + name)
        if '\n' in secret or '\r' in secret:
            raise ValueError('百炼 API Key 格式无效')
        return secret

    def request(self,url,payload):
        headers = {'Content-Type': 'application/json'}
        cloud = self.config['provider'] == 'bailian'
        if cloud:
            base = bailian_url(self.config['base_url'])
            if url != base + '/chat/completions':
                raise ValueError('请求地址与所选百炼入口不一致，拒绝发送 Key')
            headers['Authorization'] = 'Bearer ' + self.api_key()
        req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                                  headers=headers,method='POST')
        for attempt in range(self.config['request_retries']+1):
            if cloud and 'messages' in payload and self.config.get('budget_ledger'):
                self.reserve_budget(payload)
            if 'messages' in payload:
                self.usage['request_count'] += 1
            try:
                with self.opener.open(req,timeout=self.config['timeout']) as response:
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as exc:
                label = '百炼 API' if cloud else '本地模型'
                if exc.code not in {429,500,502,503,504}:
                    hints = {400: '检查模型是否支持 JSON、非思考模式及输出长度',
                             401: '检查 Key 与 endpoint 地域是否匹配',
                             403: '检查模型权限及服务开通状态',
                             404: '检查模型名、业务空间和入口路径'}
                    raise ValueError(label+' HTTP '+str(exc.code)+'：'+hints.get(exc.code,'请求被拒绝')) from None
                if attempt==self.config['request_retries']: raise ValueError(label+' 请求重试耗尽：HTTP '+str(exc.code)) from None
            except (urllib.error.URLError,TimeoutError) as exc:
                if attempt==self.config['request_retries']:
                    message = '百炼 API 不可用或超时，请检查网络与地域入口' if cloud else '本地模型不可用或超时；请启动服务并确认模型已安装'
                    raise ValueError(message) from None
            time.sleep(min(2**attempt,8))

    def reserve_budget(self, payload):
        """Persist conservative reservations before sending; retries are never refunded."""
        cfg = self.config
        if cfg['model'] != 'qwen-plus' or cfg['base_url'] != 'https://dashscope.aliyuncs.com/compatible-mode/v1':
            raise ValueError('当前费用保护仅支持北京 qwen-plus 非思考模式')
        bound = len(json.dumps(payload['messages'], ensure_ascii=False).encode('utf-8')) + 4096
        if bound > 128000:
            raise ValueError('输入超出已核对的计费档位，停止请求')
        cap = Decimal(str(cfg.get('max_cost_cny', 0)))
        if not cap.is_finite() or cap <= 0:
            raise ValueError('max_cost_cny 必须是有限正数')
        amount = (Decimal(bound) * Decimal('0.8') + Decimal(payload['max_tokens']) * Decimal('2')) / 1000000
        path = Path(cfg['budget_ledger']).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(path.suffix + '.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError('费用记录正被占用，停止请求') from None
        try:
            os.close(fd)
            data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'reserved_cny':'0','requests':0}
            total = Decimal(data['reserved_cny']) + amount
            if not total.is_finite() or total > cap:
                raise ValueError('保守费用预留将超过预算，停止请求')
            data.update(reserved_cny=str(total), requests=data['requests']+1,
                        cap_cny=str(cap), pricing_date='2026-10-12', input_rate='0.8', output_rate='2',
                        note='按 UTF-8 字节加4096估计输入上界；输出按最大长度；预留不是实际账单')
            tmp = path.with_suffix(path.suffix + '.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(path)
        finally:
            lock.unlink()
    def preflight(self):
        if self.config['provider']=='bailian':
            bailian_url(self.config['base_url'])
            self.api_key()  # Presence only; no chargeable call and no transcript upload.
            return
        if self.config['provider']=='ollama':
            parsed=urllib.parse.urlsplit(self.config['base_url'])
            url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'/api/show','',''))
            data=self.request(url,{'model':self.config['model']})
            if data.get('remote_host') or data.get('remote_model') or data.get('cloud'):
                raise ValueError('Ollama 返回远端/云模型，拒绝上传原稿')
    def complete(self,messages):
        self.last_usage = {}
        size=sum(len(str(m['content'])) for m in messages)
        if size>self.config['max_input_chars']:
            raise ValueError('分析输入超过 max_input_chars，请提高模型上下文或缩小本批范围；未静默截断')
        if self.config['provider']=='ollama':
            parsed=urllib.parse.urlsplit(self.config['base_url'])
            url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,'/api/chat','',''))
            payload={'model':self.config['model'],'messages':messages,'stream':False,'format':'json','think':False,
                     'options':{'temperature':0,'num_ctx':self.config['context_length'],
                                'num_predict':self.config['max_output_tokens']}}
            data=self.request(url,payload)
            self.record_usage(data)
            if data.get('done_reason')=='length':raise ValueError('模型输出被截断，请提高 max_output_tokens')
            try:return parse_json(data['message']['content'])
            except (KeyError,TypeError) as exc:raise ValueError('本地模型响应缺少 message.content') from exc
        payload={'model':self.config['model'],'messages':messages,'stream':False,
                 'temperature':0,'max_tokens':self.config['max_output_tokens'],
                 'response_format':{'type':'json_object'}}
        if self.config['provider']=='bailian':
            payload.update({'temperature': 0.1, 'enable_thinking': False, 'enable_search': False})
        data=self.request(self.config['base_url'].rstrip('/')+'/chat/completions',payload)
        self.record_usage(data)
        try:
            choice=data['choices'][0]
            if choice.get('finish_reason')=='length': raise ValueError('模型输出被截断，请提高 max_output_tokens')
            if choice.get('finish_reason') in {'content_filter', 'sensitive'}:
                raise ValueError('模型服务拒绝生成该内容，未生成完整蒸馏结果')
            return parse_json(choice['message']['content'])
        except (KeyError,IndexError,TypeError) as exc:
            raise ValueError('模型响应不是兼容的 Chat Completions 格式') from exc

    def record_usage(self, data):
        """Record server-reported tokens; never estimate currency charges or log secrets."""
        if not isinstance(data, dict):
            return
        reported = data.get('usage')
        if self.config['provider']=='ollama':
            reported = {'prompt_tokens':data.get('prompt_eval_count'),
                        'completion_tokens':data.get('eval_count')}
        if not isinstance(reported, dict):
            return
        actual = {name:value for name,value in reported.items()
                  if name in ('prompt_tokens','completion_tokens','total_tokens')
                  and type(value) is int and value >= 0}
        if not actual:
            return
        if 'total_tokens' not in actual and {'prompt_tokens','completion_tokens'} <= set(actual):
            actual['total_tokens'] = actual['prompt_tokens'] + actual['completion_tokens']
        self.last_usage = actual
        self.usage['responses_with_usage'] += 1
        for name,value in actual.items():
            self.usage[name] += value
