"""Read bounded local launch evidence; never execute log contents."""
import re
from pathlib import Path


def attach_runtime_failures(folder, active):
    log=Path(folder).parent/'logs'/'latest.log'
    try:
        if log.stat().st_size>8<<20:return
        text=log.read_text(encoding='utf8',errors='replace')
        stamp=log.stat().st_mtime_ns
    except OSError:return
    by_name={p.name:(p,m) for p,m in active.items() if m}
    def mark(name,reason):
        if name not in by_name:return
        p,mods=by_name[name]
        try:
            if p.stat().st_mtime_ns>stamp:return
        except OSError:return
        mods[0]['_runtime_failure']=reason
    for line in text.splitlines():
        if 'Encountered error while transforming jar file ' in line:
            path=line.split('Encountered error while transforming jar file ',1)[1].strip()
            mark(path.replace('\\','/').rsplit('/',1)[-1],'最近启动日志：Connector 转换此文件失败，需要原生 Forge 候选')
        match=re.search(r'Missing language .* wanted by (.+\.jar), found ',line)
        if match:mark(match[1],'最近启动日志：加载语言版本不受支持，需要原生 Forge 候选')
        match=re.search(r"Mod ID: '([^']+)', Requested by: '([^']+)', Expected range: '([^']+)', Actual version: '\[MISSING\]'",line)
        if match:
            for p,mods in active.items():
                if mods and mods[0]['id']==match[1] and mods[0].get('_platform')=='fabric':
                    mark(p.name,'最近启动日志：Forge 未加载这个已存在的前置，需要原生 Forge 候选')

        match=re.search(r'from mod ([a-z0-9_-]+) failed injection check',line)
        if not match:match=re.search(r'Mixin apply for mod ([a-z0-9_-]+) failed',line)
        if not match and 'FAILED during APPLY' in line:
            match=re.search(r'from mod ([a-z0-9_-]+)\]',line)
        if match:
            for p,mods in active.items():
                if mods and mods[0]['id']==match[1] and mods[0].get('_platform')=='fabric':
                    mark(p.name,'最近启动日志：此 Fabric 模组 Mixin 注入失败，需要原生 Forge 候选')
