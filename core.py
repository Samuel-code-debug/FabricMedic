import hashlib
import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


def matches(version, rule):
    """True, False, or None when comparison needs the loader itself."""
    def term(t):
        if t == '*':
            return True
        m = re.fullmatch(r'(>=|<=|>|<|=|~|\^)?(.+)', t)
        if not m:
            return None
        op, ref = m.groups()
        if op in (None, '=') and version == ref:
            return True
        def parts(s):
            s = s.split('+')[0]
            return list(map(int, s.split('.'))) if re.fullmatch(r'\d+(?:\.\d+)*', s) else None
        a = parts(version)
        wildcard = re.fullmatch(r'(\d+(?:\.\d+)*)(?:\.[xX*])+', ref)
        if wildcard and not op and a is not None:
            prefix = parts(wildcard[1])
            return (a + [0]*len(prefix))[:len(prefix)] == prefix
        floor = ref.endswith('-')
        prerelease='-' in ref
        b = parts(ref.split('-',1)[0] if prerelease else ref)
        if a is None or b is None:
            return None
        size = max(3, len(a), len(b))
        a += [0]*(size-len(a))
        b += [0]*(size-len(b))
        if prerelease and a==b and op in ('<','<=','>','>=',None,'='):
            return op in ('>','>=')
        return {None:a==b, '=':a==b, '>':a>b, '<':a<b, '>=':a>=b, '<=':a<=b,
                '^':a>=b and a[0]==b[0], '~':a>=b and a[:2]==b[:2]}[op]
    alternatives = []
    for expr in rule if isinstance(rule,list) else [rule]:
        terms = [term(t) for t in expr.split()] if isinstance(expr,str) else []
        alternatives.append(False if False in terms else None if not terms or None in terms else True)
    return True if True in alternatives else None if None in alternatives else False


def metadata(source,loader='fabric'):
    if loader=='forge':
        from forge import read
        return read(source)
    remaining = 128 << 20
    def visit(src, depth):
        nonlocal remaining
        with zipfile.ZipFile(src) as z:
            if 'fabric.mod.json' not in z.namelist():
                return []
            if z.getinfo('fabric.mod.json').file_size > 1 << 20:
                raise ValueError('元数据过大')
            m = json.loads(z.read('fabric.mod.json').decode('utf-8-sig'))
            if m.get('schemaVersion') != 1:
                raise ValueError('未识别的 Fabric 元数据版本')
            if not isinstance(m['id'],str) or not isinstance(m['version'],str):
                raise ValueError('无效模组标识')
            for field in ('depends','breaks','conflicts'):
                if not isinstance(m.get(field,{}),dict):
                    raise ValueError('无法识别依赖声明')
            if not isinstance(m.get('provides',[]),list) or not all(isinstance(s,str) for s in m.get('provides',[])):
                raise ValueError('无法识别模组别名')
            if m.get('environment') == 'server':
                return []
            result = [m]
            for item in m.get('jars', []):
                info = z.getinfo(item['file'])
                remaining -= info.file_size
                if remaining < 0 or depth >= 8:
                    raise ValueError('嵌套文件超出检查范围')
                result.extend(visit(io.BytesIO(z.read(info)),depth+1))
            return result
    return visit(source,0)


def ids(m):
    return [m['id'], *m.get('provides',[])]


