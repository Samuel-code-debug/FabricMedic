import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from core import Path, tempfile, metadata, matches, analyze, resolve, apply, restore, backup_root, install_verified


from workbench import Workbench


class App(Workbench):
    def __init__(self, win):
        self.win=win
        threading.excepthook=self._thread_crash
        win.title('模组体检台 · Fabric')
        win.geometry('980x680')
        self.temp=tempfile.TemporaryDirectory()
        self.folder=None
        self.busy=False
        self.game=tk.StringVar()
        self.setup()
        self.say('扫描只生成方案。点击冲突行可选择保留谁；应用前请关闭游戏。')

    def say(self,text,append=False):
        self.log.config(state='normal')
        if not append:
            self.log.delete('1.0','end')
        elif self.log.index('end-1c')!='1.0':
            self.log.insert('end','\n')
        self.log.insert('end',text)
        self.log.see('end')
        self.log.config(state='disabled')
        if self.busy and not self.drawer_open:
            self.toggle_drawer()

    def _thread_crash(self,args):
        try:
            from pathlib import Path as _P
            import time as _t
            d=_P(os.environ.get('LOCALAPPDATA',str(_P.home())))/'FabricMedic'
            d.mkdir(parents=True,exist_ok=True)
            with open(d/'crash.log','a',encoding='utf-8') as f:
                f.write('\n=== %s [thread] ===\n'%_t.strftime('%Y-%m-%d %H:%M:%S'))
                import traceback as _tb
                _tb.print_exception(args.exc_type,args.exc_value,args.exc_traceback,file=f)
        except Exception:
            pass

    def safe(self,fn):
        if self.busy:
            return
        try:
            fn()
        except Exception as e:
            self.dialog('操作未完成',str(e),'error')

    def choose(self):
        path=filedialog.askdirectory(title='选择 PCL 实例的 mods 文件夹')
        if path:
            folder=Path(path).resolve()
            if folder.name.lower()!='mods':
                raise ValueError('请选择名为 mods 的文件夹')
            config=folder.parent/(folder.parent.name+'.json')
            data=json.loads(config.read_text(encoding='utf-8-sig')) if config.is_file() else {}
            version=data.get('clientVersion') or data.get('inheritsFrom')
            if not version:
                version=self.dialog('实例版本','Minecraft 游戏版本（例如 26.1.2）',mode='input',initialvalue=self.game.get())
            if not version:
                return
            self.game.set(version.strip())
            self.folder=folder
            self.scan()
            self.remember()
            self.navigate('home')

    def snapshot(self):
        return {p:(p.stat().st_size,p.stat().st_mtime_ns) for p in self.folder.glob('*.jar')}

    def scan(self):
        if not self.folder:
            return
        self.version=self.game.get().strip()
        if not self.version:
            raise ValueError('请填写游戏版本')
        self.disk=self.snapshot()
        self.mods={}
        self.off=set()
        self.reasons={}
        self.proposed=set()
        self.swaps={}
        for p in sorted(self.disk):
            try:
                if p.is_symlink():
                    raise ValueError('链接文件')
                mods=metadata(p,self.loader)
                if not mods:
                    raise ValueError('非当前加载器的客户端模组或没有元数据')
                reason=mods[0].get('depends',{}).get('minecraft','*')
                ok=matches(self.version,reason)
                if ok is False:
                    self.off.add(p)
                self.reasons[p]=('版本不符：' if ok is False else '需人工核对：' if ok is None else '游戏版本：')+str(reason)
                self.mods[p]=mods
            except Exception as e:
                self.mods[p]=[]
                self.reasons[p]='保留未识别文件：'+str(e)
        self.location.config(text=f'{self.folder}    ·    Minecraft {self.version} / {self.loader.title()}')
        self.initial_off=set(self.off)
        self.refresh()

    def active(self):
        return {p:m for p,m in self.mods.items() if p not in self.off}

    def refresh(self,extra=''):
        self.tree.delete(*self.tree.get_children())
        self.pairs,_,_=analyze(self.mods,self.version)
        repairs={}
        pairs,missing,notes=analyze(self.active(),self.version,repairs)
        # 把「缺哪个前置」落到表格行上，不再只写在输出区
        missing_by_mod={}
        for dep,reqs in missing.items():
            for modname,rule in reqs:
                missing_by_mod.setdefault(modname,[]).append(dep)
        self.rows=list(self.mods)
        for i,p in enumerate(self.rows):
            details=[self.reasons.get(p,'Modrinth · 已校验')]
            lacking=[]
            for m in self.mods.get(p,[]):
                lacking.extend(missing_by_mod.get(m.get('id'),[]))
            if lacking:
                details.insert(0,'缺少前置：'+', '.join(sorted(set(lacking))))
            for pair,why in self.pairs.items():
                if p in pair:
                    other=next(x for x in pair if x!=p)
                    details.append(other.name+' ['+' / '.join(sorted(why))+']')
            state='× 移出' if p in self.off else '＋ 待安装' if p in self.proposed else ('⚠ 缺前置' if lacking else '✓ 保留')
            if p in repairs.values():
                state='⚠ 待替换'
                details.insert(0,'依赖版本不符：现有 '+self.mods[p][0]['version'])
            if p in self.swaps:
                state='↻ 备份替换'
                details.insert(0,'替换为 '+self.mods[self.swaps[p]][0]['version'])
            self.tree.insert('','end',iid=str(i),values=(state,p.name,'；'.join(details)))
        lines=[f'{a.name} ↔ {b.name}：'+ '；'.join(sorted(v)) for (a,b),v in pairs.items()]
        lines += [f'缺少 {key} ← '+', '.join(f'{n} {r}' for n,r in req) for key,req in missing.items()]
        append=getattr(self,'_log_append',False)
        self._log_append=False
        self.say('\n'.join(filter(None,[extra,*lines,*notes])) or '已识别的模组未发现声明冲突或缺失前置。',append=append)

    def toggle(self,event):
        row=self.tree.identify_row(event.y)
        if self.busy or not row or self.tree.identify_region(event.x,event.y)!='cell':
            return
        p=self.rows[int(row)]
        if not self.mods[p]:
            return
        for old,new in list(self.swaps.items()):
            if p in (old,new):
                if self.dialog('取消替换','撤销这对新旧文件的替换计划，保留原文件？'):
                    del self.swaps[old]
                    self.off.discard(old)
                    self.proposed.remove(new)
                    del self.mods[new]
                    self.refresh()
                return
        others={x for pair in self.pairs if p in pair for x in pair if x!=p and x not in self.off}
        names='、'.join(x.name for x in others)
        if p in self.off:
            if others and not self.dialog('仍要同时保留？',f'{p.name} 与 {names} 存在冲突，可能不稳定甚至无法启动。继续勾选？'):
                return
            self.off.remove(p)
        elif others:
            choice=self.dialog('选择保留项',f'保留 {p.name}，将 {names} 标 ×？\n选“否”仅将 {p.name} 标 ×。',mode='choice')
            if choice is None:
                return
            self.off.update(others if choice else [p])
        else:
            self.off.add(p)
        self.refresh()

    def check(self):
        if not self.folder or not hasattr(self,'disk'):
            raise ValueError('请先选择实例并扫描')
        if self.version!=self.game.get().strip() or self.disk!=self.snapshot():
            raise ValueError('游戏版本或目录内容已变，请重新扫描')

    def auto_install(self):
        self.check()
        if self.off!=self.initial_off or self.proposed:
            raise ValueError('已有手动方案，请先应用，或重新扫描后再自动安装。')
        self.download(automatic=True)

    def download(self,automatic=False):
        self.check()
        active=dict(self.mods) if automatic else self.active()
        wrong_game={self.mods[p][0]['id']:p for p in self.initial_off} if automatic else {}
        if automatic:
            for path,group in active.items():
                if any(matches(self.version,m.get('depends',{}).get('minecraft','*')) is False for m in group):
                    wrong_game[group[0]['id']]=path
        repairs={}
        if not analyze(active,self.version,repairs)[1] and not repairs and not wrong_game:
            self.refresh('没有缺失或可自动替换的前置。')
            return
        self.busy=True
        out=queue.Queue()
        progress=queue.Queue()
        self.say('正在查找并校验兼容版本，全部就绪后将自动安装。' if automatic else '正在查找前置，下载后可预览。')
        resolver=resolve if self.loader=="fabric" else lambda *args,**kw:resolve(*args,**kw,loader="forge")
        def worker():
            found={}
            errors=[]
            tried=set()
            swaps={}
            try:
                for _ in range(60):
                    live={p:m for p,m in (active|found).items() if p not in swaps}
                    repairs={}
                    missing=analyze(live,self.version,repairs)[1]
                    repairs.update({k:p for k,p in wrong_game.items() if p in live})
                    targets=sorted((missing.keys()|repairs.keys())-tried,key=lambda key:(key not in wrong_game,key))
                    if not targets:
                        break
                    k=targets[0]
                    tried.add(k)
                    progress.put('正在查找 '+k+' …')
                    try:
                        old=repairs.get(k)
                        if old and (old not in self.disk or old in self.swaps.values()):
                            raise ValueError('该组件已在方案中，请人工核对')
                        rules=[(m['id'],m['depends'][k]) for group in live.values() for m in group if k in m.get('depends',{})]
                        def game_ok(group):
                            return all(matches(self.version,m.get('depends',{}).get('minecraft','*')) is not False for m in group)
                        try:
                            if k in wrong_game:
                                p,mods=resolver(k,rules,self.version,Path(self.temp.name),accept=game_ok)
                            else:
                                p,mods=resolver(k,rules,self.version,Path(self.temp.name))
                        except ValueError as reason:
                            if not automatic or not old or k in wrong_game or '没有找到' not in str(reason):
                                raise
                            owners=[f for f,group in live.items() if any(k in m.get('depends',{}) and matches(live[old][0]['version'],m['depends'][k]) is False for m in group)]
                            if len(owners)!=1 or owners[0] not in self.disk:
                                raise
                            installed=live[old][0]['version']
                            old=owners[0]
                            dep=k
                            k=live[old][0]['id']
                            requires=[(m['id'],m['depends'][k]) for group in live.values() for m in group if k in m.get('depends',{})]
                            def compatible(group):
                                return game_ok(group) and all(matches(installed,m['depends'][dep]) is True for m in group if dep in m.get('depends',{}))
                            p,mods=resolver(k,requires,self.version,Path(self.temp.name),accept=compatible)
                        if (not automatic and p in self.off) or any(f.name==p.name for f in self.disk):
                            raise ValueError('同名文件已存在或已手动取消')
                        if old:
                            if mods[0]['id']!=k:
                                raise ValueError('候选文件不是同一独立模组')
                            trial={f:group for f,group in live.items() if f!=old}
                            trial[p]=mods
                            if any(p in pair for pair in analyze(trial,self.version)[0]):
                                raise ValueError('候选版本与当前保留的模组有已声明冲突')
                            swaps[old]=p
                        found[p]=mods
                    except Exception as e:
                        errors.append(f'{k}：{e}')
                        progress.put('　'+k+'：'+str(e))
            except BaseException as e:
                errors.append(f'{type(e).__name__}: {e}')
            finally:
                out.put((found,errors,swaps))
        started=time.monotonic()
        def finish():
            while not progress.empty():
                self.say(progress.get(),append=True)
            self._log_append=True
            if out.empty():
                if time.monotonic()-started>120:
                    self.busy=False
                    self.refresh('查找超时（2 分钟无结果），已中断本轮。')
                    return
                self.win.after(150,finish)
                return
            found,errors,swaps=out.get()
            self.busy=False
            self._log_append=True
            if automatic:
                try:
                    self.check()
                    if errors:
                        raise ValueError('\n'.join(errors))
                    if not found:
                        raise ValueError('没有找到可安装的文件')
                    kept={p:m for p,m in active.items() if p not in swaps}
                    batch=install_verified(self.folder,swaps,found,kept,self.version,self.loader)
                except Exception as exc:
                    self.refresh('自动修复未完成：'+str(exc))
                    return
                self.scan()
                changes='、'.join(f"{mods[0]['id']} {mods[0]['version']}" for mods in found.values())
                self.refresh(f'安装及落盘校验通过：{changes}\n备份：{batch}')
                return
            self.mods.update(found)
            self.proposed.update(found)
            self.swaps.update(swaps)
            self.off.update(swaps)
            self.refresh(f'准备好 {len(found)} 个文件。'+'\n'+'\n'.join(errors))
        threading.Thread(target=worker,daemon=True).start()
        finish()

    def commit(self):
        self.check()
        removed=self.off & self.disk.keys()
        added=self.proposed-self.off
        if not removed and not added:
            self.refresh('当前方案没有文件变更。')
            return
        pairs,missing,notes=analyze(self.active(),self.version)
        msg=[*('备份移出 '+p.name for p in sorted(removed)),*('安装 '+p.name for p in sorted(added))]
        if pairs or missing or notes:
            msg.append('仍有冲突、缺失前置或未确认的要求，游戏可能无法启动。')
        if self.dialog('游戏关闭后应用', '\n'.join(msg)+'\n\n执行这些变更？'):
            batch=apply(self.folder,removed,added)
            self.scan()
            self.refresh('已应用，备份批次：'+str(batch))

    def undo(self):
        self.check()
        root=backup_root(self.folder)
        if not root.exists():
            raise ValueError('此实例尚无备份')
        selected=filedialog.askdirectory(initialdir=root,title='选择要撤销的备份批次')
        if selected and self.dialog('撤销此批变更','恢复移出的模组，并移走该批次安装的前置？'):
            batch=Path(selected)
            restore(self.folder,batch)
            self.scan()
            self.refresh('已恢复：'+batch.name)


