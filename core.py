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


class ForgeRule(str):
    """Maven range from mods.toml; unsupported qualifiers stay unknown."""


def maven_compare(left,right):
    # Numeric hyphen suffixes used by Moonlight/Supplementaries are numeric
    # Maven items, not SemVer prerelease strings. Only compare the same prefix.
    numeric=re.fullmatch(r'(\d+(?:\.\d+)*)-(\d+(?:\.\d+)*)',left)
    other=re.fullmatch(r'(\d+(?:\.\d+)*)-(\d+(?:\.\d+)*)',right)
    if numeric and other and numeric[1]==other[1]:
        a=list(map(int,numeric[2].split('.')));b=list(map(int,other[2].split('.')))
        size=max(len(a),len(b));a += [0]*(size-len(a));b += [0]*(size-len(b))
        return (a>b)-(a<b)
    def parse(value):
        m=re.fullmatch(r'(\d+(?:\.\d+)*)(?:-(alpha|beta|milestone|rc)[.-]?(\d+))?(\+.*)?',value,re.I)
        if not m:return None
        return list(map(int,m[1].split('.'))), {'alpha':0,'beta':1,'milestone':2,'rc':3,None:4}[m[2].lower() if m[2] else None],int(m[3] or 0),m[4]
    a,b=parse(left),parse(right)
    if a is None or b is None:return None
    av,bv=a[0],b[0];size=max(len(av),len(bv));av += [0]*(size-len(av));bv += [0]*(size-len(bv))
    for x,y in ((av,bv),(a[1],b[1]),(a[2],b[2])):
        if x!=y:return (x>y)-(x<y)
    return 0 if a[3]==b[3] else None


class FabricRule(str):
    """Preserve the declaring loader's comparison semantics through planning."""


def fabric_compare(left, right):
    def parse(value):
        m=re.fullmatch(r'(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]*))?(?:\+[^ ]*)?',value)
        if not m:return None
        return list(map(int,m[1].split('.'))), m[2]
    a,b=parse(left),parse(right)
    if a is None or b is None:return None
    an,ap=a;bn,bp=b
    size=max(len(an),len(bn));an += [0]*(size-len(an));bn += [0]*(size-len(bn))
    if an!=bn:return (an>bn)-(an<bn)
    if ap==bp:return 0
    if ap is None:return 1
    if bp is None:return -1
    if ap=='':return -1
    if bp=='':return 1
    aa,bb=ap.split('.'),bp.split('.')
    for x,y in zip(aa,bb):
        if x==y:continue
        if x.isdigit() and y.isdigit():
            if int(x)==int(y):continue
            return (int(x)>int(y))-(int(x)<int(y))
        if x.isdigit()!=y.isdigit():return -1 if x.isdigit() else 1
        return (x>y)-(x<y)
    return (len(aa)>len(bb))-(len(aa)<len(bb))


def matches(version, rule):
    """True, False, or None when comparison needs the loader itself."""
    def term(t, fabric=False, forge=False):
        if t == '*':
            return True
        m = re.fullmatch(r'(>=|<=|>|<|=|~|\^)?(.+)', t)
        if not m:
            return None
        op, ref = m.groups()
        if op in (None, '=') and version == ref:
            return True
        if forge and ('-' in version or '-' in ref):
            comparison=maven_compare(version,ref)
            if comparison is None:return None
            return {None:comparison==0,'=':comparison==0,'>':comparison>0,'<':comparison<0,'>=':comparison>=0,'<=':comparison<=0}.get(op)
        if fabric:
            wildcard=re.fullmatch(r'(\d+(?:\.\d+)*)(?:\.[xX*])+',ref)
            if wildcard and not op:
                base=wildcard[1];parts=list(map(int,base.split('.')));parts[-1]+=1
                low=fabric_compare(version,base+'-');high=fabric_compare(version,'.'.join(map(str,parts))+'-')
                return None if low is None or high is None else low>=0 and high<0
            comparison=fabric_compare(version,ref)
            if comparison is None:return None
            if op in ('^','~'):
                nums=list(map(int,ref.split('+')[0].split('-')[0].split('.')))
                index=0 if op=='^' else 1
                nums += [0]*max(0,index+1-len(nums));nums=nums[:index+1];nums[index]+=1
                upper=fabric_compare(version,'.'.join(map(str,nums))+'-')
                return comparison>=0 and upper<0
            return {None:comparison==0,'=':comparison==0,'>':comparison>0,'<':comparison<0,'>=':comparison>=0,'<=':comparison<=0}[op]
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
        terms = [term(t,isinstance(expr,FabricRule),isinstance(expr,ForgeRule)) for t in expr.split()] if isinstance(expr,str) else []
        alternatives.append(False if False in terms else None if not terms or None in terms else True)
    return True if True in alternatives else None if None in alternatives else False


