from motion import inverse, transition, transition_page, settle
from chrome import round_widget, round_window, titlebar, Scrollbar
import math
import os
import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

THEMES = {
    '朱红': ('#c62332','#b61c2a','#971526','#39dccd','#5ce4d6','#74ffeb'),
    '石墨': ('#191919','#222222','#303030','#efefed','#aaa9a7','#92b7ed'),
    '纸白': ('#faf9f6','#efece7','#dedbd4','#272624','#625e59','#305e96'),
    '深海': ('#17202a','#202c39','#304051','#e4edf3','#a1b1c2','#90c8c8'),
}


class Workbench:
    def setup(self):
        self.pref=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'FabricMedic'/'workbench.json'
        try:
            self.prefs=json.loads(self.pref.read_text(encoding='utf8'))
        except (OSError, ValueError):
            self.prefs={}
        self.anim={}
        self.buttons={}
        self.page='home'
        self.drawer_open=False
        self.wheel=None
        self.style=ttk.Style(self.win)
        self.style.theme_use('clam')
        self.win.geometry('1190x720')
        self.win.minsize(800,490)
        self.loader=self.prefs.get('loader','fabric')
        titlebar(self)
        self.rail=ttk.Frame(self.win,style='Side.TFrame',width=190,padding=(10,18))
        self.rail.pack(side='left',fill='y')
        self.rail.pack_propagate(False)
        ttk.Label(self.rail,text='工作空间',style='Side.TLabel').pack(anchor='w',pady=(0,12))
        for text,page,icon in [('主页','home','⌂'),('设置','settings','⚙')]:
            button=self.button(self.rail,text,lambda p=page:self.navigate(p))
            button.pack(fill='x')
            glyph=tk.Label(button,text=icon,bd=0,font=('Microsoft YaHei UI',10))
            glyph.place(x=30,rely=.5,anchor='center',width=20,height=22)
            button.glyph=glyph
            glyph.bind('<ButtonRelease-1>',lambda e,b=button:b.action())
            glyph.bind('<Enter>',lambda e,b=button:b.event_generate('<Enter>'))
            glyph.bind('<Leave>',lambda e,b=button:b.event_generate('<Leave>'))

        ttk.Label(self.rail,text='版本',style='Side.TLabel').pack(anchor='w',pady=(28,7))
        self.instance_view=tk.Canvas(self.rail,bd=0,highlightthickness=0,height=1)
        self.instance_view.pack(fill='both',expand=True)
        self.instances=ttk.Frame(self.instance_view,style='Side.TFrame')
        rows=self.instance_view.create_window(0,0,anchor='nw',window=self.instances)
        self.instance_view.bind('<Configure>',lambda e:self.instance_view.itemconfigure(rows,width=e.width))
        self.instances.bind('<Configure>',lambda e:self.instance_view.configure(scrollregion=(0,0,e.width,max(e.height,self.instance_view.winfo_height()))))
        self.instance_view.bind('<MouseWheel>',self.scroll_instances)
        self.panel_button=self.button(self.rail,'☰    操作面板',self.open_wheel)
        self.panel_button.pack(fill='x',side='bottom',ipady=4)
        self.workspace=ttk.Frame(self.win)
        self.workspace.pack(fill='both',expand=True)
        self.drawer=ttk.Frame(self.workspace,width=0,style='Side.TFrame')
        self.drawer.pack(side='right',fill='y')
        self.drawer.pack_propagate(False)
        self.button(self.drawer,'输出     ×',self.toggle_drawer).pack(fill='x',padx=8,pady=12)
        self.log=tk.Text(self.drawer,wrap='word',relief='flat',font=('Microsoft YaHei UI',10),padx=16,pady=12)
        self.log.pack(fill='both',expand=True)
        self.deck=ttk.Frame(self.workspace)
        self.deck.pack(fill='both',expand=True)
        self.home=ttk.Frame(self.deck,padding=(32,26))
        self.version_page=ttk.Frame(self.deck,padding=(18,18))
        self.settings=ttk.Frame(self.deck,padding=30)
        self.pages={'home':self.home,'version':self.version_page,'settings':self.settings}
        self.home.place(relwidth=1,relheight=1)
        ttk.Label(self.home,text='Fabric Medic  /  更新记录',style='Muted.TLabel').pack(anchor='w')
        ttk.Separator(self.home).pack(fill='x',pady=(12,22))
        ttk.Label(self.home,text='更新内容',style='Title.TLabel').pack(anchor='w')
        for release,lines in [
            ('v18.6',('主页集中展示更新记录。','点击左侧版本名称可查看模组、依赖和冲突。')),
            ('v18.5.6',('启动说明移到主窗口内，修复说明被遮挡时无法操作的问题。',)),
            ('v18.5.5',('调整窗口拖动定位，给说明卡片加上灰色轮廓。',)),
        ]:
            ttk.Label(self.home,text=release,font=('Segoe UI',13,'bold')).pack(anchor='w',pady=(18,5))
            for line in lines:
                ttk.Label(self.home,text='•  '+line,wraplength=500).pack(anchor='w',pady=2)
        head=ttk.Frame(self.version_page)
        head.pack(fill='x')
        ttk.Label(head,text='模组工作台',style='Title.TLabel').pack(side='left')
        self.button(head,'◧   输出',self.toggle_drawer).pack(side='right')
        self.location=ttk.Label(self.version_page,text='从左下角操作面板添加第一个实例',style='Muted.TLabel',wraplength=560)
        self.location.pack(anchor='w',pady=(10,22))
        body=round_widget(ttk.Frame(self.version_page,style="Side.TFrame",padding=5),12)
        self.table_frame=body
        body.pack(fill='both',expand=True)
        inner=round_widget(ttk.Frame(body),9)
        inner.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(inner,columns=('state','name','why'),show='headings',selectmode='browse')
        for c,label,width in [('state','处理状态',96),('name','模组文件',280),('why','版本要求 / 冲突对象',340)]:
            self.tree.heading(c,text=label,anchor='w')
            self.tree.column(c,width=width,minwidth=80,stretch=c!='state')
        sx=Scrollbar(inner,orient='horizontal',command=self.tree.xview)
        sy=Scrollbar(inner,orient='vertical',command=self.tree.yview)
        self.scrollbars=(sx,sy)
        def display(scroll,first,last):
            scroll.set(first,last)
            if float(last)-float(first)<.99999:
                horizontal=scroll is sx
                scroll.place(relx=0 if horizontal else 1,rely=1 if horizontal else 0,
                             anchor='sw' if horizontal else 'ne',**({'relwidth':1} if horizontal else {'relheight':1}))
                scroll.tk.call('raise',scroll._w)
            else:
                scroll.place_forget()
        self.tree.configure(xscrollcommand=lambda a,b:display(sx,a,b),yscrollcommand=lambda a,b:display(sy,a,b))
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<ButtonRelease-1>',self.toggle)
        ttk.Label(self.settings,text='设置',style='Title.TLabel').pack(anchor='w')
        self.setting_fields=[]
        for label,key,options in [('外观颜色','theme',list(THEMES)),('动画速度','speed',['慢','标准','快','关闭'])]:
            ttk.Label(self.settings,text=label).pack(anchor='w',pady=(26,8))
            default=options[0] if key=='theme' else '标准'
            if key=='theme': default='石墨'
            control=self.button(self.settings,self.prefs.get(key,default)+'     ﹀',lambda:None)
            self.setting_fields.append(control)
            control.action=lambda k=key,opts=options,c=control:self.palette(k,opts,c)
            control.pack(anchor='w',ipadx=12)
        self.paint()
        self.list_instances()
        self.win.bind('<Escape>',lambda e:self.close_wheel() if self.wheel else None,add='+')

    def button(self,parent,text,cmd,caption=False,**options):
        b=round_widget(tk.Label(parent,text=text,relief='flat',bd=0,highlightthickness=0,
                                 padx=13,pady=6,cursor='hand2',takefocus=True,
                                 font=('Microsoft YaHei UI',10),**options))
        b.action=cmd
        b.bind('<ButtonRelease-1>',lambda e:b.action() if 0<=e.x<b.winfo_width() and 0<=e.y<b.winfo_height() else None)
        b.bind('<Return>',lambda e:b.action())
        b.bind('<space>',lambda e:b.action())
        self.buttons[b]=[caption,0.]
        def hover(target):
            start=self.buttons[b][1]
            self.ease(b,lambda t:self.tint(b,start+(target-start)*t),motion='hover_in' if target else 'hover_out')
        def cleanup(e):
            if b in self.anim:
                self.win.after_cancel(self.anim.pop(b))
            self.buttons.pop(b,None)
        b.bind('<Enter>',lambda e:hover(1))
        b.bind('<Leave>',lambda e:hover(0))
        b.bind('<Destroy>',cleanup)
        if hasattr(self,'colors'):
            self.tint(b,0)
        return b

    def tint(self,b,amount):
        caption=self.buttons[b][0]
        self.buttons[b][1]=amount
        base=self.style.lookup('Cap.TFrame','background') if caption else self.colors[1]
        end='#459396' if caption else self.colors[2]
        if getattr(b,"selected",False):
            base,end=end,self.colors[4]
            amount*=.28
        rgb=[round(int(base[i:i+2],16)*(1-amount)+int(end[i:i+2],16)*amount) for i in (1,3,5)]
        color='#%02x%02x%02x'%tuple(rgb)
        fg=inverse(color)
        b.configure(bg=color,fg=fg)
        if hasattr(b,"glyph"):b.glyph.configure(bg=color,fg=fg)

    def palette(self,key,options,control):
        pop=tk.Toplevel(self.win)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.transient(self.win)
        pop.attributes('-alpha',0)
        bg=self.colors[1]
        pop.configure(bg=bg)
        shell=tk.Frame(pop,bg=bg,padx=18,pady=12)
        shell.pack(fill='both',expand=True)
        for value in options:
            shade=THEMES[value][0] if key=='theme' else bg
            label=tk.Label(shell,text=('●   ' if key=='theme' else '')+value,anchor='w',width=18,
                           padx=12,pady=6,bg=shade,fg=inverse(shade),cursor='hand2',takefocus=True)
            label.pack(fill='x',pady=2)
            label.bind('<Button-1>',lambda e,v=value:close(v))
            label.bind('<Return>',lambda e,v=value:close(v))
        pop.update_idletasks()
        x=self.win.winfo_rootx()+(self.win.winfo_width()-pop.winfo_reqwidth())//2
        y=self.win.winfo_rooty()+54
        def frame(amount):
            pop.geometry(f'+{max(0,x)}+{max(0,y-24+round(24*amount))}')
            pop.attributes('-alpha',amount)
        closing=False
        def close(value=None):
            nonlocal closing
            if closing:return
            closing=True
            def finish():
                pop.destroy()
                if value is not None:
                    control.configure(text=value+'     ﹀')
                    self.preference(key,value)
            start=float(pop.attributes('-alpha'))
            self.ease('notice',lambda t:frame(start*(1-t)),finish)
        pop.bind('<Escape>',lambda e:close())
        pop.bind('<ButtonPress-1>',lambda e:close() if not (pop.winfo_rootx()<=e.x_root<pop.winfo_rootx()+pop.winfo_width() and pop.winfo_rooty()<=e.y_root<pop.winfo_rooty()+pop.winfo_height()) else None,add='+')
        frame(0)
        pop.deiconify()
        pop.grab_set()
        pop.focus_force()
        self.ease('notice',frame)

    def persist(self):
        self.pref.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.pref.with_suffix('.'+str(os.getpid())+'.tmp')
        tmp.write_text(json.dumps(self.prefs,ensure_ascii=False),encoding='utf8')
        tmp.replace(self.pref)

    def preference(self,key,value):
        def change():
            self.prefs[key]=value
            self.persist()
            self.paint()
        if key=='theme':
            transition(self,self.win,change,radial=True)
        else:
            change()

    def paint(self):
        self.colors=bg,side,sel,fg,muted,accent=THEMES.get(self.prefs.get('theme'),THEMES['石墨'])
        fg=inverse(bg)
        self.resize_grip.configure(bg=bg,fg=muted)
        s=self.style
        cap={'石墨':'#222222','朱红':'#dc1825','纸白':'#f9f9f9','深海':'#28566c'}.get(self.prefs.get('theme'),'#222222')
        self.loader_arrow.configure(bg=cap)
        self.loader_arrow.itemconfigure('chevron',fill=inverse(cap))
        s.configure('Cap.TFrame',background=cap)
        s.configure('Cap.TLabel',background=cap,foreground=inverse(cap),font=('Segoe UI',14,'bold'))
        s.configure('Cap.TButton',background=cap,foreground='#ffffff',padding=(8,4),borderwidth=0)
        s.map('Cap.TButton',background=[('active','#378084')])
        for scroll in self.scrollbars:
            scroll.configure(bg=side)
            scroll.color=muted
            scroll.draw()
        s.layout('Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
        s.layout('Treeview.Heading',[('Treeheading.padding',{'sticky':'nswe','children':[('Treeheading.text',{'sticky':'we'})]})])
        self.win.configure(bg=bg)
        s.configure('.',background=bg,foreground=fg,bordercolor=side,lightcolor=side,darkcolor=side,troughcolor=side,font=('Microsoft YaHei UI',10))
        s.configure('Side.TFrame',background=side)
        s.configure('Side.TLabel',background=side,foreground=muted)
        s.configure('Brand.TLabel',background=side,foreground=fg,font=('Segoe UI',15,'bold'))
        s.configure('Title.TLabel',font=('Microsoft YaHei UI',18,'bold'))
        s.configure('Muted.TLabel',foreground=muted)
        s.configure('TButton',background=side,borderwidth=0,padding=7)
        s.map('TButton',background=[('active',sel)])
        s.configure('Treeview',background=bg,fieldbackground=bg,foreground=fg,rowheight=34,borderwidth=0)
        s.configure('Treeview.Heading',background=side,foreground=muted,padding=7)
        s.map('Treeview',background=[('selected',sel)],foreground=[('selected',accent)])
        s.map('TCombobox',fieldbackground=[('readonly',side)],foreground=[('readonly',fg)])
        self.instance_view.configure(bg=side)
        self.log.configure(bg=side,fg=inverse(side))
        for b,(_,amount) in self.buttons.items():
            self.tint(b,amount)

    def remember(self):
        self.prefs.setdefault('instances',{})[str(self.folder)]=self.version
        self.prefs['last']=str(self.folder)
        self.persist()
        self.list_instances()

    def list_instances(self):
        for row in self.instances.winfo_children():
            row.destroy()
        for path in self.prefs.get('instances',{}):
            row=self.button(self.instances,Path(path).parent.name,lambda p=path:self.pick(p),anchor='w')
            row.selected=path==self.prefs.get('last')
            self.tint(row,0)
            row.pack(fill='x',padx=2,pady=3)
            row.bind('<MouseWheel>',self.scroll_instances)

    def scroll_instances(self,event):
        if self.instances.winfo_height()>self.instance_view.winfo_height():
            self.instance_view.yview_scroll(-1 if event.delta>0 else 1,'units')

    def activate(self,path):
        if not Path(path).is_dir():
            raise ValueError('实例目录已移动，请从操作面板重新选择。')
        self.folder=Path(path)
        self.game.set(self.prefs['instances'][path])
        self.scan()
        self.remember()
        self.show_instance()

    def show_instance(self):
        if self.page=='version' and self.version_page.winfo_viewable():
            self.ease('instance',lambda t:self.version_page.place_configure(y=round(-16*(1-settle(t)))) if self.page=='version' else None,motion='page',seconds=.35)
        else:self.navigate('version')

    def pick(self,path):
        if self.busy:return
        if self.folder==Path(path):
            self.show_instance()
        else:self.safe(lambda:self.activate(path))

    def ease(self,key,step,done=lambda:None,motion=None,seconds=None):
        if key in self.anim:
            self.win.after_cancel(self.anim.pop(key))
        start=time.monotonic()
        duration={'慢':.55,'标准':.33,'快':.18,'关闭':0}.get(self.prefs.get('speed'),.33)
        if motion=='reveal':
            duration*=1.85
        if motion in ('hover_in','hover_out','page','window'):
            duration*=({'hover_in':.1,'hover_out':.2,'page':seconds,'window':seconds}[motion]/.33)
        def tick():
            t=min(1,(time.monotonic()-start)/duration) if duration else 1
            if motion=='page':
                progress=t
            elif motion in ('hover_in','hover_out') or key=='dialog':
                progress=1-(1-t)**3
            else:
                progress=8*t**4 if t<.5 else 1-((-2*t+2)**4)/2
            step(progress)
            if t<1:
                self.anim[key]=self.win.after(15,tick)
            else:
                self.anim.pop(key,None)
                done()
        tick()

    def show_notice(self):
        notice=getattr(self,'notice',None)
        if notice is not None and notice.winfo_exists():
            notice.lift()
            return
        notice=self.notice=round_widget(tk.Frame(self.win,bg='#777777'),12)
        shell=round_widget(ttk.Frame(notice,padding=22),11)
        shell.pack(fill='both',expand=True,padx=1,pady=1)
        ttk.Label(shell,text='说明',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text='修复了一些已知的问题。').pack(anchor='w',pady=14)
        button=self.button(shell,'确定',notice.destroy)
        button.pack(anchor='e')
        button.bind('<Escape>',lambda e:notice.destroy())
        notice.place(relx=.5,rely=.5,anchor='center')
        notice.lift()
        button.focus_set()

    def navigate(self,page):
        self.close_wheel()
        finish=getattr(self,'finish_page',None)
        if finish:finish()
        if page==self.page:
            return
        incoming=self.pages[page]
        outgoing=self.pages[self.page]
        if page!='version' and self.drawer_open:self.toggle_drawer()
        self.page=page
        def change():
            outgoing.place_forget()
            incoming.place(x=0,y=0,relwidth=1,relheight=1)
            incoming.lift()
        transition_page(self,outgoing,incoming,change)

    def toggle_drawer(self):
        self.drawer_open=not self.drawer_open
        start=self.drawer.winfo_width()
        end=min(345,self.workspace.winfo_width()//3) if self.drawer_open else 1
        self.ease('drawer',lambda t:self.drawer.configure(width=round(start+(end-start)*t)))

    def open_wheel(self):
        if self.wheel:
            self.close_wheel()
            return
        panel=self.wheel=round_widget(ttk.Frame(self.rail,style='Side.TFrame',padding=6),10)
        actions=[('选择目录',self.choose),('重新扫描',self.scan),('修复依赖',self.download),('应用方案',self.commit),('自动安装并校验',self.auto_install),('恢复备份',self.undo)]
        stack=ttk.Frame(panel,style='Side.TFrame')
        for text,cmd in actions:
            self.button(stack,text,lambda f=cmd:self.close_wheel(lambda:self.safe(f))).pack(fill='x',pady=1)
        stack.update_idletasks()
        height=stack.winfo_reqheight()
        stack.place(relx=0,rely=1,anchor='sw',relwidth=1,height=height)
        panel.place(in_=self.panel_button,relwidth=1,y=-6,anchor='sw',height=height+12)
        panel.lift()
        panel.opacity=0
        def fade(amount):
            panel.opacity=amount
            surface=self.colors[1]
            for row in stack.winfo_children():
                self.tint(row,self.buttons[row][1])
                ink=row.cget('fg')
                rgb=tuple(round(int(surface[i:i+2],16)*(1-amount)+int(ink[i:i+2],16)*amount) for i in (1,3,5))
                row.configure(fg='#%02x%02x%02x'%rgb)
        panel.fade=fade
        self.ease('wheel',fade,motion='window',seconds=.19)

    def close_wheel(self,done=lambda:None):
        if self.wheel:
            panel=self.wheel
            start=panel.opacity
            def closed():
                panel.destroy()
                self.wheel=None
                done()
            self.ease('wheel',lambda t:panel.fade(start*(1-t)),closed,motion='window',seconds=.16)

    def dialog(self,title,text,mode='confirm',initialvalue=''):
        pop=tk.Toplevel(self.win)
        pop.withdraw()
        pop.title(title)
        pop.overrideredirect(True)
        round_window(pop,12)
        pop.transient(self.win)
        pop.attributes('-alpha',0)
        pop.configure(bg='#777777')
        shell=ttk.Frame(pop,padding=22)
        round_widget(shell,11)
        shell.pack(fill='both',expand=True,padx=1,pady=1)
        ttk.Label(shell,text=title,style='Title.TLabel').pack(anchor='w')
        if len(text)>400:
            view=tk.Text(shell,height=12,width=60,wrap='word',bg=self.colors[0],fg=self.colors[3],relief='flat')
            view.pack(pady=14)
            view.insert('1.0',text)
            view.configure(state='disabled')
        else:
            ttk.Label(shell,text=text,wraplength=460).pack(anchor='w',pady=14)
        entry=None
        if mode=='input':
            entry=ttk.Entry(shell,width=35)
            entry.insert(0,initialvalue)
            entry.pack(fill='x')
        bar=ttk.Frame(shell)
        bar.pack(anchor='e',pady=(14,0))
        result=[None]
        closing=False
        def close(value):
            nonlocal closing
            if closing:return
            closing=True
            result[0]=value
            initial=pop.attributes('-alpha')
            self.ease('dialog',lambda t:pop.attributes('-alpha',float(initial)*(1-t)),pop.destroy)
        if mode in ('choice','input'):
            self.button(bar,'取消',lambda:close(None)).pack(side='left')
        if mode in ('choice','confirm'):
            self.button(bar,'否',lambda:close(False)).pack(side='left',padx=4)
        ok=lambda:close(entry.get() if entry else True)
        self.button(bar,'是' if mode in ('choice','confirm') else '确定',ok).pack(side='left')
        pop.update_idletasks()
        x=self.win.winfo_rootx()+(self.win.winfo_width()-pop.winfo_reqwidth())//2
        y=self.win.winfo_rooty()+(self.win.winfo_height()-pop.winfo_reqheight())//2
        pop.geometry(f'+{max(0,x)}+{max(0,y)}')
        pop.protocol('WM_DELETE_WINDOW',lambda:close(None))
        pop.bind('<Escape>',lambda e:close(None))
        pop.deiconify()
        pop.grab_set()
        (entry or pop).focus_set()
        self.ease('dialog',lambda t:pop.attributes('-alpha',t))
        self.win.wait_window(pop)
        return result[0]
