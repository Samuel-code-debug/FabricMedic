import hashlib
import io
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.error import HTTPError
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
        if prerelease and not floor:
            return None  # Qualifier semantics differ between Fabric and Maven; do not guess.
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
    if loader=='mix':
        with zipfile.ZipFile(source) as jar:
            names=set(jar.namelist())
            if 'META-INF/mods.toml' in names or 'META-INF/jarjar/metadata.json' in names:
                return metadata(source,'forge')
            if 'META-INF/MANIFEST.MF' in names and 'META-INF/services/cpw.mods.modlauncher.api.ITransformationService' in names:
                manifest=jar.read('META-INF/MANIFEST.MF').decode('utf8','replace').replace('\r\n ','')
                fields=dict(line.split(': ',1) for line in manifest.splitlines() if ': ' in line)
                if fields.get('Automatic-Module-Name')=='org.sinytra.connector':
                    return [dict(id='connector',provides=['connectormod'],version=fields.get('Implementation-Version','?'),depends={'fabric_api':'*'})]
        mods=metadata(source,'fabric')
        if mods:
            mods[0].setdefault('depends',{}).setdefault('connector','*')
            if mods[0]['id']=='fabric-api':
                mods[0].setdefault('breaks',{})['fabric_api']='*'
        return mods
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
            m = json.loads(z.read('fabric.mod.json').decode('utf-8-sig'), strict=False)
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


def analyze(active, game, repairs=None, diagnostics=None):
    providers = {}
    pairs, missing, notes = {}, {}, []
    issues = []
    def issue(level, target, owner, rule, installed, reason):
        issues.append(dict(level=level,target=target,owner=owner,rule=rule,installed=installed,reason=reason))
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
                            if any(not group for group in active.values()):
                                issue('review',target,name,rule,[],'有未识别文件，尚不能确认前置缺失')
                            else:
                                missing.setdefault(target,[]).append((name,rule))
                                issue('error',target,name,rule,[],'缺少必需前置')
                        elif True not in results:
                            level='review' if None in results else 'error'
                            installed=[game] if target=='minecraft' else [v['version'] for _,v in candidates]
                            issue(level,target,name,rule,installed,'版本格式尚无法可靠比较' if level=='review' else '已安装版本不符合要求')
                            if repairs is not None and None not in results and len(candidates)==1:
                                g,provider=candidates[0]
                                if active[g][0] is provider and provider['id']==target:
                                    repairs[target]=g
                    else:
                        for (g,_),res in zip(candidates,results):
                            if res is True:
                                if kind=='breaks':pair(f,g,'严重冲突：'+f'{name} → {target}')
                                else:issue('info',target,name,rule,[providers[target][0][1]['version']],'模组声明了兼容性建议')
                            elif res is None:
                                issue('review',target,name,rule,[v['version'] for _,v in candidates],'无法核实冲突范围')
    if diagnostics is not None: diagnostics.extend(issues)
    groups={}
    for item in issues:
        if item['reason']=='缺少必需前置':continue
        groups.setdefault((item['level'],item['target'],item['reason']),[]).append(item)
    for (level,target,reason),items in groups.items():
        label={'error':'明确问题','review':'待核实','info':'普通提示'}[level]
        notes.append(f"[{label}] {target}：{reason}，涉及 {len(set(x['owner'] for x in items))} 个模组")
    return pairs,missing,notes


class JobStopped(RuntimeError):
    pass


class LookupControl:
    def __init__(self, progress=lambda message: None, seconds=120):
        self.cancelled=threading.Event()
        self.deadline=time.monotonic()+seconds
        self.progress=progress
    def check(self):
        if self.cancelled.is_set():raise JobStopped('已取消查找，游戏文件未修改')
        if time.monotonic()>=self.deadline:raise JobStopped('查找超时，已停止后续请求；游戏文件未修改')
    def report(self,message):
        self.check()
        self.progress(message)


def fetch(url, limit, control=None):
    control=control or LookupControl()
    control.check()
    request=Request(url,headers={'User-Agent':'FabricMedic/2.1 (local desktop utility)'})
    try:
        with urlopen(request,timeout=max(.1,min(8,control.deadline-time.monotonic()))) as r:
            chunks=[];total=0;last=0
            while True:
                control.check()
                data=r.read1(min(65536,limit+1-total))
                if not data:break
                chunks.append(data);total+=len(data)
                if total>limit:raise ValueError('下载超出大小限制')
                if time.monotonic()-last>=1:
                    control.report(f'正在接收数据：{total/1048576:.1f} MB')
                    last=time.monotonic()
        control.check()
        return b''.join(chunks)
    except HTTPError:
        raise
    except (OSError, TimeoutError) as exc:
        control.check()
        raise RuntimeError('网络请求失败或等待超过 8 秒，请稍后重试：'+str(exc)) from exc


def cached_jar(file, control=None):
    control=control or LookupControl()
    control.check()
    key=file['hashes']['sha512'].lower()
    if not re.fullmatch('[0-9a-f]{128}',key):
        raise ValueError('无效 SHA-512')
    root=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'FabricMedic'/'downloads'
    path=root/(key+'.jar')
    try:
        if path.stat().st_size <= 128<<20:
            data=path.read_bytes()
            if hashlib.sha512(data).hexdigest()==key:
                control.report('复用已校验的下载缓存')
                return data
    except OSError:
        pass
    control.report('下载 '+file['filename'])
    data=fetch(file['url'],128<<20,control)
    control.report('校验 SHA-512：'+file['filename'])
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


def resolve(target, requirements, game, folder, accept=None, loader='fabric', project=None, file_loader=None, control=None):
    control=control or LookupControl()
    control.check()
    if loader=='mix':
        bridge={'connector':'connector','connectormod':'connector','fabric_api':'forgified-fabric-api','fabric-api':'forgified-fabric-api','fabric':'forgified-fabric-api'}
        errors=[]
        for platform in (('forge',) if target in bridge else ('forge','fabric')):
            try:
                return resolve(target,requirements,game,folder,accept,platform,bridge.get(target),'mix',control)
            except ValueError as exc:
                errors.append(str(exc))
            except HTTPError as exc:
                if exc.code!=404:raise
                errors.append(str(exc))
        raise ValueError('没有找到兼容桥接组合的 '+target+'：'+' / '.join(errors))
    aliases={'cloth-config':'cloth-config','cloth_config':'cloth-config','fabric':'fabric-api',
             'fabric-api':'fabric-api','mezz_config':'mezzconfig','fabric-language-kotlin':'fabric-language-kotlin'}
    slug=project or aliases.get(target,target.replace('_','-'))
    query=urlencode({'loaders':json.dumps([loader]), 'game_versions':json.dumps([game])})
    url='https://api.modrinth.com/v2/project/'+quote(slug,safe='')+'/version?'+query
    stamp,versions=_list_cache.get(url,(0,None))
    if versions is None or time.monotonic()-stamp>120:
        control.report(f'获取 {target} 的 {loader} / {game} 版本列表')
        versions=json.loads(fetch(url,12<<20,control))
        _list_cache[url]=(time.monotonic(),versions)
    control.check()
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
            control.report(f'{target}：检查候选 {start-len(batch)+1}–{start} / {len(candidates)}')
            jobs=[pool.submit(cached_jar,f,control) for _,f in batch]
            for (v,_),job in zip(batch,jobs):
                data=job.result()
                control.check()
                mods=metadata(io.BytesIO(data),file_loader or loader)
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