def analyze(active, game, repairs=None):
    providers = {}
    pairs, missing, notes = {}, {}, []
    for file, mods in active.items():
        for m in mods:
            for key in ids(m):
                providers.setdefault(key,[]).append((file,m))
    def pair(a,b,why):
        if a != b:
            pairs.setdefault(tuple(sorted((a,b))),set()).add(why)
    for f, mods in active.items():
        for m in mods:
            name = m['id']
            if m is mods[0]:
                for g, other in providers[name]:
                    if active[g][0] is other and other['id']==name:
                        pair(f,g,'相同模组 ID：'+name)
            for kind in ('depends','breaks','conflicts'):
                for target, rule in m.get(kind,{}).items():
                    if target in ('java','fabricloader'):
                        continue
                    candidates = providers.get(target,[])
                    results = [matches(v['version'],rule) for _,v in candidates]
                    if target=='minecraft':
                        results=[matches(game,rule)]
                    if kind=='depends':
                        if not results:
                            missing.setdefault(target,[]).append((name,rule))
                        elif True not in results:
                            notes.append(f'{name} 需要 {target} {rule}（当前不满足或无法判定）')
                            if repairs is not None and None not in results and len(candidates)==1:
                                g,provider=candidates[0]
                                if active[g][0] is provider and provider['id']==target:
                                    repairs[target]=g
                    else:
                        for (g,_),res in zip(candidates,results):
                            if res is True:
                                pair(f,g,('严重冲突' if kind=='breaks' else '兼容性警告')+f'：{name} → {target}')
                            elif res is None:
                                notes.append(f'无法判断 {name} 与 {target} 的冲突范围 {rule}')
    return pairs,missing,notes


def fetch(url, limit):
    request=Request(url,headers={'User-Agent':'FabricMedic/0.1 (local desktop utility)'})
    with urlopen(request,timeout=18) as r:
        data=r.read(limit+1)
    if len(data)>limit:
        raise ValueError('下载超出大小限制')
    return data


def cached_jar(file):
    key=file['hashes']['sha512'].lower()
    if not re.fullmatch('[0-9a-f]{128}',key):
        raise ValueError('无效 SHA-512')
    root=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'FabricMedic'/'downloads'
    path=root/(key+'.jar')
    try:
        if path.stat().st_size <= 128<<20:
            data=path.read_bytes()
            if hashlib.sha512(data).hexdigest()==key:
                return data
    except OSError:
        pass
    data=fetch(file['url'],128<<20)
    if hashlib.sha512(data).hexdigest()!=key:
        raise ValueError('SHA-512 校验失败')
    try:
        root.mkdir(parents=True,exist_ok=True)
        entries=sorted(root.glob('*.jar'),key=lambda p:p.stat().st_mtime)
        total=sum(p.stat().st_size for p in entries)+len(data)
        for item in entries:
            if total<=256<<20:
                break
            total-=item.stat().st_size
            item.unlink()
        tmp=root/(uuid.uuid4().hex+'.tmp')
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError:
        pass
    return data


_list_cache={}


def resolve(target, requirements, game, folder, accept=None, loader='fabric'):
    aliases={'cloth-config':'cloth-config','cloth_config':'cloth-config','fabric':'fabric-api',
             'fabric-api':'fabric-api','mezz_config':'mezzconfig','fabric-language-kotlin':'fabric-language-kotlin'}
    slug=aliases.get(target,target.replace('_','-'))
    query=urlencode({'loaders':json.dumps([loader]), 'game_versions':json.dumps([game])})
    url='https://api.modrinth.com/v2/project/'+quote(slug,safe='')+'/version?'+query
    stamp,versions=_list_cache.get(url,(0,None))
    if versions is None or time.monotonic()-stamp>120:
        versions=json.loads(fetch(url,12<<20))
        _list_cache[url]=(time.monotonic(),versions)
    candidates=[]
    for v in versions[:40]:
        # Download only a candidate whose published version plausibly satisfies the constraints.
        rules=[r for _,r in requirements]
        if any(matches(v['version_number'],r) is False for r in rules):
            continue
        files=[f for f in v['files'] if f.get('primary') and f['filename'].lower().endswith('.jar')]
        if not files:
            continue
        file=files[0]
        if urlsplit(file['url']).hostname!='cdn.modrinth.com' or not file['url'].startswith('https://'):
            raise ValueError('下载地址不属于 Modrinth CDN')
        candidates.append((v,file))
    # Try the newest alone; only prefetch in pairs when we need older candidates.
    with ThreadPoolExecutor(max_workers=2) as pool:
        start=0
        while start<len(candidates):
            batch=candidates[start:start+(2 if start else 1)]
            start+=len(batch)
            jobs=[pool.submit(cached_jar,f) for _,f in batch]
            for (v,_),job in zip(batch,jobs):
                data=job.result()
                mods=metadata(io.BytesIO(data),loader)
                if accept and not accept(mods):
                    continue
                if any(target in ids(m) and all(matches(m['version'],r) is True for r in rules) for m in mods):
                    if matches(game,mods[0].get('depends',{}).get('minecraft','*')) is False:
                        continue
                    path=folder/(re.sub(r'[^a-zA-Z0-9._-]','_',slug+'-'+v['id'])+'.jar')
                    path.write_bytes(data)
                    return path,mods
    raise ValueError('没有找到能核实模组 ID 和版本要求的对应加载器文件')


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def verify_selection(live, changed, game):
    providers={}
    for group in live.values():
        for mod in group:
            for key in ids(mod):
                providers.setdefault(key,[]).append(mod['version'])
    touched={key for p in changed for mod in live[p] for key in ids(mod)}
    problems=[]
    for file,group in live.items():
        for mod in group:
            for key,rule in mod.get('depends',{}).items():
                if key in ('java','fabricloader'):
                    continue
                versions=[game] if key=='minecraft' else providers.get(key,[])
                checks=[matches(v,rule) for v in versions]
                if True not in checks and (None not in checks or file in changed or key in touched):
                    problems.append(f"{mod['id']} 需要 {key} {rule}")
    for pair,why in analyze(live,game)[0].items():
        if set(pair)&changed or any(not s.startswith('兼容性警告') for s in why):
            problems.extend(sorted(why))
    if problems:
        raise ValueError('；'.join(dict.fromkeys(problems)))