def metadata(source,loader='fabric'):
    if loader=='mix':
        with zipfile.ZipFile(source) as jar:
            names=set(jar.namelist())
            if 'META-INF/MANIFEST.MF' in names and 'META-INF/services/cpw.mods.modlauncher.api.ITransformationService' in names:
                manifest=jar.read('META-INF/MANIFEST.MF').decode('utf8','replace').replace('\r\n ','')
                fields=dict(line.split(': ',1) for line in manifest.splitlines() if ': ' in line)
                if fields.get('Automatic-Module-Name')=='org.sinytra.connector':
                    return [dict(id='connector',provides=['connectormod'],version=fields.get('Implementation-Version','?'),depends={'fabric_api':'*'})]
            if 'META-INF/mods.toml' in names or 'META-INF/jarjar/metadata.json' in names:
                mods=metadata(source,'forge')
                for mod in mods:
                    if mod['id'] in ('connector','connectormod'):
                        mod.setdefault('provides',[]).extend(k for k in ('connector','connectormod') if k != mod['id'] and k not in mod.get('provides',[]))
                        mod.setdefault('depends',{}).setdefault('fabric_api','*')
                return mods
        mods=metadata(source,'fabric')
        if mods and mods[0]['id']=='forgeconfigapiport' and 'net/minecraftforge/fml/config/ModConfig.class' in names:
            mods[0]['_loader_problem']='Fabric 配置移植包与 Forge 自带配置类重复；需要 Connector Extras 的桥接实现'
        if mods:
            mods[0].setdefault('depends',{}).setdefault('connector','*')
            mods[0]['depends'].setdefault('fabric_api','*')
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
            for field in ('depends','breaks','conflicts'):
                for key,rule in m.get(field,{}).items():
                    m[field][key]=[FabricRule(x) if isinstance(x,str) else x for x in rule] if isinstance(rule,list) else FabricRule(rule) if isinstance(rule,str) else rule
            m['_platform']='fabric'
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
            problem=m.get('_runtime_failure') or m.get('_loader_problem')
            if problem:
                issue('error',name,name,'*',[m['version']],problem)
                if repairs is not None and m is mods[0]:repairs[name]=f
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
    def __init__(self, progress=lambda message: None, seconds=None):
        self.cancelled=threading.Event()
        self.deadline=float("inf") if seconds is None else time.monotonic()+seconds
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
    request=Request(url,headers={'User-Agent':'FabricMedic/2.3 (local desktop utility)'})
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


def resolve(target, requirements, game, folder, accept=None, loader='fabric', project=None, file_loader=None, control=None, native_only=False):
    control=control or LookupControl()
    control.check()
    if loader=='mix':
        bridge={'forgeconfigapiport':'connector-extras','connector':'connector','connectormod':'connector','fabric_api':'forgified-fabric-api','fabric-api':'forgified-fabric-api','fabric':'forgified-fabric-api'}
        errors=[]
        for platform in (('forge',) if target in bridge or native_only else ('forge','fabric')):
            try:
                return resolve(target,requirements,game,folder,accept,platform,bridge.get(target),'mix',control,native_only)
            except ValueError as exc:
                errors.append(str(exc))
            except HTTPError as exc:
                if exc.code!=404:raise
                errors.append(str(exc))
        raise ValueError('没有找到兼容桥接组合的 '+target+'：'+' / '.join(errors))
    aliases={'cloth-config':'cloth-config','cloth_config':'cloth-config','fabric':'fabric-api',
             'fabric-api':'fabric-api','inventoryprofilesnext':'inventory-profiles-next','yet_another_config_lib_v3':'yacl','puzzleslib':'puzzles-lib','kotlinforforge':'kotlin-for-forge','mezz_config':'mezzconfig','fabric-language-kotlin':'fabric-language-kotlin'}
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
                if any(m.get('_loader_problem') for m in mods):continue
                if native_only and (not mods or mods[0].get('_platform')!='forge'):continue
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
    for group in live.values():
        for mod in group:
            problem=mod.get('_runtime_failure') or mod.get('_loader_problem')
            if problem:problems.append(mod['id']+'：'+problem)
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