if __name__=='__main__':
    # 崩溃日志：窗口版没有控制台，异常会静默吞掉，全部写到 crash.log
    import os as _os, sys as _sys, time as _time, traceback as _tb
    from pathlib import Path as _Path
    _log_dir=_Path(_os.environ.get('LOCALAPPDATA',str(_Path.home())))/'FabricMedic'
    _log_file=_log_dir/'crash.log'

    def _crash(exc_type, exc, tb):
        try:
            _log_dir.mkdir(parents=True, exist_ok=True)
            with open(_log_file,'a',encoding='utf-8') as f:
                f.write('\n=== %s ===\n' % _time.strftime('%Y-%m-%d %H:%M:%S'))
                _tb.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        try:
            from tkinter import messagebox as _mb
            _mb.showerror('出错了', ''.join(_tb.format_exception_only(exc_type, exc)) +
                          '\n\n详情见：%s' % _log_file)
        except Exception:
            pass

    _sys.excepthook=_crash
    win=tk.Tk()
    import ctypes
    from ctypes import wintypes
    win.attributes('-alpha',0)
    app=App(win)
    win.report_callback_exception=_crash
    class MonitorInfo(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('bounds',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]
    user=ctypes.windll.user32
    point=wintypes.POINT()
    user.GetCursorPos(ctypes.byref(point))
    user.MonitorFromPoint.argtypes=[wintypes.POINT,wintypes.DWORD]
    user.MonitorFromPoint.restype=wintypes.HANDLE
    monitor=user.MonitorFromPoint(point,2)
    info=MonitorInfo()
    info.size=ctypes.sizeof(info)
    if user.GetMonitorInfoW(wintypes.HANDLE(monitor),ctypes.byref(info)):
        r=info.work
        width=min(1190,r.right-r.left)
        height=min(720,r.bottom-r.top)
        win.geometry(f'{width}x{height}+{r.left+(r.right-r.left-width)//2}+{r.top+(r.bottom-r.top-height)//2}')
    win.update_idletasks()
    win.after_idle(lambda:app.ease('window',lambda t:win.attributes('-alpha',max(0,(t-.28)/.72)),motion='window',seconds=.35))
    win.mainloop()