def install_verified(folder, old, staged, kept, game, loader='fabric'):
    plan=dict(kept)
    plan.update(staged)
    verify_selection(plan,set(staged),game)
    batch=apply(folder,old,staged)
    try:
        installed=dict(kept)
        for source,expected in staged.items():
            path=folder/source.name
            installed[path]=metadata(path,loader)
            if digest(path)!=digest(source) or installed[path]!=expected:
                raise ValueError('安装后文件或元数据与下载方案不符：'+path.name)
        verify_selection(installed,{folder/p.name for p in staged},game)
    except Exception as exc:
        restore(folder,batch)
        raise ValueError(f'安装后复查失败，已恢复本批次：{exc}') from exc
    return batch


def backup_root(folder):
    return folder.parent/(folder.name+'-FabricMedic-backups')


def restore(folder, batch):
    root=backup_root(folder)
    if batch.resolve().parent!=root.resolve() or root.is_symlink() or root.is_junction():
        raise ValueError('无效备份位置')
    if (batch/'restored').exists():
        raise ValueError('此批次已恢复')
    manifest=json.loads((batch/'changes.json').read_text(encoding='utf8'))
    actions=[]
    for kind, records in manifest.items():
        if kind not in ('added','removed'):
            raise ValueError('无效备份记录')
        for name,h in records.items():
            if Path(name).name!=name or not name.lower().endswith('.jar') or ':' in name:
                raise ValueError('无效文件名')
            live=folder/name
            saved=batch/name
            src,dst=(live,batch/('undo-'+name)) if kind=='added' else (saved,live)
            if not src.exists():
                continue
            if dst.exists() or src.is_symlink() or digest(src)!=h:
                raise ValueError('文件已变化，无法安全还原：'+name)
            actions.append((src,dst))
    for src,dst in actions:
        src.rename(dst)
    (batch/'restored').touch()


def apply(folder, removed, added):
    root=backup_root(folder)
    if root.is_symlink() or root.is_junction():
        raise ValueError('备份目录不能是链接')
    batch=root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    for p in added:
        if (folder/p.name).exists():
            raise FileExistsError(p.name)
    plan={'removed':{p.name:digest(p) for p in removed},'added':{p.name:digest(p) for p in added}}
    batch.mkdir(parents=True)
    (batch/'changes.json').write_text(json.dumps(plan,ensure_ascii=False),encoding='utf8')
    try:
        for p in removed:
            p.rename(batch/p.name)
        for p in added:
            temp=batch/('stage-'+p.name)
            shutil.copyfile(p,temp)
            if digest(temp)!=plan['added'][p.name]:
                raise ValueError('复制校验失败')
            temp.rename(folder/p.name)
    except Exception:
        restore(folder,batch)
        raise
    return batch
