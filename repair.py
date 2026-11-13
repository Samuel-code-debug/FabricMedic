"""Shared repair planner used by the desktop app and offline validation."""
from core import analyze, matches, ids, JobStopped


def build_plan(active, game, folder, resolver, control, *, loader='fabric', disk=None,
               wrong_game=None, existing_swaps=None, off=(), automatic=False):
    disk=active if disk is None else disk
    wrong_game=wrong_game or {}
    existing_swaps=existing_swaps or {}
    found={}
    errors=[]
    tried=set()
    swaps={}
    seen=set()
    try:
        while True:
            control.check()
            live={p:m for p,m in (active|found).items() if p not in swaps}
            state=(tuple(sorted((str(p),repr(m)) for p,m in live.items())),tuple(sorted(tried)))
            if state in seen:raise ValueError('依赖方案出现循环，请人工核对版本约束')
            seen.add(state)
            repairs={}
            missing=analyze(live,game,repairs)[1]
            repairs.update({k:p for k,p in wrong_game.items() if p in live})
            if loader=='mix':
                originals=[p for p,group in live.items() if group and group[0]['id']=='fabric-api']
                if len(originals)>1:raise ValueError('存在多个原版 Fabric API，请先处理重复文件')
                if originals:repairs['fabric_api']=originals[0]
            targets=sorted((missing.keys()|repairs.keys())-tried,key=lambda key:(key not in ('fabric_api','connector'),key not in wrong_game,key))
            if not targets:
                break
            k=targets[0]
            tried.add(k)
            control.report('正在查找 '+k+' …')
            try:
                old=repairs.get(k)
                if old and (old not in disk or old in existing_swaps.values()):
                    raise ValueError('该组件已在方案中，请人工核对')
                rules=[(m['id'],m['depends'][k]) for group in live.values() for m in group if k in m.get('depends',{})]
                if loader=='mix' and k=='fabric_api':
                    rules += [(m['id'],m['depends'][alias]) for f,group in live.items() if f!=old for m in group for alias in ('fabric-api','fabric') if alias in m.get('depends',{})]
                    existing=[f for f,group in live.items() if group and group[0]['id']=='fabric_api']
                    if existing and old:
                        if not all(matches(live[existing[0]][0]['version'],rule) is True for _,rule in rules):
                            raise ValueError('已安装桥接 API 不满足所有版本约束')
                        swaps[old]=existing[0]
                        continue
                def game_ok(group):
                    return all(matches(game,m.get('depends',{}).get('minecraft','*')) is not False for m in group)
                native=bool(old and loader=='mix' and (live[old][0].get('_runtime_failure') or live[old][0].get('_loader_problem')))
                try:
                    if native:
                        p,mods=resolver(k,rules,game,folder,accept=game_ok,native_only=True)
                    elif k in wrong_game:
                        p,mods=resolver(k,rules,game,folder,accept=game_ok)
                    else:
                        p,mods=resolver(k,rules,game,folder)
                except ValueError as reason:
                    if native or k in wrong_game or '没有找到' not in str(reason):
                        raise
                    owners=[f for f,group in live.items() if any(k in m.get('depends',{}) for m in group)]
                    if len(owners)!=1 or owners[0] not in disk or owners[0] in swaps:
                        raise
                    installed=live[old][0]['version'] if old else None
                    old=owners[0]
                    dep=k
                    k=live[old][0]['id']
                    requires=[(m['id'],m['depends'][k]) for group in live.values() for m in group if k in m.get('depends',{})]
                    control.report('前置无匹配版本，正在查找兼容的 '+k+' 版本 …')
                    def compatible(group):
                        if not game_ok(group):return False
                        dependency_rules=[(m['id'],m['depends'][dep]) for m in group if dep in m.get('depends',{})]
                        if not dependency_rules:return True
                        if installed is not None:
                            return all(matches(installed,rule) is True for _,rule in dependency_rules)
                        try:
                            resolver(dep,dependency_rules,game,folder,accept=game_ok)
                            return True
                        except ValueError:
                            return False
                    p,mods=resolver(k,requires,game,folder,accept=compatible)
                    tried.discard(dep)
                    control.report('兼容方案：替换 '+k+' '+live[old][0]['version']+' → '+mods[0]['version'])
                if (not automatic and p in off) or any(f.name==p.name for f in disk):
                    raise ValueError('同名文件已存在或已手动取消')
                if old:
                    bridge_bundle=(loader=='mix' and k=='forgeconfigapiport' and mods[0]['id']=='connectorextras' and any(k in ids(m) for m in mods))
                    if k not in ids(mods[0]) and not bridge_bundle:
                        raise ValueError('候选文件不是同一独立模组')
                    trial={f:group for f,group in live.items() if f!=old}
                    trial[p]=mods
                    if any(p in pair for pair in analyze(trial,game)[0]):
                        raise ValueError('候选版本与当前保留的模组有已声明冲突')
                    swaps[old]=p
                found[p]=mods
            except JobStopped:
                raise
            except Exception as e:
                errors.append(f'{k}：{e}')
                control.report('　'+k+'：'+str(e))
    except BaseException as e:
        errors.append(f'{type(e).__name__}: {e}')
    return found,errors,swaps
